"""Run one Elisa-hosted LLVM pass over textual IR through `elisac llvm-pass`.

The compiler is $ELISAC, or bin/elisac-stage1 of this repository.
"""
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPILER = Path(os.environ.get('ELISAC', ROOT / 'bin' / 'elisac-stage1'))


def run_pass(pass_name, ir):
    """Return the pass's change count and the module text it left."""
    with tempfile.TemporaryDirectory(prefix='elisa-llvm-pass-') as temporary:
        source = Path(temporary) / 'input.ll'
        source.write_text(ir)
        result = subprocess.run([str(COMPILER), 'llvm-pass', pass_name, str(source)],
                                capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise AssertionError(f'elisac llvm-pass {pass_name} exited {result.returncode}: {result.stderr}')
    count, _, module = result.stdout.partition('\n')
    return int(count), module
