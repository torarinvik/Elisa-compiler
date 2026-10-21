#!/usr/bin/env python3
"""Reject short-lived bytes in source-lived readonly diagnostic metadata."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
COMPILER = os.environ.get("ELISACORE_BIN", str(ROOT / "../../Go projects/Elisa-core/compiler/bin/elisac"))
SOURCE = '''global region source
def main() -> i32:
    can Memory.Allocate, Abort.Panic:
        names: mutable darray[sview @source] = []
        region short(4096):
            bytes: mutable darray[u8] @short = [65]
            names.push(bytes.as_sview())
        return 0
'''

with tempfile.TemporaryDirectory(prefix="elisa-readonly-contract-") as directory:
    source = Path(directory) / "short_view.elisa"
    source.write_text(SOURCE)
    result = subprocess.run(
        [COMPILER, "-emit", "obj", "-permissive", "-O0", "-o", str(Path(directory) / "short_view.o"), str(source)],
        capture_output=True, text=True, timeout=30,
    )
    diagnostics = result.stdout + result.stderr
    assert result.returncode != 0, "short-lived view entered source-lived metadata"
    assert 'stored into longer-lived region "source"' in diagnostics, diagnostics
print("readonly metadata short-view rejection: ok")
