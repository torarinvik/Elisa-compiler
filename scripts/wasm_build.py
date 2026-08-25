#!/usr/bin/env python3
"""Build an Elisa WebAssembly module and its zero-glue ESM/TypeScript facade.

The compiler owns the object file and the host script owns the final wasm link.  Keeping
the linker here makes the normal ``-emit wasm`` path work on machines where ``wasm-ld``
is installed next to LLVM but no C compiler or JavaScript bundler is present.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
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


def runtime_cache_path(root: Path, compiler: Path, target: str, runtime_source: Path) -> Path:
    digest = hashlib.sha256()
    digest.update(target.encode("utf-8"))
    digest.update(read_flat_source(runtime_source).encode("utf-8"))
    for candidate in (compiler, root / "bin" / "elisac-stage1"):
        try:
            stat = candidate.resolve().stat()
        except OSError:
            continue
        digest.update(str(candidate.resolve()).encode("utf-8"))
        digest.update(f"{stat.st_size}:{stat.st_mtime_ns}".encode("ascii"))
    return root / "build" / "wasm-cache" / f"runtime-{digest.hexdigest()[:20]}.o"


def ts_type(type_text: str, target: str, *, parameter: bool = False) -> str:
    normalized = normalize_type(type_text)
    if normalized == "cstr":
        return "string | number" if parameter else "string"
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
    if normalized == "cstr":
        return f"memoryTools.readString({expression})"
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
        raw_arguments: list[str] = []
        setup: list[str] = []
        cleanup: list[str] = []
        for parameter in item["parameters"]:
            parameter_name = parameter["name"]
            if parameter["binding"] == "string":
                local_name = f"__elisa_{parameter_name}"
                setup.append(
                    f"      const {local_name} = typeof {parameter_name} === \"string\" "
                    f"? memoryTools.writeString({parameter_name}) : ({parameter_name} >>> 0);"
                )
                cleanup.append(f"        if (typeof {parameter_name} === \"string\") memoryTools.free({local_name});")
                raw_arguments.append(local_name)
            else:
                raw_arguments.append(js_input(parameter["type"], parameter_name))
        raw_args = ", ".join(raw_arguments)
        call = f"instance.exports[{json.dumps(item['name'])}]({raw_args})"
        result = js_output(item["return"], call)
        if setup:
            functions.append(
                f"    {item['name']}({args}) {{\n"
                + "\n".join(setup)
                + f"\n      try {{ return {result}; }}\n"
                + "      finally {\n"
                + "\n".join(cleanup)
                + "\n      }\n"
                + "    }"
            )
        else:
            functions.append(f"    {item['name']}({args}) {{ return {result}; }}")
    function_block = ",\n".join(functions)
    wasm_relative_url = json.dumps(f"./{manifest['files']['wasm']}")
    return f'''// Generated by `elisac -emit wasm`; edit the Elisa source, not this file.
const WASM_URL = new URL({wasm_relative_url}, import.meta.url);
const PAGE_SIZE = 65536;
const DEFAULT_INITIAL_PAGES = {manifest["memory_initial_pages"]};
const DEFAULT_MAXIMUM_PAGES = {manifest["memory_max_pages"]};
const RUNTIME_STATE = Symbol("ElisaWasmRuntimeState");
const UTF8_ENCODER = new TextEncoder();
const UTF8_DECODER = new TextDecoder();

function align(value, boundary = 16) {{ return (value + boundary - 1) & ~(boundary - 1); }}

/** Create the small host ABI used by Elisa's portable runtime. User imports win. */
export function createElisaImports(options = {{}}) {{
  const customImports = options.imports ?? {{}};
  const customEnv = customImports.env ?? {{}};
  const memory = options.memory ?? customEnv.memory ?? new WebAssembly.Memory({{ initial: options.initialPages ?? DEFAULT_INITIAL_PAGES, maximum: options.maximumPages ?? DEFAULT_MAXIMUM_PAGES }});
  if (!(memory instanceof WebAssembly.Memory)) throw new TypeError("Elisa WASM requires options.memory/imports.env.memory to be a WebAssembly.Memory");
  let next = options.heapBase === undefined ? 0 : align(Number(options.heapBase));
  let heapReady = options.heapBase !== undefined;
  const allocations = new Map();
  const freeBlocks = [];
  const bytes = () => new Uint8Array(memory.buffer);
  const ensureEnd = (end) => {{
    while (end > memory.buffer.byteLength) memory.grow(Math.max(1, Math.ceil((end - memory.buffer.byteLength) / PAGE_SIZE)));
  }};
  const readCString = (pointer) => {{
    if (!pointer) return "";
    const data = bytes(); let end = pointer >>> 0;
    while (end < data.length && data[end] !== 0) end++;
    return UTF8_DECODER.decode(data.subarray(pointer >>> 0, end));
  }};
  const coalesceFreeBlocks = () => {{
    freeBlocks.sort((left, right) => left.pointer - right.pointer);
    for (let index = 1; index < freeBlocks.length;) {{
      const previous = freeBlocks[index - 1], current = freeBlocks[index];
      if (previous.pointer + previous.size === current.pointer) {{
        previous.size += current.size;
        freeBlocks.splice(index, 1);
      }} else index++;
    }}
  }};
  const setHeapBase = (value) => {{
    const base = align(Number(value));
    next = Math.max(next, base);
    heapReady = true;
  }};
  const malloc = (requestedSize) => {{
    if (!heapReady) throw new Error("Elisa WASM allocator used before __heap_base was initialized");
    const numericSize = Number(requestedSize);
    if (!Number.isSafeInteger(numericSize) || numericSize < 0) throw new RangeError(`Invalid Elisa WASM allocation size: ${{requestedSize}}`);
    const size = align(Math.max(1, numericSize));
    const reusable = freeBlocks.findIndex((block) => block.size >= size);
    if (reusable >= 0) {{
      const block = freeBlocks[reusable];
      const pointer = block.pointer;
      if (block.size === size) freeBlocks.splice(reusable, 1);
      else {{ block.pointer += size; block.size -= size; }}
      allocations.set(pointer, size);
      return pointer;
    }}
    const pointer = align(next);
    next = pointer + size;
    ensureEnd(next);
    allocations.set(pointer, size);
    return pointer;
  }};
  const free = (rawPointer) => {{
    const pointer = Number(rawPointer) >>> 0;
    const size = allocations.get(pointer);
    if (size === undefined) return;
    allocations.delete(pointer);
    freeBlocks.push({{ pointer, size }});
    coalesceFreeBlocks();
  }};
  const writeBytes = (value, nulTerminate = false) => {{
    const source = value instanceof Uint8Array
      ? Uint8Array.from(value)
      : Uint8Array.from(new Uint8Array(value.buffer ?? value, value.byteOffset ?? 0, value.byteLength ?? value.length));
    const pointer = malloc(source.byteLength + (nulTerminate ? 1 : 0));
    bytes().set(source, pointer);
    if (nulTerminate) bytes()[pointer + source.byteLength] = 0;
    return Object.freeze({{ pointer, length: source.byteLength }});
  }};
  const readBytes = (pointer, length) => bytes().slice(pointer >>> 0, (pointer >>> 0) + Number(length));
  const writeString = (text) => writeBytes(UTF8_ENCODER.encode(String(text)), true).pointer;
  const onWrite = options.onWrite ?? ((text, descriptor) => (descriptor === 2 ? console.error(text) : console.log(text)));
  const env = {{
    memory,
    stderr: new WebAssembly.Global({{ value: "i32", mutable: false }}, 0),
    malloc,
    free,
    realloc(pointer, oldSize, newSize) {{ if (!pointer) return malloc(newSize); if (Number(newSize) === 0) {{ free(pointer); return 0; }} const available = allocations.get(pointer >>> 0) ?? Number(oldSize); const replacement = malloc(newSize); new Uint8Array(memory.buffer, replacement, Number(newSize)).set(new Uint8Array(memory.buffer, pointer >>> 0, Math.min(available, Number(newSize)))); free(pointer); return replacement; }},
    memcpy(destination, source, size) {{ new Uint8Array(memory.buffer, destination >>> 0, Number(size)).set(new Uint8Array(memory.buffer, source >>> 0, Number(size))); return destination; }},
    memmove(destination, source, size) {{ const copy = new Uint8Array(memory.buffer, source >>> 0, Number(size)).slice(); new Uint8Array(memory.buffer, destination >>> 0, Number(size)).set(copy); return destination; }},
    memset(destination, value, size) {{ bytes().fill(Number(value) & 255, destination >>> 0, (destination >>> 0) + Number(size)); return destination; }},
    memcmp(left, right, size) {{ const data = bytes(); for (let i = 0; i < Number(size); i++) {{ const difference = data[(left >>> 0) + i] - data[(right >>> 0) + i]; if (difference) return difference; }} return 0; }},
    strlen(pointer) {{ let length = 0; const data = bytes(); while (data[(pointer >>> 0) + length] !== 0) length++; return length; }},
    strcmp(left, right) {{ const a = readCString(left), b = readCString(right); return a < b ? -1 : (a > b ? 1 : 0); }},
    puts(pointer) {{ (options.onPrint ?? ((text) => console.log(text)))(readCString(pointer)); return 0; }},
    write(descriptor, pointer, size) {{ onWrite(UTF8_DECODER.decode(readBytes(pointer, size)), Number(descriptor)); return Number(size); }},
    read() {{ return -1; }},
    printf(format) {{ const text = readCString(format); (options.onPrint ?? ((line) => console.log(line)))(text); return UTF8_ENCODER.encode(text).byteLength; }},
    fprintf() {{ return 0; }},
    snprintf() {{ return -1; }},
    backtrace() {{ return 0; }},
    backtrace_symbols_fd() {{}},
    wasm_memory_size() {{ return memory.buffer.byteLength / PAGE_SIZE; }},
    wasm_memory_grow(index, pages) {{ try {{ return memory.grow(Number(pages)); }} catch {{ return -1; }} }},
    abort() {{ throw new Error("Elisa WASM aborted"); }},
    exit(code) {{ throw new Error(`Elisa WASM exited with code ${{code}}`); }},
  }};
  const imports = {{ ...customImports, memory, env: {{ ...env, ...customEnv, ...(options.env ?? {{}}), memory }} }};
  Object.defineProperty(imports, RUNTIME_STATE, {{ value: {{ setHeapBase, malloc, free, writeBytes, readBytes, writeString, readString: readCString }} }});
  return imports;
}}

async function sourceBytes(source) {{
  if (typeof Response !== "undefined" && source instanceof Response) return new Uint8Array(await source.arrayBuffer());
  if (source instanceof ArrayBuffer) return new Uint8Array(source);
  if (ArrayBuffer.isView(source)) return new Uint8Array(source.buffer, source.byteOffset, source.byteLength);
  const url = source instanceof URL ? source : (source ? String(source) : WASM_URL);
  if (url instanceof URL && url.protocol === "file:") {{
    const {{ readFile }} = await import("node:fs/promises");
    return new Uint8Array(await readFile(url));
  }}
  if (typeof url === "string" && url.startsWith("file:")) {{
    const {{ readFile }} = await import("node:fs/promises");
    return new Uint8Array(await readFile(new URL(url)));
  }}
  if (typeof url === "string" && !/^(?:https?:|file:)/.test(url)) {{
    try {{ const {{ readFile }} = await import("node:fs/promises"); return new Uint8Array(await readFile(url)); }} catch {{ /* browser URL fallback */ }}
  }}
  const response = await fetch(url);
  if (!response.ok) throw new Error(`Unable to load Elisa WASM (${{response.status}} ${{response.statusText}}): ${{response.url || url}}`);
  return new Uint8Array(await response.arrayBuffer());
}}

export async function loadWasm(source, options = {{}}) {{
  const imports = createElisaImports(options);
  const module = await WebAssembly.compile(await sourceBytes(source));
  const missing = WebAssembly.Module.imports(module).filter((required) => !(required.name in (imports[required.module] ?? {{}})));
  if (missing.length) {{
    const names = missing.map((required) => `${{required.module}}.${{required.name}} (${{required.kind}})`).join(", ");
    throw new Error(`Missing Elisa WASM imports: ${{names}}. Provide them through loadWasm(source, {{ imports: {{ module: {{ name: value }} }} }}).`);
  }}
  const instance = await WebAssembly.instantiate(module, imports);
  const runtime = imports[RUNTIME_STATE];
  const heapGlobal = instance.exports.__heap_base;
  const heapBase = heapGlobal instanceof WebAssembly.Global ? heapGlobal.value : heapGlobal;
  if (heapBase === undefined) throw new Error("Elisa WASM module does not export __heap_base");
  runtime.setHeapBase(heapBase);
  const memoryTools = Object.freeze({{
    alloc: runtime.malloc,
    free: runtime.free,
    writeBytes: runtime.writeBytes,
    readBytes: runtime.readBytes,
    writeString: runtime.writeString,
    readString: runtime.readString,
  }});
  return Object.freeze({{
{function_block},
    memory: imports.memory,
    ...memoryTools,
    raw: instance.exports,
  }});
}}

export default loadWasm;
'''


def type_declaration(manifest: dict[str, Any], module_name: str) -> str:
    interface_stem = re.sub(r"[^A-Za-z0-9_$]", "_", module_name)
    if not interface_stem or interface_stem[0].isdigit():
        interface_stem = f"_{interface_stem}"
    interface_name = f"{interface_stem}Exports"
    interfaces: list[str] = []
    for item in manifest["exports"]:
        params = ", ".join(f"{p['name']}: {ts_type(p['type'], manifest['target'], parameter=True)}" for p in item["parameters"])
        interfaces.append(f"  {item['name']}({params}): {ts_type(item['return'], manifest['target'])};")
    return f'''// Generated by `elisac -emit wasm`; edit the Elisa source, not this file.
export type WasmSource = string | URL | ArrayBuffer | ArrayBufferView | Response;
export interface ElisaWasmLoadOptions {{
  memory?: WebAssembly.Memory;
  initialPages?: number;
  maximumPages?: number;
  heapBase?: number;
  imports?: WebAssembly.Imports;
  env?: Record<string, unknown>;
  onPrint?: (text: string) => void;
  onWrite?: (text: string, descriptor: number) => void;
}}
export interface ElisaWasmBuffer {{ readonly pointer: number; readonly length: number; }}
export interface {interface_name} {{
{chr(10).join(interfaces)}
  memory: WebAssembly.Memory;
  alloc(size: number): number;
  free(pointer: number): void;
  writeBytes(data: ArrayBuffer | ArrayBufferView): ElisaWasmBuffer;
  readBytes(pointer: number, length: number): Uint8Array;
  writeString(text: string): number;
  readString(pointer: number): string;
  raw: Record<string, unknown>;
}}
export function createElisaImports(options?: ElisaWasmLoadOptions): WebAssembly.Imports;
export function loadWasm(source?: WasmSource, options?: ElisaWasmLoadOptions): Promise<{interface_name}>;
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
    manifest: dict[str, Any] = {
        "version": 1,
        "module": module_name,
        "target": target,
        "memory_initial_pages": 16,
        "memory_max_pages": 32768,
        "memory": {"import_module": "env", "import_name": "memory", "heap_base_export": "__heap_base"},
        "exports": exports,
        "files": {"wasm": output.name, "loader": f"{module_name}.mjs", "types": f"{module_name}.d.ts", "types_esm": f"{module_name}.d.mts"},
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
            root = Path(args.root).resolve()
            runtime_source = root / "elisacore_std" / "native_runtime_support.elisa"
            cached_runtime = runtime_cache_path(root, Path(args.compiler), target, runtime_source)
            if os.environ.get("ELISA_WASM_NO_CACHE"):
                runtime_object = directory / "runtime.o"
                runtime_command = [args.compiler, "-emit", "obj", "-target-triple", target, "-O0", "-o", str(runtime_object), str(runtime_source)]
                run(runtime_command, "WASM runtime compilation", env)
            else:
                cached_runtime.parent.mkdir(parents=True, exist_ok=True)
                if not cached_runtime.is_file():
                    runtime_candidate = directory / "runtime-cache-candidate.o"
                    runtime_command = [args.compiler, "-emit", "obj", "-target-triple", target, "-O0", "-o", str(runtime_candidate), str(runtime_source)]
                    run(runtime_command, "WASM runtime compilation", env)
                    os.replace(runtime_candidate, cached_runtime)
                runtime_object = cached_runtime
        manifest["runtime"] = {
            "mode": "inline" if runtime_object is None else "linked",
            "allocator": "host-free-list",
        }

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
            "--export=__heap_base",
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
    esm_types_path = output.with_name(f"{module_name}.d.mts")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    loader_path.write_text(js_bindings(manifest, module_name), encoding="utf-8")
    declarations = type_declaration(manifest, module_name)
    types_path.write_text(declarations, encoding="utf-8")
    esm_types_path.write_text(declarations, encoding="utf-8")
    print(f"wasm: wrote {output}, {loader_path}, {types_path}, {esm_types_path}, and {manifest_path}", file=sys.stderr)


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
