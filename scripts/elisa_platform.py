"""Python twin of scripts/platform.sh: the host link flags and LLVM paths.

Values come from the environment scripts/platform.sh exports when a shell driver sourced it,
else they are derived the same way here, so a Python harness run on its own still links on
macOS (ld64) and Linux (GNU ld) without tools/linux_shim.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

DARWIN = sys.platform == "darwin"


def _llvm_config() -> str:
    env = os.environ.get("LLVM_CONFIG")
    if env:
        return env
    if DARWIN:
        # Match platform.sh: don't let an older llvm-config earlier on PATH override
        # Homebrew's current LLVM formula. The brew prefix query is read-only and must
        # not trigger a formula update while resolving the compiler toolchain.
        brew = shutil.which("brew")
        if not brew:
            raise RuntimeError(
                "Homebrew is required to select LLVM on macOS; set LLVM_CONFIG to override"
            )
        brew_env = os.environ.copy()
        brew_env["HOMEBREW_NO_AUTO_UPDATE"] = "1"
        result = subprocess.run(
            [brew, "--prefix", "llvm"], capture_output=True, text=True, env=brew_env
        )
        if result.returncode != 0:
            raise RuntimeError(
                "Homebrew LLVM is not installed; set LLVM_CONFIG to override"
            )
        candidate = os.path.join(result.stdout.strip(), "bin", "llvm-config")
        if not os.access(candidate, os.X_OK):
            raise RuntimeError(
                "Homebrew LLVM is missing llvm-config; set LLVM_CONFIG to override"
            )
        return candidate
    return shutil.which("llvm-config") or "llvm-config"


LLVM_CONFIG = _llvm_config()


def _query(flag: str, fallback: str) -> str:
    try:
        return subprocess.run([LLVM_CONFIG, flag], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return fallback


def _env(name: str, default) -> str:
    value = os.environ.get(name)
    return value if value is not None else (default() if callable(default) else default)


LD_DEAD_STRIP = _env("ELISA_LD_DEAD_STRIP", "-Wl,-dead_strip" if DARWIN else "-Wl,--gc-sections").split()
LINK_EXE_FLAGS = _env("ELISA_LINK_EXE_FLAGS", "" if DARWIN else "-no-pie -Wl,--unresolved-symbols=ignore-all").split()
LLVM_LIBDIR = _env("ELISA_LLVM_LIBDIR", lambda: _query("--libdir", ""))
LLVM_BIN_DIR = _env("ELISA_LLVM_BIN_DIR", lambda: _query("--bindir", ""))
if not LLVM_LIBDIR or not LLVM_BIN_DIR:
    raise RuntimeError(f"could not read LLVM bin/lib directories from {LLVM_CONFIG}; set ELISA_LLVM_BIN_DIR and ELISA_LLVM_LIBDIR to override")
LLVM_CLANG = os.environ.get("ELISA_CLANG") or os.path.join(LLVM_BIN_DIR, "clang")
# platform.sh's static-archive fallback is not repeated here: a harness that needs it runs
# under a shell driver, which exports ELISA_LLVM_LIBS.
LLVM_LIBS = _env("ELISA_LLVM_LIBS", "-lLLVM").split()
# Every executable link: dead-strip/gc-sections plus the host's exe flags.
EXE_LINK = LD_DEAD_STRIP + LINK_EXE_FLAGS
