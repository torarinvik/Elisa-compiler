"""Identify and fingerprint native runtime tools."""
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


def _stat_identity(_services, info: os.stat_result) -> tuple[int, int, int, int, int]:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)

def _owned_private_path(_services, info: os.stat_result) -> bool:
    uid = getattr(os, "getuid", None)
    if uid is not None and info.st_uid != uid():
        return False
    return not bool(info.st_mode & (stat.S_IWGRP | stat.S_IWOTH))

def _trusted_cache_ancestor(_services, info: os.stat_result) -> bool:
    uid = getattr(os, "getuid", None)
    if uid is not None and info.st_uid not in {0, uid()}:
        return False
    writable = bool(info.st_mode & (stat.S_IWGRP | stat.S_IWOTH))
    return not writable or bool(info.st_mode & stat.S_ISVTX)

def _hash_regular_file(_services, 
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
        if not stat.S_ISREG(opened.st_mode) or _services['_stat_identity'](opened) != _services['_stat_identity'](before):
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
    if (_services['_stat_identity'](opened) != _services['_stat_identity'](after)
            or _services['_stat_identity'](after) != _services['_stat_identity'](current)
            or not stat.S_ISREG(current.st_mode)):
        raise OSError(f"file changed while hashing: {path}")
    return digest.hexdigest(), size, _services['_stat_identity'](after)

def _resolve_executable(_services, path: Path) -> Path | None:
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

def _resolve_llc_executable(_services) -> Path | None:
    # Match the compiler's own tool selection: the selected LLVM bindir wins
    # over PATH, which may contain a different LLVM version.
    configured_bindir = os.environ.get("ELISA_LLVM_BIN_DIR") or elisa_platform.LLVM_BIN_DIR
    candidates = [str(Path(configured_bindir) / "llc") if configured_bindir else None]
    candidates.append(shutil.which("llc"))
    candidates.extend(("/opt/homebrew/opt/llvm/bin/llc", "/usr/local/opt/llvm/bin/llc"))
    for candidate in candidates:
        if not candidate:
            continue
        resolved = _services['_resolve_executable'](Path(candidate))
        if resolved is not None and os.access(resolved, os.X_OK):
            return resolved
    return None

def _resolve_native_object_merger(_services) -> tuple[Path | None, bool]:
    selector = os.environ.get("ELISA_LD", "").strip()
    if selector:
        parts = selector.split()
        return (_services['_resolve_executable'](Path(parts[0])) if parts else None), True

    selected = shutil.which("ld")
    if not selected:
        return None, True
    if sys.platform == "darwin" and os.path.normpath(selected) == "/usr/bin/ld":
        xcrun = _services['_resolve_executable'](Path("/usr/bin/xcrun"))
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
                resolved = _services['_resolve_executable'](toolchain_linker) if toolchain_linker.is_absolute() else None
                if resolved is not None:
                    return resolved, True
            except subprocess.TimeoutExpired:
                # Core's lookup has no timeout and may still select a toolchain
                # linker after this bounded probe expires. Do not share a key
                # that falls back to the /usr/bin/ld dispatch shim.
                return None, False
            except (OSError, subprocess.SubprocessError):
                pass
    return _services['_resolve_executable'](Path(selected)), True

def _llvm_shared_libraries(_services) -> list[Path]:
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
            raise _services['WasmBuildError'](f"cannot inspect LLVM library directory {directory}: {error}") from error
        for candidate in candidates:
            filename = candidate.name
            if filename == "LLVM.framework" and candidate.is_dir():
                try:
                    for framework_binary in (candidate / "Versions").glob("*/LLVM"):
                        resolved = framework_binary.resolve(strict=True)
                        if stat.S_ISREG(resolved.lstat().st_mode):
                            found[str(resolved)] = resolved
                except OSError:
                    raise _services['WasmBuildError'](f"cannot inspect LLVM framework {candidate}")
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
