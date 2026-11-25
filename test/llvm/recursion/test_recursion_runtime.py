#!/usr/bin/env python3
"""Run the small-recursion passes' outputs next to their inputs on AArch64.

Each module and the module a pass left are built as shared libraries for the native
triple, and their entry functions must agree: the expanded binary recursion, the
literal-specialized calls (on 1004 inputs), the zero-versioned helper's observable
writes, the biased search loop, and the checked accumulators rewritten as loops.
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
from recursion_cases import CASES, DARWIN, run_mode

CONFIG = os.environ.get('LLVM_CONFIG', '/opt/homebrew/opt/llvm@23/bin/llvm-config' if os.uname().sysname == 'Darwin' else '/usr/lib/llvm-23/bin/llvm-config')
NATIVE = DARWIN if os.uname().sysname == 'Darwin' else 'aarch64-unknown-linux-gnu'
U64 = ctypes.c_uint64


def libraries(name, directory):
    """The case's input and its pass output, each loaded as a native shared library."""
    mode, ir = CASES[name]
    _, module = run_mode(mode, ir)
    clang = Path(subprocess.run([CONFIG, '--bindir'], capture_output=True, text=True, check=True).stdout.strip()) / 'clang'
    loaded = []
    for index, text in enumerate([ir, module]):
        source = directory / f'{name}{index}.ll'
        source.write_text(text.replace(DARWIN, NATIVE))
        library = directory / f'{name}{index}.so'
        subprocess.run([str(clang), '-O2', '-shared', '-fPIC', str(source), '-o', str(library)], check=True, capture_output=True, timeout=60)
        loaded.append(ctypes.CDLL(str(library)))
    return loaded


def function(library, name, arguments):
    entry = getattr(library, name)
    entry.argtypes = [U64] * arguments
    entry.restype = U64
    return entry


def agree(name, directory, entry, arguments, inputs):
    entries = [function(library, entry, arguments) for library in libraries(name, directory)]
    for values in inputs:
        results = [call(*values) for call in entries]
        assert results[0] == results[1], (name, values, results)
    print('PASS runtime', name, flush=True)


def main():
    if os.uname().machine not in ('arm64', 'aarch64'):
        print('recursion runtime: skipped off AArch64')
        return
    with tempfile.TemporaryDirectory(prefix='elisa-recursion-runtime-') as temporary:
        directory = Path(temporary)
        agree('inline-binary-darwin', directory, 'entry', 1, [(n,) for n in range(16)])
        generator = random.Random(821)
        values = [0, 1, 2, 2**64 - 1] + [generator.randrange(2**64) for _ in range(1000)]
        literal = [function(library, 'entry_dynamic', 2) for library in libraries('literals-eligible', directory)]
        for index, value in enumerate(values):
            results = [call(index % 7, value) for call in literal]
            assert results[0] == results[1], (index % 7, value, results)
        print('PASS runtime literals-eligible on 1004 inputs', flush=True)
        zero = [function(library, 'entry', 2) for library in libraries('zero-eligible', directory)]
        for n in range(8):
            for iterations in range(1, 16):
                assert [call(n, iterations) for call in zero] == [(n + 1) * iterations] * 2, (n, iterations)
        print('PASS runtime zero-eligible keeps its writes', flush=True)
        bias = [function(library, 'entry', 2) for library in libraries('bias-eligible', directory)]
        for n in range(1, 20):
            for target in range(25):
                expected = target + 5 if target < n else 0
                assert [call(target, n) for call in bias] == [expected, expected], (target, n)
        print('PASS runtime bias-eligible', flush=True)
        small = [(n, x) for n in range(12) for x in range(4)]
        for name in ('accumulator-add', 'accumulator-sub', 'accumulator-call-first', 'accumulator-merged-return',
                     'accumulator-shared-return', 'accumulator-result-in-continue', 'accumulator-guarded'):
            agree(name, directory, 'entry', 2, small)
        agree('accumulator-mul-constant', directory, 'entry', 2, [(n, 1) for n in range(30)])
    print('recursion runtime: outputs agree with inputs')


if __name__ == '__main__':
    main()
