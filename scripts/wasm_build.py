#!/usr/bin/env python3
"""Build an Elisa WebAssembly module and its zero-glue ESM/TypeScript facade.

The compiler owns the object file and the host script owns the final wasm link.  Keeping
the linker here makes the normal ``-emit wasm`` path work on machines where ``wasm-ld``
is installed next to LLVM but no C compiler or JavaScript bundler is present.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable


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
    if normalized.endswith("&") or normalized.endswith("&&") or normalized == "cstr":
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
    has_main = False
    for line_number, line in enumerate(source.splitlines(), 1):
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
            seen.add(public_name)
            continue
        main_match = MAIN_RE.match(line)
        if main_match:
            has_main = True
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


def find_wasm_ld(explicit: str | None) -> str:
    candidates = [explicit, os.environ.get("WASM_LD")]
    llvm_config = os.environ.get("LLVM_CONFIG", "/opt/homebrew/opt/llvm/bin/llvm-config")
    if Path(llvm_config).is_file():
        try:
            bindir = subprocess.check_output([llvm_config, "--bindir"], text=True).strip()
            candidates.append(str(Path(bindir) / "wasm-ld"))
        except (OSError, subprocess.CalledProcessError):
            pass
    candidates.append(shutil.which("wasm-ld"))
    for candidate in candidates:
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
    raise WasmBuildError("WASM linker not found; install LLVM's wasm-ld or set WASM_LD")


def run(command: list[str], label: str, env: dict[str, str]) -> None:
    completed = subprocess.run(command, env=env)
    if completed.returncode:
        rendered = " ".join(subprocess.list2cmdline([item]) for item in command)
        raise WasmBuildError(f"{label} failed with exit status {completed.returncode}: {rendered}")


def ts_type(type_text: str, target: str) -> str:
    normalized = normalize_type(type_text)
    if normalized in {"i64", "u64", "int", "char"}:
        return "bigint"
    if normalized in {"bool"}:
        return "boolean"
    if normalized == "void":
        return "void"
    return "number"


def js_input(type_text: str, expression: str) -> str:
    normalized = normalize_type(type_text)
    if normalized in {"i64", "u64", "int", "char"}:
        return f"BigInt({expression})"
    if normalized == "bool":
        return f"{expression} ? 1 : 0"
    return expression


def js_output(type_text: str, expression: str) -> str:
    normalized = normalize_type(type_text)
    if normalized == "bool":
        return f"!!({expression})"
    if normalized == "i8":
        return f"(({expression} << 24) >> 24)"
    if normalized == "i16":
        return f"(({expression} << 16) >> 16)"
    if normalized in {"isize"}:
        return f"(({expression}) | 0)"
    if normalized == "u8":
        return f"(({expression}) & 0xff)"
    if normalized == "u16":
        return f"(({expression}) & 0xffff)"
    if normalized in {"u32", "usize", "uintptr"}:
        return f"(({expression}) >>> 0)"
    return expression


def js_bindings(manifest: dict[str, Any], module_name: str) -> str:
    functions: list[str] = []
    for item in manifest["exports"]:
        args = ", ".join(parameter["name"] for parameter in item["parameters"])
        raw_args = ", ".join(js_input(parameter["type"], parameter["name"]) for parameter in item["parameters"])
        call = f"instance.exports[{json.dumps(item['name'])}]({raw_args})"
        result = js_output(item["return"], call)
        functions.append(f"    {item['name']}({args}) {{ return {result}; }}")
    function_block = ",\n".join(functions)
    return f'''// Generated by `elisac -emit wasm`; edit the Elisa source, not this file.
const WASM_URL = new URL("./{module_name}.wasm", import.meta.url);
const PAGE_SIZE = 65536;
const DEFAULT_INITIAL_PAGES = {manifest["memory_initial_pages"]};
const DEFAULT_MAXIMUM_PAGES = {manifest["memory_max_pages"]};

function align(value, boundary = 16) {{ return (value + boundary - 1) & ~(boundary - 1); }}

/** Create the small host ABI used by Elisa's portable runtime. User imports win. */
export function createElisaImports(options = {{}}) {{
  const memory = options.memory ?? new WebAssembly.Memory({{ initial: options.initialPages ?? DEFAULT_INITIAL_PAGES, maximum: options.maximumPages ?? DEFAULT_MAXIMUM_PAGES }});
  let next = options.heapBase ?? 1024;
  const bytes = () => new Uint8Array(memory.buffer);
  const ensure = (size) => {{
    const needed = next + Math.max(0, Number(size));
    while (needed > memory.buffer.byteLength) memory.grow(Math.max(1, Math.ceil((needed - memory.buffer.byteLength) / PAGE_SIZE)));
  }};
  const readCString = (pointer) => {{
    const data = bytes(); let end = pointer >>> 0;
    while (end < data.length && data[end] !== 0) end++;
    return new TextDecoder().decode(data.subarray(pointer >>> 0, end));
  }};
  const env = {{
    memory,
    stderr: new WebAssembly.Global({{ value: "i32", mutable: false }}, 0),
    malloc(size) {{ const pointer = align(next); next = pointer + Number(size); ensure(0); return pointer; }},
    free() {{}},
    realloc(pointer, oldSize, newSize) {{ const replacement = env.malloc(newSize); new Uint8Array(memory.buffer, replacement, Number(newSize)).set(new Uint8Array(memory.buffer, pointer >>> 0, Math.min(Number(oldSize), Number(newSize)))); return replacement; }},
    memcpy(destination, source, size) {{ new Uint8Array(memory.buffer, destination >>> 0, Number(size)).set(new Uint8Array(memory.buffer, source >>> 0, Number(size))); return destination; }},
    memmove(destination, source, size) {{ const copy = new Uint8Array(memory.buffer, source >>> 0, Number(size)).slice(); new Uint8Array(memory.buffer, destination >>> 0, Number(size)).set(copy); return destination; }},
    memset(destination, value, size) {{ bytes().fill(Number(value) & 255, destination >>> 0, (destination >>> 0) + Number(size)); return destination; }},
    memcmp(left, right, size) {{ const data = bytes(); for (let i = 0; i < Number(size); i++) {{ const difference = data[(left >>> 0) + i] - data[(right >>> 0) + i]; if (difference) return difference; }} return 0; }},
    strlen(pointer) {{ let length = 0; const data = bytes(); while (data[(pointer >>> 0) + length] !== 0) length++; return length; }},
    strcmp(left, right) {{ const a = readCString(left), b = readCString(right); return a < b ? -1 : (a > b ? 1 : 0); }},
    puts(pointer) {{ if (options.onPrint) options.onPrint(readCString(pointer)); return 0; }},
    fprintf() {{ return 0; }},
    snprintf() {{ return -1; }},
    wasm_memory_size() {{ return memory.buffer.byteLength / PAGE_SIZE; }},
    wasm_memory_grow(index, pages) {{ try {{ return memory.grow(Number(pages)); }} catch {{ return -1; }} }},
    exit(code) {{ throw new Error(`Elisa WASM exited with code ${{code}}`); }},
  }};
  return {{ ...options, memory, env: {{ ...env, ...(options.env ?? {{}}) }} }};
}}

async function sourceBytes(source) {{
  if (source instanceof Response) return new Uint8Array(await source.arrayBuffer());
  if (source instanceof ArrayBuffer) return new Uint8Array(source);
  if (ArrayBuffer.isView(source)) return new Uint8Array(source.buffer, source.byteOffset, source.byteLength);
  const url = source instanceof URL ? source : (source ? String(source) : WASM_URL);
  if (url instanceof URL && url.protocol === "file:") {{
    const {{ readFile }} = await import("node:fs/promises");
    return new Uint8Array(await readFile(url));
  }}
  if (typeof url === "string" && !/^(?:https?:|file:)/.test(url)) {{
    try {{ const {{ readFile }} = await import("node:fs/promises"); return new Uint8Array(await readFile(url)); }} catch {{ /* browser URL fallback */ }}
  }}
  return new Uint8Array(await (await fetch(url)).arrayBuffer());
}}

export async function loadWasm(source, options = {{}}) {{
  const imports = createElisaImports(options);
  const result = await WebAssembly.instantiate(await sourceBytes(source), imports);
  const instance = result.instance;
  return Object.freeze({{
{function_block},
    memory: imports.memory,
    raw: instance.exports,
  }});
}}

export default loadWasm;
'''


def type_declaration(manifest: dict[str, Any], module_name: str) -> str:
    interfaces: list[str] = []
    for item in manifest["exports"]:
        params = ", ".join(f"{p['name']}: {ts_type(p['type'], manifest['target'])}" for p in item["parameters"])
        interfaces.append(f"  {item['name']}({params}): {ts_type(item['return'], manifest['target'])};")
    return f'''// Generated by `elisac -emit wasm`; edit the Elisa source, not this file.
export type WasmSource = string | URL | ArrayBuffer | ArrayBufferView | Response;
export interface ElisaWasmLoadOptions {{
  memory?: WebAssembly.Memory;
  initialPages?: number;
  maximumPages?: number;
  heapBase?: number;
  env?: Record<string, unknown>;
  onPrint?: (text: string) => void;
}}
export interface {module_name}Exports {{
{chr(10).join(interfaces)}
  memory: WebAssembly.Memory;
  raw: Record<string, unknown>;
}}
export function createElisaImports(options?: ElisaWasmLoadOptions): WebAssembly.Imports;
export function loadWasm(source?: WasmSource, options?: ElisaWasmLoadOptions): Promise<{module_name}Exports>;
export default loadWasm;
'''


def build(args: argparse.Namespace) -> None:
    source = Path(args.source).resolve()
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    target = args.target or "wasm32-unknown-unknown"
    if not target.startswith("wasm32"):
        raise WasmBuildError(f"-emit wasm currently targets wasm32 (got {target!r})")
    flat_source = read_flat_source(source)
    exports = parse_exports(flat_source)
    module_name = output.name[:-5] if output.name.endswith(".wasm") else output.name
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", module_name):
        raise WasmBuildError(f"WASM output stem {module_name!r} is not a valid JavaScript/TypeScript identifier")
    manifest: dict[str, Any] = {
        "version": 1,
        "module": module_name,
        "target": target,
        "memory_initial_pages": 16,
        "memory_max_pages": 32768,
        "exports": exports,
        "files": {"wasm": output.name, "loader": f"{module_name}.mjs", "types": f"{module_name}.d.ts"},
        "generated_by": "elisa -emit wasm",
    }
    env = os.environ.copy()
    env["ELISA_STAGE1_WASM"] = "1"
    with tempfile.TemporaryDirectory(prefix="elisa-wasm-") as workspace:
        directory = Path(workspace)
        object_path = directory / "module.o"
        compile_command = [args.compiler, "-emit", "obj", "-target-triple", target, "-o", str(object_path)]
        compile_command.extend(args.compiler_flags)
        compile_command.append(str(source))
        run(compile_command, "WASM object compilation", env)

        runtime_object: Path | None = None
        if not re.search(r"^\s*def\s+arena_alloc\s*\(", flat_source, re.MULTILINE):
            runtime_object = directory / "runtime.o"
            runtime_source = Path(args.root).resolve() / "elisacore_std" / "native_runtime_support.elisa"
            runtime_command = [args.compiler, "-emit", "obj", "-target-triple", target, "-O0", "-o", str(runtime_object), str(runtime_source)]
            run(runtime_command, "WASM runtime compilation", env)

        linker = find_wasm_ld(args.wasm_ld)
        wasm_path = directory / output.name
        link_command = [
            linker,
            "--no-entry",
            "--import-memory",
            f"--initial-memory={manifest['memory_initial_pages'] * 65536}",
            f"--max-memory={manifest['memory_max_pages'] * 65536}",
            "--allow-undefined",
            "--gc-sections",
        ]
        link_command.extend(f"--export={item['name']}" for item in exports)
        link_command.extend(["-o", str(wasm_path), str(object_path)])
        if runtime_object is not None:
            link_command.append(str(runtime_object))
        run(link_command, "WASM link", env)
        shutil.copyfile(wasm_path, output)

    manifest_path = output.with_name(f"{module_name}.json")
    loader_path = output.with_name(f"{module_name}.mjs")
    types_path = output.with_name(f"{module_name}.d.ts")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    loader_path.write_text(js_bindings(manifest, module_name), encoding="utf-8")
    types_path.write_text(type_declaration(manifest, module_name), encoding="utf-8")
    print(f"wasm: wrote {output}, {loader_path}, {types_path}, and {manifest_path}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--compiler", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--target")
    parser.add_argument("--wasm-ld")
    parser.add_argument("--compiler-flag", dest="compiler_flags", action="append", default=[])
    args = parser.parse_args()
    try:
        build(args)
    except WasmBuildError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
