#!/usr/bin/env python3
"""Fingerprint the environment and executable toolchain used by parity checks.

The parity result cache is only sound when changing a tool or its dynamic libraries
changes the cache key. This helper deliberately fails closed when it cannot identify
the selected tools and their direct dependencies.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import platform
import shutil
import struct
import subprocess
import sys


TOOL_NAMES = (
    "ar", "bash", "cargo", "cc", "clang", "cmake", "c++", "diff", "find",
    "gcc", "g++", "git", "go", "gtimeout", "ld", "llvm-ar", "llvm-as",
    "llvm-config", "llvm-dis", "llvm-nm", "llc", "make", "nm", "node", "ninja",
    "opt", "otool", "python", "python3", "rustc", "sed", "shasum", "strip",
    "timeout", "wasm-ld", "wasmtime", "z3",
)
INTERNAL_ENV = {
    "ELISA_GATE_TOOLCHAIN_HASH",
    "ELISA_GATE_NO_CACHE",
    "ELISA_GATE_LOG_DIR",
}
MACHO_MAGICS = {
    b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf",
    b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca",
    b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca",
}


class Fingerprint:
    def __init__(self) -> None:
        self.digest = hashlib.sha256()
        self.seen_files: set[str] = set()
        self.seen_images: set[str] = set()

    def add(self, value: bytes) -> None:
        self.digest.update(struct.pack(">Q", len(value)))
        self.digest.update(value)

    def add_text(self, value: str) -> None:
        self.add(value.encode("utf-8", "surrogateescape"))

    def add_file(self, path: str) -> None:
        lexical = os.path.abspath(path)
        self.add_text("path:" + lexical)
        if os.path.islink(lexical):
            self.add_text("symlink:" + os.readlink(lexical))
        resolved = os.path.realpath(lexical)
        if resolved in self.seen_files:
            return
        self.seen_files.add(resolved)
        stat = os.stat(resolved)
        if not os.path.isfile(resolved) or not os.access(resolved, os.R_OK):
            raise OSError(f"tool input is not a readable regular file: {resolved}")
        self.add_text("resolved:" + resolved)
        self.add_text(f"mode:{stat.st_mode & 0o7777}")
        file_digest = hashlib.sha256()
        with open(resolved, "rb") as source:
            for chunk in iter(lambda: source.read(1 << 20), b""):
                file_digest.update(chunk)
        self.add(file_digest.digest())

    def add_macho_dependencies(self, path: str, depth: int = 0) -> None:
        resolved = os.path.realpath(path)
        if resolved in self.seen_images:
            return
        self.seen_images.add(resolved)
        with open(resolved, "rb") as source:
            magic = source.read(4)
        if magic not in MACHO_MAGICS:
            return

        otool = shutil.which("otool")
        if not otool:
            raise OSError("otool is unavailable; cannot fingerprint Mach-O dependencies")
        deps = subprocess.run(
            [otool, "-L", resolved], capture_output=True, text=True, timeout=5,
            check=False,
        )
        load_commands = subprocess.run(
            [otool, "-l", resolved], capture_output=True, text=True, timeout=5,
            check=False,
        )
        if deps.returncode or load_commands.returncode:
            raise OSError(f"otool could not inspect {resolved}")

        rpaths: list[str] = []
        lines = load_commands.stdout.splitlines()
        for index, line in enumerate(lines):
            if line.strip() == "cmd LC_RPATH":
                for candidate in lines[index + 1:index + 5]:
                    fields = candidate.strip().split()
                    if len(fields) >= 2 and fields[0] == "path":
                        rpaths.append(fields[1])
                        break

        def expand_loader_tokens(value: str) -> str:
            return value.replace("@loader_path", os.path.dirname(resolved))

        def resolve_dependency(name: str) -> str | None:
            if name.startswith("/"):
                return name if os.path.isfile(name) else None
            if name.startswith("@loader_path/"):
                candidate = expand_loader_tokens(name)
                return candidate if os.path.isfile(candidate) else None
            if name.startswith("@executable_path/"):
                candidate = os.path.join(os.path.dirname(resolved), name.split("/", 1)[1])
                return candidate if os.path.isfile(candidate) else None
            if name.startswith("@rpath/"):
                suffix = name[len("@rpath/"):]
                for rpath in rpaths:
                    base = expand_loader_tokens(rpath)
                    candidate = os.path.join(base, suffix)
                    if os.path.isfile(candidate):
                        return candidate
            return None

        for line in deps.stdout.splitlines()[1:]:
            entry = line.strip().split(" (", 1)[0]
            if not entry:
                continue
            self.add_text("dependency:" + entry)
            dependency = resolve_dependency(entry)
            if dependency is None:
                # System libraries in the dyld shared cache do not always have a
                # standalone path. Their install names and OS identity are still
                # included; unresolved non-system @rpath entries make the key unsafe.
                if entry.startswith("@"):
                    raise OSError(f"could not resolve dynamic dependency {entry} of {resolved}")
                continue
            self.add_file(dependency)
            if depth < 1:
                self.add_macho_dependencies(dependency, depth + 1)

    def tool(self, path: str) -> None:
        if not os.path.exists(path):
            raise OSError(f"selected tool does not exist: {path}")
        self.add_file(path)
        if sys.platform == "darwin":
            self.add_macho_dependencies(path)


def fingerprint() -> str:
    result = Fingerprint()
    result.add_text("elisa-gate-toolchain-v1")
    result.add_text(platform.platform())
    result.add_text(platform.machine())

    for name, value in sorted(os.environ.items()):
        if name in INTERNAL_ENV:
            continue
        result.add_text("env-name:" + name)
        result.add_text(value)
        if os.path.isabs(value) and os.path.isfile(value):
            result.add_file(value)

    tools: set[str] = set()
    for name in TOOL_NAMES:
        selected = shutil.which(name)
        if selected:
            tools.add(selected)
    # Explicit tool variables commonly contain executable paths. Hash every
    # executable-valued environment setting as well, even when its name is new.
    for value in os.environ.values():
        if os.path.isabs(value) and os.path.isfile(value) and os.access(value, os.X_OK):
            tools.add(value)

    for path in sorted(tools):
        result.add_text("tool:" + path)
        result.tool(path)
    return result.digest.hexdigest()


if __name__ == "__main__":
    try:
        print(fingerprint())
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        print(f"gate toolchain fingerprint unavailable: {error}", file=sys.stderr)
        raise SystemExit(1)
