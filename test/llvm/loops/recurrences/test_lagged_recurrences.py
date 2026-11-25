#!/usr/bin/env python3
"""Check the lagged-recurrence unroll against its shapes, and run what it unrolled.

`lagged-recurrences` unrolls single-block AArch64 loops that rotate a window of
earlier values. Each case's count, and the blocks, adds, shifts and subtractions it
leaves, are what the C++ pass did with the same shapes (lagged_recurrence_cases.py). A
second run changes nothing. On AArch64 the recurrences, before and after the pass, then
run next to each other over every input from 0 to 299: the results must agree.
"""
import ctypes
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE))
from lagged_recurrence_cases import CASES, EXPECTED, MAC
from elisa_llvm_pass import run_pass

PASS = 'lagged-recurrences'
CONFIG = os.environ.get('LLVM_CONFIG', '/opt/homebrew/opt/llvm@23/bin/llvm-config' if os.uname().sysname == 'Darwin' else '/usr/lib/llvm-23/bin/llvm-config')
NATIVE = MAC if os.uname().sysname == 'Darwin' else 'aarch64-unknown-linux-gnu'


def shape(count, module):
    return (count, len(re.findall(r'^[A-Za-z0-9._-]+:', module, re.M)), len(re.findall(r'= add i64 %', module)),
            len(re.findall(r'= shl i64 ', module)), len(re.findall(r'= sub i64 ', module)))


def without_header(module):
    """The module's lines without its header, and without the `; preds =` comments, which
    follow the use lists that reparsing the printed module reorders."""
    return [line.split(';', 1)[0].rstrip() if line.endswith(':') or '; preds = ' in line else line
            for line in module.splitlines() if not line.startswith(('; ModuleID', 'source_filename'))]


def run_side_by_side(name):
    """Build the case before and after the pass and compare `recurrence(x)`."""
    _, module = run_pass(PASS, CASES[name])
    clang = Path(subprocess.run([CONFIG, '--bindir'], capture_output=True, text=True, check=True).stdout.strip()) / 'clang'
    with tempfile.TemporaryDirectory(prefix='elisa-lagged-recurrences-') as temporary:
        functions = []
        for index, text in enumerate([CASES[name], module]):
            source = Path(temporary) / f'recurrence{index}.ll'
            source.write_text(text.replace(MAC, NATIVE))
            library = Path(temporary) / f'recurrence{index}.so'
            subprocess.run([str(clang), '-O1', '-shared', '-fPIC', str(source), '-o', str(library)], check=True, capture_output=True, timeout=60)
            handle = ctypes.CDLL(str(library))
            handle.recurrence.argtypes = [ctypes.c_int64]
            handle.recurrence.restype = ctypes.c_int64
            functions.append((handle, handle.recurrence))
        for value in range(300):
            results = [function(value) for _, function in functions]
            assert results[0] == results[1], (name, value, results)
    print('PASS runtime', name, flush=True)


def main():
    for name, ir in CASES.items():
        count, module = run_pass(PASS, ir)
        assert shape(count, module) == EXPECTED[name], (name, shape(count, module), EXPECTED[name])
        again_count, again = run_pass(PASS, module)
        assert again_count == 0 and without_header(again) == without_header(module), (name, 'not idempotent')
        print('PASS', name, flush=True)
    if os.uname().machine in ('arm64', 'aarch64'):
        for name in ['two', 'scaled', 'affine', 'three', 'two-dispatch', 'affine-dispatch', 'two-trips-16', 'two-trips-256']:
            run_side_by_side(name)
    print('lagged recurrences: counts, shapes, idempotence and runtime results passed')


if __name__ == '__main__':
    main()
