#!/usr/bin/env python3
"""Check the AArch64 reverse byte reductions against their shapes.

A Horner hash read backwards over a privately stored byte prefix folds into a running sum
of `byte * radix^index` kept by the storing blocks, chosen by a phi for the prefix length:
the loop and the byte loads go away. The expected counts are the ones the C++ pass reported
for the same shapes (reverse_byte_cases.py). On an AArch64 Darwin host each folded Darwin
module is also linked and run against the original.
"""
import ctypes
import os
import random
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from elisa_llvm_pass import run_pass
from reverse_byte_cases import CASES, MAC

PASS = 'reverse-byte-reductions'


def check_shape(name, module):
    """The prefix sum reaches the return and nothing reads the byte array any more."""
    assert '%byte.prefix.sum = phi i64' in module, (name, 'no prefix sum')
    assert 'ret i64 %byte.prefix.sum' in module, (name, 'return not folded')
    assert 'load i8' not in module, (name, 'byte load left')


def compile_shared(ir, library, lengths):
    config = os.environ.get('LLVM_CONFIG', '/opt/homebrew/opt/llvm@23/bin/llvm-config')
    bindir = Path(subprocess.run([config, '--bindir'], capture_output=True, text=True, check=True).stdout.strip())
    subprocess.run([bindir / 'clang', '-O2', '-shared', '-fPIC', ir, '-o', library], check=True, capture_output=True, timeout=60)
    function = ctypes.CDLL(str(library)).f
    function.argtypes = [ctypes.c_uint8] * lengths + [ctypes.c_bool] * lengths
    function.restype = ctypes.c_uint64
    return function


def check_execution(name, original, folded, lengths, directory, generator):
    """The original and folded functions hash every prefix the same way."""
    functions = []
    for label, text in (('original', original), ('folded', folded)):
        source = directory / f'{name}-{label}.ll'
        source.write_text(text)
        functions.append(compile_shared(source, directory / f'{name}-{label}.so', lengths))
    for trial in range(4000):
        values = [generator.choice([0, 1, 127, 128, 255]) if trial % 4 == 0 else generator.randrange(256) for _ in range(lengths)]
        stop = generator.randrange(lengths)
        conditions = [index == stop for index in range(lengths)]
        results = [function(*values, *conditions) for function in functions]
        assert results[0] == results[1], (name, values, stop, results)


def main():
    executes = os.uname().machine == 'arm64' and os.uname().sysname == 'Darwin'
    generator = random.Random(20261125)
    with tempfile.TemporaryDirectory(prefix='elisa-reverse-byte-') as temporary:
        directory = Path(temporary)
        for name, (ir, lengths, expected) in CASES.items():
            changes, module = run_pass(PASS, ir)
            assert changes == expected, (name, changes, expected)
            again, _ = run_pass(PASS, module)
            assert again == 0, (name, 'not idempotent', again)
            if expected:
                check_shape(name, module)
                if executes and MAC in ir:
                    check_execution(name, ir, module, lengths, directory, generator)
            print('PASS', name, flush=True)
    print('reverse byte reductions: counts, shapes and linked results passed')


if __name__ == '__main__':
    main()
