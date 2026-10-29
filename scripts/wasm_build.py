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
from scripts import elisa_platform
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


def _stat_identity(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _owned_private_path(info: os.stat_result) -> bool:
    uid = getattr(os, "getuid", None)
    if uid is not None and info.st_uid != uid():
        return False
    return not bool(info.st_mode & (stat.S_IWGRP | stat.S_IWOTH))


def _trusted_cache_ancestor(info: os.stat_result) -> bool:
    uid = getattr(os, "getuid", None)
    if uid is not None and info.st_uid not in {0, uid()}:
        return False
    writable = bool(info.st_mode & (stat.S_IWGRP | stat.S_IWOTH))
    return not writable or bool(info.st_mode & stat.S_ISVTX)


def _hash_regular_file(
    path: Path, *, max_bytes: int | None = None
) -> tuple[str, int, tuple[int, int, int, int, int]]:
    """Hash one regular file without following a replacement or symlink."""
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise OSError(f"not a regular file: {path}")
    if max_bytes is not None and before.st_size > max_bytes:
        raise OSError(f"file exceeds cache limit: {path}")
    flags = (os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
             | getattr(os, "O_NONBLOCK", 0))
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as source:
        opened = os.fstat(source.fileno())
        if not stat.S_ISREG(opened.st_mode) or _stat_identity(opened) != _stat_identity(before):
            raise OSError(f"file changed while opening: {path}")
        digest = hashlib.sha256()
        size = 0
        for chunk in iter(lambda: source.read(1 << 20), b""):
            size += len(chunk)
            if max_bytes is not None and size > max_bytes:
                raise OSError(f"file exceeds cache limit: {path}")
            digest.update(chunk)
        after = os.fstat(source.fileno())
    current = path.lstat()
    if (_stat_identity(opened) != _stat_identity(after)
            or _stat_identity(after) != _stat_identity(current)
            or not stat.S_ISREG(current.st_mode)):
        raise OSError(f"file changed while hashing: {path}")
    return digest.hexdigest(), size, _stat_identity(after)


def _resolve_executable(path: Path) -> Path | None:
    raw = str(path)
    selected = raw if path.is_absolute() or len(path.parts) > 1 else shutil.which(raw)
    if not selected:
        return None
    try:
        resolved = Path(selected).resolve(strict=True)
        info = resolved.lstat()
    except OSError:
        return None
    return resolved if stat.S_ISREG(info.st_mode) and os.access(resolved, os.X_OK) else None


def _resolve_llc_executable() -> Path | None:
    # Match the compiler's own tool selection: the selected LLVM bindir wins
    # over PATH, which may contain a different LLVM version.
    configured_bindir = os.environ.get("ELISA_LLVM_BIN_DIR") or elisa_platform.LLVM_BIN_DIR
    candidates = [str(Path(configured_bindir) / "llc") if configured_bindir else None]
    candidates.append(shutil.which("llc"))
    candidates.extend(("/opt/homebrew/opt/llvm/bin/llc", "/usr/local/opt/llvm/bin/llc"))
    for candidate in candidates:
        if not candidate:
            continue
        resolved = _resolve_executable(Path(candidate))
        if resolved is not None and os.access(resolved, os.X_OK):
            return resolved
    return None


def _resolve_native_object_merger() -> tuple[Path | None, bool]:
    selector = os.environ.get("ELISA_LD", "").strip()
    if selector:
        parts = selector.split()
        return (_resolve_executable(Path(parts[0])) if parts else None), True

    selected = shutil.which("ld")
    if not selected:
        return None, True
    if sys.platform == "darwin" and os.path.normpath(selected) == "/usr/bin/ld":
        xcrun = _resolve_executable(Path("/usr/bin/xcrun"))
        if xcrun is not None:
            try:
                result = subprocess.run(
                    [str(xcrun), "--find", "ld"],
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    timeout=2,
                )
                toolchain_linker = Path(result.stdout.strip())
                resolved = _resolve_executable(toolchain_linker) if toolchain_linker.is_absolute() else None
                if resolved is not None:
                    return resolved, True
            except subprocess.TimeoutExpired:
                # Core's lookup has no timeout and may still select a toolchain
                # linker after this bounded probe expires. Do not share a key
                # that falls back to the /usr/bin/ld dispatch shim.
                return None, False
            except (OSError, subprocess.SubprocessError):
                pass
    return _resolve_executable(Path(selected)), True


def _llvm_shared_libraries() -> list[Path]:
    directories = {Path(elisa_platform.LLVM_LIBDIR)}
    for name in ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH", "DYLD_FRAMEWORK_PATH"):
        directories.update(Path(item) for item in os.environ.get(name, "").split(os.pathsep) if item)
    found: dict[str, Path] = {}
    for directory in sorted(directories, key=str):
        try:
            candidates = list(directory.iterdir())
        except FileNotFoundError:
            continue
        except OSError as error:
            raise WasmBuildError(f"cannot inspect LLVM library directory {directory}: {error}") from error
        for candidate in candidates:
            filename = candidate.name
            if filename == "LLVM.framework" and candidate.is_dir():
                try:
                    for framework_binary in (candidate / "Versions").glob("*/LLVM"):
                        resolved = framework_binary.resolve(strict=True)
                        if stat.S_ISREG(resolved.lstat().st_mode):
                            found[str(resolved)] = resolved
                except OSError:
                    raise WasmBuildError(f"cannot inspect LLVM framework {candidate}")
                continue
            shared = filename.startswith("libLLVM") and (
                ".dylib" in filename or ".so" in filename or filename.endswith(".dll")
            )
            if not shared:
                continue
            try:
                resolved = candidate.resolve(strict=True)
                if stat.S_ISREG(resolved.lstat().st_mode):
                    found[str(resolved)] = resolved
            except OSError:
                continue
    return [found[key] for key in sorted(found)]


def _runtime_cache_directory_ready(path: Path, root: Path, *, create: bool) -> bool:
    """Admit cache paths only beneath trusted, non-symlink directories."""
    # Windows mode bits do not establish the effective ACL owner/writability.
    # Until the cache can validate those ACLs, compile without sharing objects.
    if os.name == "nt":
        return False
    root = root.resolve()
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    try:
        current = Path(root.anchor)
        root_info = current.lstat()
        if (not stat.S_ISDIR(root_info.st_mode)
                or not _trusted_cache_ancestor(root_info)):
            return False
        for part in root.parts[1:]:
            current = current / part
            info = current.lstat()
            if not stat.S_ISDIR(info.st_mode):
                return False
            if current == root:
                if not _owned_private_path(info):
                    return False
            elif not _trusted_cache_ancestor(info):
                return False
        root_info = root.lstat()
        if not stat.S_ISDIR(root_info.st_mode) or not _owned_private_path(root_info):
            return False
        current = root
        for part in relative.parts:
            current = current / part
            try:
                info = current.lstat()
            except FileNotFoundError:
                continue
            if not stat.S_ISDIR(info.st_mode) or not _owned_private_path(info):
                return False
        if create:
            path.mkdir(parents=True, exist_ok=True)
            current = root
            for part in relative.parts:
                current = current / part
                info = current.lstat()
                if not stat.S_ISDIR(info.st_mode) or not _owned_private_path(info):
                    return False
    except OSError:
        return False
    return True


def _runtime_cache_entry_valid(path: Path) -> bool:
    manifest_path = path.with_suffix(path.suffix + ".json")
    try:
        object_digest, object_size, object_identity = _hash_regular_file(
            path, max_bytes=RUNTIME_CACHE_MAX_BYTES
        )
        if object_size == 0:
            return False
        object_info = path.lstat()
        if not _owned_private_path(object_info):
            return False
        manifest_before = manifest_path.lstat()
        if (not stat.S_ISREG(manifest_before.st_mode) or manifest_before.st_size > 4096
                or not _owned_private_path(manifest_before)):
            return False
        flags = (os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                 | getattr(os, "O_NONBLOCK", 0))
        descriptor = os.open(manifest_path, flags)
        with os.fdopen(descriptor, "rb") as source:
            manifest_opened = os.fstat(source.fileno())
            if (_stat_identity(manifest_opened) != _stat_identity(manifest_before)
                    or not stat.S_ISREG(manifest_opened.st_mode)):
                return False
            raw_manifest = source.read(4097)
            manifest_after = os.fstat(source.fileno())
        manifest_current = manifest_path.lstat()
        if len(raw_manifest) > 4096:
            return False
        if (_stat_identity(manifest_opened) != _stat_identity(manifest_after)
                or _stat_identity(manifest_after) != _stat_identity(manifest_current)
                or not stat.S_ISREG(manifest_current.st_mode)):
            return False
        manifest = json.loads(raw_manifest.decode("utf-8"))
        if manifest != {
            "format": RUNTIME_CACHE_FORMAT,
            "sha256": object_digest,
            "size": object_size,
        }:
            return False
        return _stat_identity(path.lstat()) == object_identity
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError, TypeError, ValueError):
        return False


def _runtime_cache_observer_requested() -> bool:
    return (any(os.environ.get(name) for name in RUNTIME_CACHE_OBSERVERS)
            or "ELISACORE_RETAINED_SERVER" in os.environ
            or bool(os.environ.get("ELISACORE_RETAINED_PROFILE_DIR"))
            or bool(os.environ.get("ELISACORE_RETAINED_HEAPPROFILE"))
            or os.environ.get("ELISACORE_RETAINED_FAST_PREPARE") == "shadow")


def _publish_runtime_cache(candidate: Path, cached: Path) -> bool:
    temporary_object: Path | None = None
    temporary_manifest: Path | None = None
    try:
        digest, size, candidate_identity = _hash_regular_file(
            candidate, max_bytes=RUNTIME_CACHE_MAX_BYTES
        )
        if size == 0:
            return False
        with tempfile.NamedTemporaryFile(
            "wb", dir=cached.parent, prefix=".runtime-object-", delete=False
        ) as object_file:
            temporary_object = Path(object_file.name)
            flags = (os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                     | getattr(os, "O_NONBLOCK", 0))
            descriptor = os.open(candidate, flags)
            with os.fdopen(descriptor, "rb") as source:
                opened = os.fstat(source.fileno())
                if not stat.S_ISREG(opened.st_mode) or _stat_identity(opened) != candidate_identity:
                    return False
                copied = 0
                while copied <= RUNTIME_CACHE_MAX_BYTES:
                    remaining = RUNTIME_CACHE_MAX_BYTES + 1 - copied
                    chunk = source.read(min(1 << 20, remaining))
                    if not chunk:
                        break
                    object_file.write(chunk)
                    copied += len(chunk)
                if copied > RUNTIME_CACHE_MAX_BYTES:
                    return False
                after = os.fstat(source.fileno())
            current = candidate.lstat()
            if (_stat_identity(opened) != _stat_identity(after)
                    or _stat_identity(after) != _stat_identity(current)
                    or not stat.S_ISREG(current.st_mode)):
                return False
        temporary_digest, temporary_size, _ = _hash_regular_file(
            temporary_object, max_bytes=RUNTIME_CACHE_MAX_BYTES
        )
        if temporary_digest != digest or temporary_size != size:
            return False
        os.replace(temporary_object, cached)
        temporary_object = None
        current_digest, current_size, _ = _hash_regular_file(cached, max_bytes=RUNTIME_CACHE_MAX_BYTES)
        if current_digest != digest or current_size != size:
            return False
        manifest_path = cached.with_suffix(cached.suffix + ".json")
        payload = json.dumps(
            {"format": RUNTIME_CACHE_FORMAT, "sha256": digest, "size": size},
            sort_keys=True,
            separators=(",", ":"),
        ) + "\n"
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=cached.parent, prefix=".runtime-cache-", delete=False
        ) as manifest_file:
            temporary_manifest = Path(manifest_file.name)
            manifest_file.write(payload)
        os.replace(temporary_manifest, manifest_path)
        temporary_manifest = None
        return _runtime_cache_entry_valid(cached)
    except OSError:
        return False
    finally:
        for temporary in (temporary_object, temporary_manifest):
            if temporary is not None:
                try:
                    temporary.unlink()
                except OSError:
                    pass


def _compile_runtime_object(
    compiler: str,
    target: str,
    source: Path,
    candidate: Path,
    env: dict[str, str],
    label: str,
) -> None:
    command = [
        compiler, "-emit", "obj", "-target-triple", target, "-O0", "-o",
        str(candidate), str(source),
    ]
    run(command, label, env)


def _runtime_object_from_cache(
    cached: Path,
    root: Path,
    directory: Path,
    compiler: str,
    target: str,
    source: Path,
    env: dict[str, str],
    *,
    label: str,
    candidate_name: str,
    identity_is_current: Callable[[], bool] | None = None,
) -> Path:
    if (
        os.environ.get("ELISA_WASM_NO_CACHE")
        or _runtime_cache_observer_requested()
        or not _runtime_cache_directory_ready(cached.parent, root, create=True)
    ):
        candidate = directory / candidate_name
        _compile_runtime_object(compiler, target, source, candidate, env, label)
        return candidate
    if _runtime_cache_entry_valid(cached):
        if identity_is_current is None:
            return cached
        try:
            if identity_is_current():
                return cached
        except (OSError, WasmBuildError):
            pass
    candidate = directory / candidate_name
    _compile_runtime_object(compiler, target, source, candidate, env, label)
    if identity_is_current is not None:
        try:
            if not identity_is_current():
                return candidate
        except (OSError, WasmBuildError):
            return candidate
    if _runtime_cache_directory_ready(cached.parent, root, create=False) and _publish_runtime_cache(candidate, cached):
        return cached
    return candidate


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


def runtime_cache_path(
    root: Path,
    compiler: Path,
    target: str,
    runtime_source: Path,
    *,
    export_scan_launcher: str | None = None,
    export_scan_script: str | None = None,
    python_reference_scanner: bool = False,
) -> Path:
    root = root.resolve()
    if python_reference_scanner:
        flattened_runtime_source = read_flat_source(runtime_source)
    elif export_scan_launcher is None and export_scan_script is None:
        raise WasmBuildError(
            "Elisascript export scanner is required; configure both scanner paths "
            "or select --python-reference-scanner for a parity oracle run"
        )
    elif (export_scan_launcher is None) != (export_scan_script is None):
        raise WasmBuildError(
            "--export-scan-launcher and --export-scan-script must be supplied together"
        )
    elif export_scan_launcher is not None and export_scan_script is not None:
        try:
            flattened_runtime_source = run_flatten_source(
                export_scan_launcher,
                export_scan_script,
                runtime_source,
            )
        except WasmExportScanClientError as error:
            raise WasmBuildError(str(error)) from error

    digest = hashlib.sha256()
    digest.update(f"elisa-wasm-runtime-cache-v{RUNTIME_CACHE_FORMAT}\0".encode("ascii"))
    # build() sets this for every compiler subprocess, regardless of the
    # caller's inherited value.
    digest.update(b"effective-env:ELISA_STAGE1_WASM=1\0")
    for label, value in (
        (b"target", target.encode("utf-8")),
        (b"runtime-path", str(runtime_source.resolve()).encode("utf-8")),
        (b"flattened-source", flattened_runtime_source.encode("utf-8")),
    ):
        digest.update(len(label).to_bytes(4, "big"))
        digest.update(label)
        digest.update(len(value).to_bytes(8, "big"))
        digest.update(value)
    compiler_candidates = [("compiler", compiler), ("stage1", root / "bin" / "elisac-stage1")]
    # A supported compiler path can be a shell wrapper (for example, the
    # parity path passes tools/s0cache and the Stage1 launcher itself). Those
    # wrappers select the real compiler from the environment at execution
    # time, so fingerprint the selected executable too, not only the wrapper
    # bytes and the selector's path spelling below.
    for name in ("ELISA_STAGE1_BIN", "ELISA_STAGE1_SELF", "ELISA_S0_REAL", "ELISACORE_BIN"):
        selected_by = os.environ.get(name)
        if selected_by:
            compiler_candidates.append((name.lower(), Path(selected_by)))
    for label, candidate in compiler_candidates:
        selected = _resolve_executable(candidate)
        digest.update(label.encode("ascii") + b"\0")
        if selected is None:
            # An unresolved selector may be a command looked up by a wrapper
            # through a different PATH or later become executable. Do not let
            # two such states share an object key.
            digest.update(b"unavailable\0" + str(candidate).encode("utf-8") + b"\0" + os.urandom(16))
            continue
        try:
            content_hash, size, _ = _hash_regular_file(selected)
        except OSError:
            # The build can continue, but an unidentifiable executable must
            # never share a runtime object with another invocation.
            digest.update(b"unreadable\0" + os.urandom(16))
            continue
        digest.update(str(selected).encode("utf-8") + b"\0")
        digest.update(str(size).encode("ascii") + b"\0" + bytes.fromhex(content_hash))
    solver_selector = os.environ.get("ELISA_Z3")
    digest.update(b"smt-solver\0")
    if solver_selector:
        solver_path = _resolve_executable(Path(solver_selector))
        if solver_path is None:
            digest.update(b"unavailable\0" + solver_selector.encode("utf-8") + b"\0" + os.urandom(16))
        else:
            try:
                solver_hash, solver_size, _ = _hash_regular_file(solver_path)
            except OSError:
                digest.update(b"unreadable\0" + os.urandom(16))
            else:
                digest.update(str(solver_path).encode("utf-8") + b"\0")
                digest.update(str(solver_size).encode("ascii") + b"\0" + bytes.fromhex(solver_hash))
    else:
        # Stage0 can carry a non-PATH default solver via Go -ldflags. PATH's
        # `z3` may not be that binary, so an unset selector cannot identify it.
        digest.update(b"unresolved-default\0" + os.urandom(16))
    digest.update(b"llc\0")
    llc_path = _resolve_llc_executable()
    if llc_path is None:
        digest.update(b"unavailable\0")
    else:
        try:
            llc_hash, llc_size, _ = _hash_regular_file(llc_path)
        except OSError:
            digest.update(b"unreadable\0" + os.urandom(16))
        else:
            digest.update(str(llc_path).encode("utf-8") + b"\0")
            digest.update(str(llc_size).encode("ascii") + b"\0" + bytes.fromhex(llc_hash))
    try:
        llvm_libraries = _llvm_shared_libraries()
    except WasmBuildError:
        # The compile can still succeed; an incomplete native-library identity
        # only disables reuse by making this invocation's key unique.
        digest.update(b"llvm-libraries-unavailable\0" + os.urandom(16))
        llvm_libraries = []
    digest.update(b"llvm-libraries\0")
    if not llvm_libraries:
        digest.update(b"none\0")
    for library in llvm_libraries:
        try:
            content_hash, size, _ = _hash_regular_file(library)
        except OSError:
            digest.update(b"unreadable\0" + os.urandom(16))
            continue
        digest.update(str(library).encode("utf-8") + b"\0")
        digest.update(str(size).encode("ascii") + b"\0" + bytes.fromhex(content_hash))
    digest.update(b"native-object-merger\0")
    merger_path, merger_identity_known = _resolve_native_object_merger()
    if not merger_identity_known:
        digest.update(b"unresolved\0" + os.urandom(16))
    elif merger_path is None:
        digest.update(b"unavailable\0")
    else:
        try:
            merger_hash, merger_size, _ = _hash_regular_file(merger_path)
        except OSError:
            digest.update(b"unreadable\0" + os.urandom(16))
        else:
            digest.update(str(merger_path).encode("utf-8") + b"\0")
            digest.update(str(merger_size).encode("ascii") + b"\0" + bytes.fromhex(merger_hash))
    for name, value in sorted(os.environ.items()):
        if name == "ELISA_STAGE1_WASM":
            continue
        if (name.startswith("ELISA_") or name.startswith("ELISACORE_")
                or name in RUNTIME_CACHE_TOOL_ENV
                or name in {"PATH", "LLVM_CONFIG", "LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH", "DYLD_FRAMEWORK_PATH"}):
            digest.update(name.encode("utf-8", "surrogateescape") + b"=" + value.encode("utf-8", "surrogateescape") + b"\0")
    return root / "build" / "wasm-cache" / f"runtime-{digest.hexdigest()}.o"


def _runtime_cache_key_is_current(
    root: Path, compiler: str, target: str, runtime_source: Path,
    expected: Path, args: argparse.Namespace,
) -> bool:
    return runtime_cache_path(
        root,
        Path(compiler),
        target,
        runtime_source,
        export_scan_launcher=getattr(args, "export_scan_launcher", None),
        export_scan_script=getattr(args, "export_scan_script", None),
        python_reference_scanner=getattr(args, "python_reference_scanner", False),
    ) == expected


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
