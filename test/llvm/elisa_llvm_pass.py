"""Run one Elisa-hosted LLVM pass over textual IR through `elisac llvm-pass`.

The compiler is $ELISAC, or bin/elisac-stage1 of this repository.
"""
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPILER = Path(os.environ.get('ELISAC', ROOT / 'bin' / 'elisac-stage1'))


def run_pass_with_target(pass_name, ir, cpu, features):
    """Return the pass's change count and the module text it left. A CPU (and FEATURES)
    gives the pass a target machine for the module's triple; None runs it without one."""
    with tempfile.TemporaryDirectory(prefix='elisa-llvm-pass-') as temporary:
        source = Path(temporary) / 'input.ll'
        source.write_text(ir)
        command = [str(COMPILER), 'llvm-pass', pass_name, str(source)]
        if cpu is not None:
            command += [cpu] + ([features] if features is not None else [])
        result = subprocess.run(command, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise AssertionError(f'elisac llvm-pass {pass_name} exited {result.returncode}: {result.stderr}')
    count, _, module = result.stdout.partition('\n')
    return int(count), module


def run_pass(pass_name, ir):
    """Return the pass's change count and the module text it left, without a target machine."""
    return run_pass_with_target(pass_name, ir, None, None)
