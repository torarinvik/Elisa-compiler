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

An explicit `--export-scan-launcher` plus `--export-scan-script` pair selects
the Elisascript scanner for source flattening, export parsing, and runtime
cache hashing. Normal packager runs require that pair (or its environment
defaults) and never silently fall back to Python. The pinned Python scanner is
available only through `--python-reference-scanner` for parity-oracle runs and
compatibility re-exports. Selecting the Elisascript path does not load the
Python scanner module.
"""


from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

# Run directly (`python3 scripts/wasm_build.py`) the interpreter puts `scripts/` on the path,
# not the repository root, so the sibling modules have to be reachable by name explicitly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.wasm_export_scan_client import (
    WasmExportScanClientError,
    run_export_scan,
    run_flatten_source,
)
from scripts import elisa_platform, wasm_runtime_toolchain, wasm_runtime_cache
from scripts.wasm_facade import js_bindings, type_declaration

# Re-exported so `from scripts.wasm_build import ...` keeps working for the unit test and
# for anything else that grew up importing the whole surface from this one module.
__all__ = ["WasmBuildError", "parse_exports", "read_flat_source", "js_bindings",
           "type_declaration", "build", "main"]


class WasmBuildError(RuntimeError):
    """A package build or scanner integration failed."""


RUNTIME_CACHE_FORMAT = 2
RUNTIME_CACHE_MAX_BYTES = 256 << 20
RUNTIME_CACHE_OBSERVERS = (
    "ELISA_SMT_RLIMIT_LOG", "ELISA_SMT_TRACE", "ELISA_SEMANTIC_INTERNAL_PARITY_OUT",
    "ELISA_DUMP_DEATHTIME", "ELISA_DUMP_REGION_STACKS", "ELISA_REGION_DEBUG",
    "ELISA_ELEMSTATE_TRACE", "ELISA_STORE_PAYLOAD_TRACE", "ELISA_STORESCAN_TRACE",
    "ELISA_STORE_TRACE", "ELISA_RECLAIM_TRACE", "ELISA_PARALLEL_GRAPH_REPORT",
    "ELISA_PARALLEL_SHARING_REPORT", "ELISA_PARALLEL_DECLINE_LOG", "ELISA_POST_TIMING",
    "ELISA_DECL_TIMING", "ELISA_REGION_FIXPOINT_SHADOW", "ELISA_TRACKED_SHARE_CHECK",
    "ELISA_SMT_PREAMBLE_SHADOW", "ELISA_BACKEND_PARITY_OUT", "ELISA_PARSER_PARITY_OUT",
    "ELISA_SEMANTIC_PARITY_OUT", "ELISACORE_CPUPROFILE", "ELISACORE_MEMPROFILE",
    "ELISACORE_GOROUTINEPROFILE", "ELISACORE_BLOCKPROFILE", "ELISACORE_BUILD_TIMING",
    "ELISACORE_TEST_TIMING", "ELISACORE_TEST_PHASE_DEBUG", "ELISACORE_TEST_CACHE_DEBUG",
    "ELISACORE_CACHE_DEBUG", "ELISACORE_LLVM_PASS_DEBUG", "ELISACORE_ANALYSIS_CACHE_DEBUG",
    "ELISACORE_DUMP_MODULE_ON_VERIFY_FAILURE", "ELISACORE_EMIT_LL",
    "ELISACORE_KEEP_TEST_TEMP", "ELISACORE_LEXER_CAPACITY_REPORT",
    "ELISACORE_RETAINED_DEBUG_SPANS", "ELISACORE_RETAINED_FAST_DEBUG",
    "ELISACORE_TRUSTED_RUNTIME_SOURCE", "LD_PRELOAD", "DYLD_INSERT_LIBRARIES", "LLVM_PROFILE_FILE",
)
RUNTIME_CACHE_TOOL_ENV = (
    "CPATH", "C_INCLUDE_PATH", "CPLUS_INCLUDE_PATH", "OBJC_INCLUDE_PATH", "LIBRARY_PATH",
    "SDKROOT", "DEVELOPER_DIR", "TOOLCHAINS", "MACOSX_DEPLOYMENT_TARGET",
    "IPHONEOS_DEPLOYMENT_TARGET", "TVOS_DEPLOYMENT_TARGET", "WATCHOS_DEPLOYMENT_TARGET",
    "XROS_DEPLOYMENT_TARGET", "CCC_OVERRIDE_OPTIONS", "COMPILER_PATH", "GCC_EXEC_PREFIX",
    "LDFLAGS", "CFLAGS", "CPPFLAGS", "LD_PRELOAD", "DYLD_INSERT_LIBRARIES",
)


# Pass this module's operation table so cache helpers use the same selected
# compiler, scanner, and testable host probes as the build driver.
def _stat_identity(*args, **kwargs):
    return wasm_runtime_toolchain._stat_identity(globals(), *args, **kwargs)


def _owned_private_path(*args, **kwargs):
    return wasm_runtime_toolchain._owned_private_path(globals(), *args, **kwargs)


def _trusted_cache_ancestor(*args, **kwargs):
    return wasm_runtime_toolchain._trusted_cache_ancestor(globals(), *args, **kwargs)


def _hash_regular_file(*args, **kwargs):
    return wasm_runtime_toolchain._hash_regular_file(globals(), *args, **kwargs)


def _resolve_executable(*args, **kwargs):
    return wasm_runtime_toolchain._resolve_executable(globals(), *args, **kwargs)


def _resolve_llc_executable(*args, **kwargs):
    return wasm_runtime_toolchain._resolve_llc_executable(globals(), *args, **kwargs)


def _resolve_native_object_merger(*args, **kwargs):
    return wasm_runtime_toolchain._resolve_native_object_merger(globals(), *args, **kwargs)


def _llvm_shared_libraries(*args, **kwargs):
    return wasm_runtime_toolchain._llvm_shared_libraries(globals(), *args, **kwargs)


def _runtime_cache_directory_ready(*args, **kwargs):
    return wasm_runtime_cache._runtime_cache_directory_ready(globals(), *args, **kwargs)


def _runtime_cache_entry_valid(*args, **kwargs):
    return wasm_runtime_cache._runtime_cache_entry_valid(globals(), *args, **kwargs)


def _runtime_cache_observer_requested(*args, **kwargs):
    return wasm_runtime_cache._runtime_cache_observer_requested(globals(), *args, **kwargs)


def _publish_runtime_cache(*args, **kwargs):
    return wasm_runtime_cache._publish_runtime_cache(globals(), *args, **kwargs)


def _compile_runtime_object(*args, **kwargs):
    return wasm_runtime_cache._compile_runtime_object(globals(), *args, **kwargs)


def _runtime_object_from_cache(*args, **kwargs):
    return wasm_runtime_cache._runtime_object_from_cache(globals(), *args, **kwargs)


def _python_export_scanner() -> Any:
    """Load the legacy scanner only for its explicit oracle/fallback path."""
    try:
        return importlib.import_module("scripts.wasm_export_scan")
    except ImportError as error:
        raise WasmBuildError("Python WASM export scanner is unavailable") from error


def parse_exports(source: str, *, component: bool = False) -> list[dict[str, Any]]:
    scanner = _python_export_scanner()
    try:
        return scanner.parse_exports(source, component=component)
    except scanner.WasmBuildError as error:
        raise WasmBuildError(str(error)) from error


def read_flat_source(
    path: Path,
    seen: set[Path] | None = None,
    stack: list[Path] | None = None,
) -> str:
    scanner = _python_export_scanner()
    try:
        return scanner.read_flat_source(path, seen, stack)
    except scanner.WasmBuildError as error:
        raise WasmBuildError(str(error)) from error


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


def write_text_if_changed(path: Path, contents: str) -> bool:
    """Write UTF-8 text only when its exact bytes differ from the existing file.

    Reading at most one byte beyond the generated value keeps comparison bounded
    even when an existing output was replaced by an unexpectedly large file.
    Byte writes also keep generated sidecars on deterministic LF line endings on
    every host platform.
    """
    encoded = contents.encode("utf-8")
    try:
        with path.open("rb") as current:
            existing = current.read(len(encoded) + 1)
    except FileNotFoundError:
        existing = None
    if existing == encoded:
        return False
    with path.open("wb") as output:
        output.write(encoded)
    return True


def find_wasm_ld(explicit: str | None) -> str:
    candidates = [explicit, os.environ.get("WASM_LD")]
    llvm_config = os.environ.get("LLVM_CONFIG") or elisa_platform.LLVM_CONFIG
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


def runtime_cache_path(*args, **kwargs):
    return wasm_runtime_cache.runtime_cache_path(globals(), *args, **kwargs)


def _runtime_cache_key_is_current(*args, **kwargs):
    return wasm_runtime_cache._runtime_cache_key_is_current(globals(), *args, **kwargs)


def load_export_scan(source: Path, args: argparse.Namespace) -> tuple[str, list[dict[str, Any]]]:
    launcher = getattr(args, "export_scan_launcher", None)
    scanner_script = getattr(args, "export_scan_script", None)
    if getattr(args, "python_reference_scanner", False):
        flat_source = read_flat_source(source)
        return flat_source, parse_exports(flat_source, component=bool(getattr(args, "component_types", [])))
    if (launcher is None) != (scanner_script is None):
        raise WasmBuildError(
            "--export-scan-launcher and --export-scan-script must be supplied together"
        )
    if launcher is None and scanner_script is None:
        raise WasmBuildError(
            "Elisascript export scanner is required; configure both scanner paths "
            "or select --python-reference-scanner for a parity oracle run"
        )
    component = bool(getattr(args, "component_types", []))
    try:
        return run_export_scan(launcher, scanner_script, source, component=component)
    except WasmExportScanClientError as error:
        raise WasmBuildError(str(error)) from error



def build(args: argparse.Namespace) -> None:
    source = Path(args.source).resolve()
    output = Path(args.output).resolve()
    target = args.target or "wasm32-unknown-unknown"
    if not target.startswith("wasm32"):
        raise WasmBuildError(f"-emit wasm currently targets wasm32 (got {target!r})")
    flat_source, exports = load_export_scan(source, args)
    output.parent.mkdir(parents=True, exist_ok=True)
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
            if os.environ.get("ELISA_WASM_NO_CACHE"):
                runtime_object = directory / "component-runtime.o"
                _compile_runtime_object(
                    args.compiler, target, runtime_source, runtime_object, env,
                    "WASM component runtime compilation",
                )
            else:
                cached_runtime = runtime_cache_path(
                    root,
                    Path(args.compiler),
                    target,
                    runtime_source,
                    export_scan_launcher=getattr(args, "export_scan_launcher", None),
                    export_scan_script=getattr(args, "export_scan_script", None),
                    python_reference_scanner=getattr(args, "python_reference_scanner", False),
                )
                runtime_object = _runtime_object_from_cache(
                    cached_runtime, root, directory, args.compiler, target, runtime_source, env,
                    label="WASM component runtime compilation",
                    candidate_name="component-runtime-cache-candidate.o",
                    identity_is_current=lambda: _runtime_cache_key_is_current(
                        root, args.compiler, target, runtime_source, cached_runtime, args
                    ),
                )
        elif not re.search(r"^\s*def\s+arena_alloc\s*\(", flat_source, re.MULTILINE):
            runtime_source = root / "elisacore_std" / "native_runtime_support.elisa"
            if os.environ.get("ELISA_WASM_NO_CACHE"):
                runtime_object = directory / "runtime.o"
                _compile_runtime_object(
                    args.compiler, target, runtime_source, runtime_object, env,
                    "WASM runtime compilation",
                )
            else:
                cached_runtime = runtime_cache_path(
                    root,
                    Path(args.compiler),
                    target,
                    runtime_source,
                    export_scan_launcher=getattr(args, "export_scan_launcher", None),
                    export_scan_script=getattr(args, "export_scan_script", None),
                    python_reference_scanner=getattr(args, "python_reference_scanner", False),
                )
                runtime_object = _runtime_object_from_cache(
                    cached_runtime, root, directory, args.compiler, target, runtime_source, env,
                    label="WASM runtime compilation",
                    candidate_name="runtime-cache-candidate.o",
                    identity_is_current=lambda: _runtime_cache_key_is_current(
                        root, args.compiler, target, runtime_source, cached_runtime, args
                    ),
                )
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
    write_text_if_changed(manifest_path, json.dumps(manifest, indent=2) + "\n")
    if wasm_only:
        print(f"wasm: wrote {output} and {manifest_path}", file=sys.stderr)
    else:
        loader_path = output.with_name(f"{module_name}.mjs")
        types_path = output.with_name(f"{module_name}.d.ts")
        esm_types_path = output.with_name(f"{module_name}.d.mts")
        write_text_if_changed(loader_path, js_bindings(manifest, module_name))
        declarations = type_declaration(manifest, module_name)
        write_text_if_changed(types_path, declarations)
        write_text_if_changed(esm_types_path, declarations)
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
    parser.add_argument(
        "--export-scan-launcher",
        default=os.environ.get("ELISASCRIPT_PUBLIC_LAUNCHER"),
        help=(
            "required absolute Elisascript launcher path for WASM export scanning "
            "(or ELISASCRIPT_PUBLIC_LAUNCHER)"
        ),
    )
    parser.add_argument(
        "--export-scan-script",
        default=os.environ.get("ELISASCRIPT_EXPORT_SCAN_SCRIPT"),
        help=(
            "absolute path to scripts/wasm_export_scan.elisascript "
            "(or ELISASCRIPT_EXPORT_SCAN_SCRIPT)"
        ),
    )
    parser.add_argument(
        "--python-reference-scanner",
        action="store_true",
        help="use the pinned Python scanner explicitly for parity-oracle runs",
    )
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
