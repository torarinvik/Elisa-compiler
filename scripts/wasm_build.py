#!/usr/bin/env python3
"""Build an Elisa WebAssembly module and its zero-glue ESM/TypeScript facade.

NO LONGER ON STAGE1'S PATH (§4.4, 2026-09-07).  ``bin/elisac-stage1`` does all of this
itself now — runtime object, ``wasm-ld`` link, manifest, facade — in
``src/driver/emit_wasm.elisa``; ``scripts/elisac_stage1.sh -emit wasm`` no longer spawns
Python at all.

This script stays because it is the only WASM packager STAGE0 has: the Go oracle's CLI has
no ``-emit wasm``, and ``test/parity/wasm_component_runtime_smoke.sh`` drives this file with
``--compiler "$ELISACORE_BIN"`` to keep stage0's component ABI covered.  It therefore also
serves as the port's oracle: ``test/parity/wasm_python_parity_smoke.sh`` builds the same
sources both ways and requires every artifact — module included — to be byte-identical.
Change one side and that smoke tells you the other has drifted.
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

# Run directly (`python3 scripts/wasm_build.py`) the interpreter puts `scripts/` on the path,
# not the repository root, so the sibling modules have to be reachable by name explicitly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.wasm_export_scan import (
    WasmBuildError,
    parse_exports,
    read_flat_source,
)
from scripts.wasm_facade import js_bindings, type_declaration

# Re-exported so `from scripts.wasm_build import ...` keeps working for the unit test and
# for anything else that grew up importing the whole surface from this one module.
__all__ = ["WasmBuildError", "parse_exports", "read_flat_source", "js_bindings",
           "type_declaration", "build", "main"]


def memory_pages_from_env(name: str, default: int) -> int:
    """Read an optional linker memory size without making manifests mandatory."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw, 10)
    except ValueError as error:
        raise WasmBuildError(f"{name} must be a positive integer page count") from error
    if value <= 0:
        raise WasmBuildError(f"{name} must be a positive integer page count")
    return value


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


def find_wasm_component_ld(explicit: str | None) -> str:
    """Locate the component-producing linker shipped with Rust's WASI target."""
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    env_path = os.environ.get("WASM_COMPONENT_LD")
    if env_path:
        candidates.append(Path(env_path))
    discovered = shutil.which("wasm-component-ld")
    if discovered:
        candidates.append(Path(discovered))

    # rustup installs the component linker in Cargo's bin directory on hosts
    # where the active rustc comes from another installation (for example
    # Homebrew). Resolve that standard location directly instead of requiring
    # every caller to add ~/.cargo/bin to PATH.
    cargo_bin = Path.home() / ".cargo" / "bin" / "wasm-component-ld"
    candidates.append(cargo_bin)
    rustup_home = os.environ.get("RUSTUP_HOME")
    if rustup_home:
        candidates.extend(
            Path(rustup_home).expanduser().glob(
                "toolchains/*/lib/rustlib/*/bin/wasm-component-ld"
            )
        )

    # rustup commonly keeps wasm-component-ld inside the active toolchain but
    # does not put that directory on PATH. Resolve that installation directly.
    rustc_candidates: list[str] = []
    rustc = shutil.which("rustc")
    if rustc:
        rustc_candidates.append(rustc)
    rustup = shutil.which("rustup")
    if rustup:
        try:
            rustup_rustc = subprocess.check_output([rustup, "which", "rustc"], text=True).strip()
            if rustup_rustc:
                rustc_candidates.append(rustup_rustc)
        except (OSError, subprocess.SubprocessError):
            pass
    for rustc_candidate in rustc_candidates:
        try:
            sysroot = Path(subprocess.check_output([rustc_candidate, "--print", "sysroot"], text=True).strip())
            host_output = subprocess.check_output([rustc_candidate, "-vV"], text=True)
            host = next((line.split(": ", 1)[1] for line in host_output.splitlines() if line.startswith("host: ")), "")
            if host:
                candidates.append(sysroot / "lib" / "rustlib" / host / "bin" / "wasm-component-ld")
        except (OSError, subprocess.SubprocessError):
            pass

    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    raise WasmBuildError(
        "WASM component linker not found; install Rust's wasm32-wasip2 target "
        "or set WASM_COMPONENT_LD"
    )


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



def build(args: argparse.Namespace) -> None:
    source = Path(args.source).resolve()
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    target = args.target or "wasm32-unknown-unknown"
    if not target.startswith("wasm32"):
        raise WasmBuildError(f"-emit wasm currently targets wasm32 (got {target!r})")
    flat_source = read_flat_source(source)
    exports = parse_exports(flat_source)
    wasm_only = args.wasm_only or bool(args.component_types)
    module_name = output.name[:-5] if output.name.endswith(".wasm") else output.name
    manifest: dict[str, Any] = {
        "version": 1,
        "module": module_name,
        "target": target,
        "memory_initial_pages": memory_pages_from_env("ELISA_WASM_INITIAL_PAGES", 16),
        "memory_max_pages": memory_pages_from_env("ELISA_WASM_MAX_PAGES", 32768),
        "memory": {"import_module": "env", "import_name": "memory", "heap_base_export": "__heap_base"},
        "exports": exports,
        "files": {"wasm": output.name, "loader": f"{module_name}.mjs", "types": f"{module_name}.d.ts", "types_esm": f"{module_name}.d.mts"},
        "generated_by": "elisa -emit wasm",
    }
    if wasm_only:
        # A package-facing WASM build must not advertise or emit a JS facade.
        manifest["files"] = {"wasm": output.name}
        manifest["generated_by"] = "elisa -emit wasm --wasm-only"
    if args.component_types:
        manifest["format"] = "wasm-component"
        manifest["component_types"] = [str(Path(item).resolve()) for item in args.component_types]
        manifest["memory"] = {"export_name": "memory", "heap_base_export": "__heap_base"}
    env = os.environ.copy()
    env["ELISA_STAGE1_WASM"] = "1"
    with tempfile.TemporaryDirectory(prefix="elisa-wasm-") as workspace:
        directory = Path(workspace)
        object_path = directory / "module.o"
        compile_command = [args.compiler, "-emit", "obj", "-target-triple", target, "-o", str(object_path)]
        compile_command.extend(args.compiler_flags)
        compile_command.append(str(source))
        run(compile_command, "WASM object compilation", env)

        component_mode = bool(args.component_types)
        runtime_object: Path | None = None
        root = Path(args.root).resolve()
        if component_mode:
            # Component canonical ABI lowering needs a freestanding allocator for
            # strings/lists. The native runtime is intentionally not linked here:
            # it imports libc-shaped `env` functions and would make the component
            # depend on a host ABI that WIT does not describe.
            runtime_source = root / "elisacore_std" / "wasm_component_runtime.elisa"
            cached_runtime = runtime_cache_path(root, Path(args.compiler), target, runtime_source)
            if os.environ.get("ELISA_WASM_NO_CACHE"):
                runtime_object = directory / "component-runtime.o"
                runtime_command = [args.compiler, "-emit", "obj", "-target-triple", target, "-O0", "-o", str(runtime_object), str(runtime_source)]
                run(runtime_command, "WASM component runtime compilation", env)
            else:
                cached_runtime.parent.mkdir(parents=True, exist_ok=True)
                if not cached_runtime.is_file():
                    runtime_candidate = directory / "component-runtime-cache-candidate.o"
                    runtime_command = [args.compiler, "-emit", "obj", "-target-triple", target, "-O0", "-o", str(runtime_candidate), str(runtime_source)]
                    run(runtime_command, "WASM component runtime compilation", env)
                    os.replace(runtime_candidate, cached_runtime)
                runtime_object = cached_runtime
        elif not re.search(r"^\s*def\s+arena_alloc\s*\(", flat_source, re.MULTILINE):
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
            "allocator": "component-cabi-realloc" if component_mode else "host-free-list",
        }

        linker = find_wasm_component_ld(args.wasm_component_ld) if component_mode else find_wasm_ld(args.wasm_ld)
        wasm_path = directory / output.name
        link_command = [linker]
        if component_mode:
            # The Elisa compiler emits a core module. wasm-component-ld embeds
            # the supplied WIT world and performs the component lift/lower pass.
            # No JavaScript or TypeScript artifacts are involved in this path.
            link_command.extend(["--wasi-adapter=none", "--validate-component=true", "--realloc-via-memory-grow"])
            for component_type in args.component_types:
                link_command.extend(["--component-type", component_type])
        link_command.extend([
            "--no-entry",
            "--export-memory=memory" if component_mode else "--import-memory",
            f"--initial-memory={manifest['memory_initial_pages'] * 65536}",
            f"--max-memory={manifest['memory_max_pages'] * 65536}",
            "--allow-undefined",
            "--gc-sections",
            "--export=__heap_base",
        ])
        # Component WIT names contain `:`, `@`, `/`, and `#`, so they cannot be
        # represented by Elisa's ordinary identifier spelling. An export may
        # carry `@link_name("...")`; the compiler preserves that spelling in
        # the object symbol and this host-side link step publishes it verbatim.
        # Ordinary builds retain the historical public-name behavior.
        link_names = (item.get("link_name", item["name"]) if component_mode else item["name"] for item in exports)
        link_command.extend(f"--export={name}" for name in link_names)
        if component_mode and runtime_object is not None:
            link_command.append("--export=cabi_realloc")
        link_command.extend(["-o", str(wasm_path), str(object_path)])
        if runtime_object is not None:
            link_command.append(str(runtime_object))
        run(link_command, "WASM link", env)
        shutil.copyfile(wasm_path, output)

    manifest_path = output.with_name(f"{module_name}.json")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    if wasm_only:
        print(f"wasm: wrote {output} and {manifest_path}", file=sys.stderr)
    else:
        loader_path = output.with_name(f"{module_name}.mjs")
        types_path = output.with_name(f"{module_name}.d.ts")
        esm_types_path = output.with_name(f"{module_name}.d.mts")
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
    parser.add_argument("--wasm-component-ld")
    parser.add_argument("--component-type", dest="component_types", action="append", default=[])
    parser.add_argument("--wasm-only", action="store_true")
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
