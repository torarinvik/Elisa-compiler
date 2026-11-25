#!/usr/bin/env python3
"""Check the bounded-copy expansion against its shapes, and run it.

`bounded-copies` turns a memcpy or memmove of a variable length that is at most 32
bytes on every path into fixed-size loads and stores. Each case's count, and the
chunk blocks, loads, stores and library copies it leaves, are what the C++ pass did
with the same shapes (bounded_copy_cases.py). On AArch64 the expanded copies of a
few cases also run next to the original calls over every length they allow,
overlapping memmoves included.
"""
import ctypes
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bounded_copy_cases import CASES, DARWIN, EXPECTED
from elisa_llvm_pass import run_pass

PASS = 'bounded-copies'
CONFIG = os.environ.get('LLVM_CONFIG', '/opt/homebrew/opt/llvm@23/bin/llvm-config' if os.uname().sysname == 'Darwin' else '/usr/lib/llvm-23/bin/llvm-config')
NATIVE = DARWIN if os.uname().sysname == 'Darwin' else 'aarch64-unknown-linux-gnu'


def shape(count, module):
    chunks = len(re.findall(r'^bounded\.copy\.[0-9]+[0-9.]*:', module, re.M))
    loads = len(re.findall(r'= load ', module))
    stores = len(re.findall(r'\bstore ', module))
    calls = len(re.findall(r'call void @llvm\.mem(?:cpy|move)\.', module))
    return count, chunks, loads, stores, calls


def run_copies(name, lengths, overlap):
    """Copy each length with the input and the expanded module; the bytes must agree."""
    _, module = run_pass(PASS, CASES[name])
    clang = Path(subprocess.run([CONFIG, '--bindir'], capture_output=True, text=True, check=True).stdout.strip()) / 'clang'
    with tempfile.TemporaryDirectory(prefix='elisa-bounded-copies-') as temporary:
        functions = []
        for index, text in enumerate([CASES[name], module]):
            source = Path(temporary) / f'copy{index}.ll'
            source.write_text(text.replace(DARWIN, NATIVE))
            library = Path(temporary) / f'copy{index}.so'
            subprocess.run([str(clang), '-O1', '-shared', '-fPIC', str(source), '-o', str(library)], check=True, capture_output=True, timeout=60)
            handle = ctypes.CDLL(str(library))
            handle.copy.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint64]
            handle.copy.restype = None
            functions.append((handle, handle.copy))
        for length in lengths:
            results = []
            for _, copy in functions:
                buffer = (ctypes.c_uint8 * 96)(*range(96))
                base = ctypes.addressof(buffer)
                destination, source = (base + 8, base + 3) if overlap else (base + 48, base)
                copy(destination, source, length)
                results.append(bytes(buffer))
            assert results[0] == results[1], (name, length)
    print('PASS runtime', name, flush=True)


def main():
    for name, ir in CASES.items():
        count, module = run_pass(PASS, ir)
        assert shape(count, module) == EXPECTED[name], (name, shape(count, module), EXPECTED[name])
        print('PASS', name, flush=True)
    if os.uname().machine in ('arm64', 'aarch64'):
        run_copies('below-33', range(40), False)
        run_copies('memmove', range(30), True)
        run_copies('even-edge', range(12), False)
        run_copies('offset-below', range(16), False)
    print('bounded copies: counts, shapes and copied bytes passed')


if __name__ == '__main__':
    main()
