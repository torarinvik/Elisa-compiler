#!/usr/bin/env python3
"""Check the private array copy elision against its shapes.

A copy into a private block that is written and copied back, a copy whose source is
never used again, and a temporary used only by two adjacent copies each lose a block
and its copies; a static array's zero fill is removed when a descending loop rewrites
the prefix an ascending loop then reads. `memcpy` libcalls and `memmove`s between
distinct allocas become `llvm.memcpy` first, which the count does not include. The
expected counts and the allocations, copies and fills left are what the C++ pass did
with the same shapes (array_copy_cases.py).
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from array_copy_cases import CASES, SHAPES
from elisa_llvm_pass import run_pass

PASS = 'array-round-trips'


def function_shape(module):
    body = module[module.index('define '):]
    allocations = len(re.findall(r'= alloca |= call ptr @malloc\(', body))
    copies = len(re.findall(r'call void @llvm\.mem(?:cpy|move)\.|call ptr @memcpy\(', body))
    fills = len(re.findall(r'call void @llvm\.memset\.', body))
    return allocations, copies, fills


def main():
    for name, (ir, expected) in CASES.items():
        status, module = run_pass(PASS, ir)
        assert status == expected, (name, status, expected)
        assert function_shape(module) == SHAPES[name], (name, function_shape(module), SHAPES[name])
        again, _ = run_pass(PASS, module)
        assert again == 0, (name, 'not idempotent', again)
        print('PASS', name, flush=True)
    print('array round trips: counts and remaining copies passed')


if __name__ == '__main__':
    main()
