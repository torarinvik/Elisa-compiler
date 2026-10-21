#!/usr/bin/env python3
"""Check call retention without building the compiler."""
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]

with tempfile.TemporaryDirectory(prefix="elisa-atom-slice-") as directory:
    work = Path(directory)
    source = work / "source.elisa"
    probe = work / "probe.elisa"
    output = work / "output.elisa"
    source.write_text('''def needed() -> u32:
    return nested()
def nested() -> u32:
    return 1
def discarded() -> u32:
    return 2
def main() -> u32:
    return discarded()
''')
    for call in (
        'consume("#", needed()) # discarded()',
        "consume('#', needed()) # discarded()",
        r'consume("escaped \" #", needed()) # discarded()',
        "'outer: for x in needed(): # discarded()",
        'consume(needed[Region]("#")) # discarded()',
    ):
        probe.write_text("def main() -> u32:\n    " + call + "\n    return 0\n")
        subprocess.run(
            [sys.executable, str(ROOT / "scripts/compiler_atom_slice.py"),
             str(source), str(probe), str(output)],
            check=True, capture_output=True, text=True, timeout=30,
        )
        sliced = output.read_text()
        assert "def needed()" in sliced, call
        assert "def nested()" in sliced, call
        assert "def discarded()" not in sliced, call
        assert sliced.count("def main()") == 1, call

print("compiler atom slice references: ok")
