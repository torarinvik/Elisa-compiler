#!/usr/bin/env python3
"""Scanning an Elisa source for its `export fn` surface — the input every WASM artifact is a
projection of.

Split out of wasm_build.py: the scan is also what test/parity/wasm_build_unit.py exercises
directly, and what the driver's own port in src/driver/emit_wasm_exports.elisa is diffed
against.  Nothing here touches the filesystem except `read_flat_source`, which splices the
include graph the same way the compiler does.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any


SCALAR_TYPES = {
    "i8": "i32",
    "u8": "i32",
    "i16": "i32",
    "u16": "i32",
    "i32": "i32",
    "u32": "i32",
    "i64": "i64",
    "u64": "i64",
    "int": "i64",
    "char": "i64",
    "isize": "i32",
    "usize": "i32",
    "uintptr": "i32",
    "f32": "f32",
    "f64": "f64",
    "bool": "i32",
    "void": "void",
}

EXPORT_RE = re.compile(
    r"^\s*export\s+fn\s+([A-Za-z_][A-Za-z0-9_]*)\s*\((.*)\)"
    r"(?:\s*->\s*([^=]+?))?\s*(?:=\s*([A-Za-z_][A-Za-z0-9_:]*))?\s*$"
)
LINK_NAME_RE = re.compile(r'^\s*@link_name\((?:"([^"]*)"|([A-Za-z_][A-Za-z0-9_]*))\)\s*$')
MAIN_RE = re.compile(
    r"^\s*def\s+main\s*\((.*)\)\s*(?:->\s*([^:]+?))?\s*:\s*$"
)
INCLUDE_RE = re.compile(r"^\s*(?:#\s*)?include\s+['\"]([^'\"]+)['\"]\s*$")



class WasmBuildError(RuntimeError):
    pass


def split_top_level(text: str, delimiter: str = ",") -> list[str]:
    result: list[str] = []
    start = 0
    depth = 0
    quote = ""
    escaped = False
    for index, char in enumerate(text):
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
            continue
        if char in "'\"":
            quote = char
        elif char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == delimiter and depth == 0:
            result.append(text[start:index].strip())
            start = index + 1
    result.append(text[start:].strip())
    return [part for part in result if part]


def split_assignment(text: str) -> tuple[str, str | None]:
    depth = 0
    quote = ""
    escaped = False
    for index, char in enumerate(text):
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
            continue
        if char in "'\"":
            quote = char
        elif char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == "=" and depth == 0:
            return text[:index].strip(), text[index + 1 :].strip()
    return text.strip(), None


def read_flat_source(path: Path, seen: set[Path] | None = None, stack: list[Path] | None = None) -> str:
    seen = set() if seen is None else seen
    stack = [] if stack is None else stack
    path = path.resolve()
    if path in stack:
        chain = " -> ".join(str(item) for item in [*stack, path])
        raise WasmBuildError(f"cyclic include while building WASM: {chain}")
    if path in seen:
        return ""
    if not path.is_file():
        raise WasmBuildError(f"missing source/include: {path}")
    seen.add(path)
    stack.append(path)
    output: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines(keepends=True):
        match = INCLUDE_RE.match(line.rstrip("\r\n"))
        if match:
            include = Path(match.group(1))
            include = include if include.is_absolute() else path.parent / include
            output.append(read_flat_source(include, seen, stack))
        else:
            output.append(line)
    stack.pop()
    return "".join(output)


def normalize_type(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^(?:mutable|lmut|heap|stack|static)\s+", "", text)
    return re.sub(r"\s+", "", text)


def parse_parameter(text: str, function: str) -> dict[str, Any]:
    declaration, default = split_assignment(text)
    if ":" not in declaration:
        raise WasmBuildError(f"exported function {function!r} has a parameter without a name/type: {text!r}")
    name, type_text = declaration.split(":", 1)
    name = name.strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise WasmBuildError(f"exported function {function!r} has an invalid parameter name {name!r}")
    return {
        "name": name,
        "type": normalize_type(type_text),
        "default": default,
    }


def abi_for_type(type_text: str, function: str, position: str) -> tuple[str, str]:
    normalized = normalize_type(type_text)
    if normalized.endswith("?"):
        raise WasmBuildError(
            f"{function}: {position} type {type_text!r} is nullable; use an explicit scalar/pointer "
            "adapter because nullable aggregates do not have a stable JS ABI"
        )
    if normalized == "cstr":
        return "string", "i32"
    if normalized.endswith("&") or normalized.endswith("&&"):
        return "pointer", "i32"
    if normalized in SCALAR_TYPES:
        return "scalar", SCALAR_TYPES[normalized]
    raise WasmBuildError(
        f"{function}: {position} type {type_text!r} is not directly representable in the generated "
        "WASM bindings; export a scalar or pointer adapter"
    )


def parse_exports(source: str) -> list[dict[str, Any]]:
    exports: list[dict[str, Any]] = []
    seen: set[str] = set()
    pending_link_name: str | None = None
    for line_number, line in enumerate(source.splitlines(), 1):
        link_name_match = LINK_NAME_RE.match(line)
        if link_name_match:
            pending_link_name = link_name_match.group(1) or link_name_match.group(2)
            continue
        match = EXPORT_RE.match(line)
        if match:
            public_name, raw_parameters, raw_return, raw_target = match.groups()
            if public_name in seen:
                raise WasmBuildError(f"duplicate WASM export {public_name!r} on line {line_number}")
            return_type = normalize_type(raw_return or "void")
            parameters = [parse_parameter(item, public_name) for item in split_top_level(raw_parameters)]
            for parameter in parameters:
                binding, wasm_type = abi_for_type(parameter["type"], public_name, f"parameter {parameter['name']}")
                parameter["binding"] = binding
                parameter["wasm_type"] = wasm_type
            binding, wasm_type = abi_for_type(return_type, public_name, "return")
            exports.append(
                {
                    "name": public_name,
                    "target": raw_target or public_name,
                    "parameters": parameters,
                    "return": return_type,
                    "binding": binding,
                    "wasm_type": wasm_type,
                    "line": line_number,
                }
            )
            if pending_link_name is not None:
                exports[-1]["link_name"] = pending_link_name
            pending_link_name = None
            seen.add(public_name)
            continue
        if line.strip() and not line.lstrip().startswith("#"):
            pending_link_name = None
        main_match = MAIN_RE.match(line)
        if main_match:
            raw_parameters, raw_return = main_match.groups()
            if "main" not in seen:
                return_type = normalize_type(raw_return or "void")
                parameters = [parse_parameter(item, "main") for item in split_top_level(raw_parameters)]
                for parameter in parameters:
                    binding, wasm_type = abi_for_type(parameter["type"], "main", f"parameter {parameter['name']}")
                    parameter["binding"] = binding
                    parameter["wasm_type"] = wasm_type
                binding, wasm_type = abi_for_type(return_type, "main", "return")
                exports.append(
                    {
                        "name": "main",
                        "target": "main",
                        "parameters": parameters,
                        "return": return_type,
                        "binding": binding,
                        "wasm_type": wasm_type,
                        "line": line_number,
                        "implicit": True,
                    }
                )
                seen.add("main")
    if not exports:
        raise WasmBuildError("WASM source has no exported function; add `export fn name(...) -> T = target`")
    return exports


