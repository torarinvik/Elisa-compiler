#!/usr/bin/env python3
"""A moved owning record must survive its producer and caller allocation churn."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
COMPILER = os.environ.get("ELISACORE_BIN", str(ROOT / "../../Go projects/Elisa-core/compiler/bin/elisac"))
RUNTIME = ROOT / "build/runtime/elisacore_runtime.o"
SOURCE = ROOT / "test/fixtures/self_parse_syntax/returned_record_move_arena.elisa"


def run(command):
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise SystemExit(f"command failed ({result.returncode}): {command[0]}\n{result.stdout}{result.stderr}")


if not RUNTIME.is_file():
    raise SystemExit(f"Build the runtime object first: {RUNTIME}")
with tempfile.TemporaryDirectory(prefix="elisa-returned-record-") as directory:
    work = Path(directory)
    obj, binary = work / "moved.o", work / "moved"
    run([COMPILER, "-emit", "obj", "-permissive", "-O0", "-o", str(obj), str(SOURCE)])
    run(["clang", str(obj), str(RUNTIME), "-o", str(binary)])
    run([str(binary)])
print("returned record caller arena: ok")
