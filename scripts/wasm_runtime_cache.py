"""Manage trusted WASM runtime cache artifacts."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Any, Callable

from scripts import elisa_platform


def _runtime_cache_directory_ready(_services, path: Path, root: Path, *, create: bool) -> bool:
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
                or not _services['_trusted_cache_ancestor'](root_info)):
            return False
        for part in root.parts[1:]:
            current = current / part
            info = current.lstat()
            if not stat.S_ISDIR(info.st_mode):
                return False
            if current == root:
                if not _services['_owned_private_path'](info):
                    return False
            elif not _services['_trusted_cache_ancestor'](info):
                return False
        root_info = root.lstat()
        if not stat.S_ISDIR(root_info.st_mode) or not _services['_owned_private_path'](root_info):
            return False
        current = root
        for part in relative.parts:
            current = current / part
            try:
                info = current.lstat()
            except FileNotFoundError:
                continue
            if not stat.S_ISDIR(info.st_mode) or not _services['_owned_private_path'](info):
                return False
        if create:
            path.mkdir(parents=True, exist_ok=True)
            current = root
            for part in relative.parts:
                current = current / part
                info = current.lstat()
                if not stat.S_ISDIR(info.st_mode) or not _services['_owned_private_path'](info):
                    return False
    except OSError:
        return False
    return True

def _runtime_cache_entry_valid(_services, path: Path) -> bool:
    manifest_path = path.with_suffix(path.suffix + ".json")
    try:
        object_digest, object_size, object_identity = _services['_hash_regular_file'](
            path, max_bytes=_services['RUNTIME_CACHE_MAX_BYTES']
        )
        if object_size == 0:
            return False
        object_info = path.lstat()
        if not _services['_owned_private_path'](object_info):
            return False
        manifest_before = manifest_path.lstat()
        if (not stat.S_ISREG(manifest_before.st_mode) or manifest_before.st_size > 4096
                or not _services['_owned_private_path'](manifest_before)):
            return False
        flags = (os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                 | getattr(os, "O_NONBLOCK", 0))
        descriptor = os.open(manifest_path, flags)
        with os.fdopen(descriptor, "rb") as source:
            manifest_opened = os.fstat(source.fileno())
            if (_services['_stat_identity'](manifest_opened) != _services['_stat_identity'](manifest_before)
                    or not stat.S_ISREG(manifest_opened.st_mode)):
                return False
            raw_manifest = source.read(4097)
            manifest_after = os.fstat(source.fileno())
        manifest_current = manifest_path.lstat()
        if len(raw_manifest) > 4096:
            return False
        if (_services['_stat_identity'](manifest_opened) != _services['_stat_identity'](manifest_after)
                or _services['_stat_identity'](manifest_after) != _services['_stat_identity'](manifest_current)
                or not stat.S_ISREG(manifest_current.st_mode)):
            return False
        manifest = json.loads(raw_manifest.decode("utf-8"))
        if manifest != {
            "format": _services['RUNTIME_CACHE_FORMAT'],
            "sha256": object_digest,
            "size": object_size,
        }:
            return False
        return _services['_stat_identity'](path.lstat()) == object_identity
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError, TypeError, ValueError):
        return False

def _runtime_cache_observer_requested(_services) -> bool:
    return (any(os.environ.get(name) for name in _services['RUNTIME_CACHE_OBSERVERS'])
            or "ELISACORE_RETAINED_SERVER" in os.environ
            or bool(os.environ.get("ELISACORE_RETAINED_PROFILE_DIR"))
            or bool(os.environ.get("ELISACORE_RETAINED_HEAPPROFILE"))
            or os.environ.get("ELISACORE_RETAINED_FAST_PREPARE") == "shadow")

def _publish_runtime_cache(_services, candidate: Path, cached: Path) -> bool:
    temporary_object: Path | None = None
    temporary_manifest: Path | None = None
    try:
        digest, size, candidate_identity = _services['_hash_regular_file'](
            candidate, max_bytes=_services['RUNTIME_CACHE_MAX_BYTES']
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
                if not stat.S_ISREG(opened.st_mode) or _services['_stat_identity'](opened) != candidate_identity:
                    return False
                copied = 0
                while copied <= _services['RUNTIME_CACHE_MAX_BYTES']:
                    remaining = _services['RUNTIME_CACHE_MAX_BYTES'] + 1 - copied
                    chunk = source.read(min(1 << 20, remaining))
                    if not chunk:
                        break
                    object_file.write(chunk)
                    copied += len(chunk)
                if copied > _services['RUNTIME_CACHE_MAX_BYTES']:
                    return False
                after = os.fstat(source.fileno())
            current = candidate.lstat()
            if (_services['_stat_identity'](opened) != _services['_stat_identity'](after)
                    or _services['_stat_identity'](after) != _services['_stat_identity'](current)
                    or not stat.S_ISREG(current.st_mode)):
                return False
        temporary_digest, temporary_size, _ = _services['_hash_regular_file'](
            temporary_object, max_bytes=_services['RUNTIME_CACHE_MAX_BYTES']
        )
        if temporary_digest != digest or temporary_size != size:
            return False
        os.replace(temporary_object, cached)
        temporary_object = None
        current_digest, current_size, _ = _services['_hash_regular_file'](cached, max_bytes=_services['RUNTIME_CACHE_MAX_BYTES'])
        if current_digest != digest or current_size != size:
            return False
        manifest_path = cached.with_suffix(cached.suffix + ".json")
        payload = json.dumps(
            {"format": _services['RUNTIME_CACHE_FORMAT'], "sha256": digest, "size": size},
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
        return _services['_runtime_cache_entry_valid'](cached)
    except OSError:
        return False
    finally:
        for temporary in (temporary_object, temporary_manifest):
            if temporary is not None:
                try:
                    temporary.unlink()
                except OSError:
                    pass

def _compile_runtime_object(_services, 
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
    _services['run'](command, label, env)

def _runtime_object_from_cache(_services, 
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
        or _services['_runtime_cache_observer_requested']()
        or not _services['_runtime_cache_directory_ready'](cached.parent, root, create=True)
    ):
        candidate = directory / candidate_name
        _services['_compile_runtime_object'](compiler, target, source, candidate, env, label)
        return candidate
    if _services['_runtime_cache_entry_valid'](cached):
        if identity_is_current is None:
            return cached
        try:
            if identity_is_current():
                return cached
        except (OSError, _services['WasmBuildError']):
            pass
    candidate = directory / candidate_name
    _services['_compile_runtime_object'](compiler, target, source, candidate, env, label)
    if identity_is_current is not None:
        try:
            if not identity_is_current():
                return candidate
        except (OSError, _services['WasmBuildError']):
            return candidate
    if _services['_runtime_cache_directory_ready'](cached.parent, root, create=False) and _services['_publish_runtime_cache'](candidate, cached):
        return cached
    return candidate

def runtime_cache_path(_services, 
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
        flattened_runtime_source = _services['read_flat_source'](runtime_source)
    elif export_scan_launcher is None and export_scan_script is None:
        raise _services['WasmBuildError'](
            "Elisascript export scanner is required; configure both scanner paths "
            "or select --python-reference-scanner for a parity oracle run"
        )
    elif (export_scan_launcher is None) != (export_scan_script is None):
        raise _services['WasmBuildError'](
            "--export-scan-launcher and --export-scan-script must be supplied together"
        )
    elif export_scan_launcher is not None and export_scan_script is not None:
        try:
            flattened_runtime_source = _services['run_flatten_source'](
                export_scan_launcher,
                export_scan_script,
                runtime_source,
            )
        except _services['WasmExportScanClientError'] as error:
            raise _services['WasmBuildError'](str(error)) from error

    digest = hashlib.sha256()
    digest.update(f"elisa-wasm-runtime-cache-v{_services['RUNTIME_CACHE_FORMAT']}\0".encode("ascii"))
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
        selected = _services['_resolve_executable'](candidate)
        digest.update(label.encode("ascii") + b"\0")
        if selected is None:
            # An unresolved selector may be a command looked up by a wrapper
            # through a different PATH or later become executable. Do not let
            # two such states share an object key.
            digest.update(b"unavailable\0" + str(candidate).encode("utf-8") + b"\0" + os.urandom(16))
            continue
        try:
            content_hash, size, _ = _services['_hash_regular_file'](selected)
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
        solver_path = _services['_resolve_executable'](Path(solver_selector))
        if solver_path is None:
            digest.update(b"unavailable\0" + solver_selector.encode("utf-8") + b"\0" + os.urandom(16))
        else:
            try:
                solver_hash, solver_size, _ = _services['_hash_regular_file'](solver_path)
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
    llc_path = _services['_resolve_llc_executable']()
    if llc_path is None:
        digest.update(b"unavailable\0")
    else:
        try:
            llc_hash, llc_size, _ = _services['_hash_regular_file'](llc_path)
        except OSError:
            digest.update(b"unreadable\0" + os.urandom(16))
        else:
            digest.update(str(llc_path).encode("utf-8") + b"\0")
            digest.update(str(llc_size).encode("ascii") + b"\0" + bytes.fromhex(llc_hash))
    try:
        llvm_libraries = _services['_llvm_shared_libraries']()
    except _services['WasmBuildError']:
        # The compile can still succeed; an incomplete native-library identity
        # only disables reuse by making this invocation's key unique.
        digest.update(b"llvm-libraries-unavailable\0" + os.urandom(16))
        llvm_libraries = []
    digest.update(b"llvm-libraries\0")
    if not llvm_libraries:
        digest.update(b"none\0")
    for library in llvm_libraries:
        try:
            content_hash, size, _ = _services['_hash_regular_file'](library)
        except OSError:
            digest.update(b"unreadable\0" + os.urandom(16))
            continue
        digest.update(str(library).encode("utf-8") + b"\0")
        digest.update(str(size).encode("ascii") + b"\0" + bytes.fromhex(content_hash))
    digest.update(b"native-object-merger\0")
    merger_path, merger_identity_known = _services['_resolve_native_object_merger']()
    if not merger_identity_known:
        digest.update(b"unresolved\0" + os.urandom(16))
    elif merger_path is None:
        digest.update(b"unavailable\0")
    else:
        try:
            merger_hash, merger_size, _ = _services['_hash_regular_file'](merger_path)
        except OSError:
            digest.update(b"unreadable\0" + os.urandom(16))
        else:
            digest.update(str(merger_path).encode("utf-8") + b"\0")
            digest.update(str(merger_size).encode("ascii") + b"\0" + bytes.fromhex(merger_hash))
    for name, value in sorted(os.environ.items()):
        if name == "ELISA_STAGE1_WASM":
            continue
        if (name.startswith("ELISA_") or name.startswith("ELISACORE_")
                or name in _services['RUNTIME_CACHE_TOOL_ENV']
                or name in {"PATH", "LLVM_CONFIG", "LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH", "DYLD_FRAMEWORK_PATH"}):
            digest.update(name.encode("utf-8", "surrogateescape") + b"=" + value.encode("utf-8", "surrogateescape") + b"\0")
    return root / "build" / "wasm-cache" / f"runtime-{digest.hexdigest()}.o"

def _runtime_cache_key_is_current(_services, 
    root: Path, compiler: str, target: str, runtime_source: Path,
    expected: Path, args: argparse.Namespace,
) -> bool:
    return _services['runtime_cache_path'](
        root,
        Path(compiler),
        target,
        runtime_source,
        export_scan_launcher=getattr(args, "export_scan_launcher", None),
        export_scan_script=getattr(args, "export_scan_script", None),
        python_reference_scanner=getattr(args, "python_reference_scanner", False),
    ) == expected
