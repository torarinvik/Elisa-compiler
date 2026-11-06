#!/usr/bin/env python3
"""Instcombine needing another iteration must not abort -O3 on assertion LLVM. Set ELISAC to test another compiler."""
import os, subprocess, tempfile
from pathlib import Path
ELISAC = os.environ.get('ELISAC') or str(Path(__file__).resolve().parents[2] / 'bin/elisac-stage1')
SOURCE = '''def hash_impl(input: i64&, length: usize) -> i64:
    if length > 65 or (length > 0 and input == null):
        return -1
    if length > 64:
        return -1
    hash: mutable i64 = 5381
    index: mutable usize = 0
    while index < length:
        code_point: i64 = input[index]
        if code_point < 0 or code_point > 255:
            return -1
        hash <- (hash * 33 + code_point) % 4294967296
        index <- index + 1
    hash

export fn hash_abi(input: i64&, length: usize) -> i64 = hash_impl
'''
with tempfile.TemporaryDirectory(prefix='elisa-fixpoint-') as tmp:
    src = Path(tmp) / 'a.elisa'
    src.write_text(SOURCE)
    subprocess.run([ELISAC, '-O3', '-emit', 'obj', '-o', str(Path(tmp) / 'a.o'), str(src)], check=True, capture_output=True, timeout=60)
print('instcombine fixpoint: ok')
