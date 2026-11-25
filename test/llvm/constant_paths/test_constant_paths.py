#!/usr/bin/env python3
"""Check the constant integer path folds against their shapes.

`constant-paths` evaluates deterministic integer paths from an AArch64 function's entry
branch: an equality test's edge becomes a constant return, and a small accepted domain
becomes a mask or table lookup; it also removes a zero-product bypass and the bounds
checks before constant Boolean and state table reads. Each case's count, and the
conditional branches, returns, lookup tables and constant-path blocks it leaves, are
what the C++ pass did with the same shapes (constant_path_cases.py).
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from constant_path_cases import CASES, EXPECTED
from elisa_llvm_pass import run_pass

PASS = 'constant-paths'


def shape(count, module):
    branches = len(re.findall(r'\bbr i1 ', module))
    returns = len(re.findall(r'\bret ', module))
    tables = len(re.findall(r'@integer\.path\.results[0-9]* = ', module))
    constant_blocks = len(re.findall(r'^constant\.path[0-9]*:', module, re.M))
    return count, branches, returns, tables, constant_blocks


def main():
    for name, ir in CASES.items():
        count, module = run_pass(PASS, ir)
        assert shape(count, module) == EXPECTED[name], (name, shape(count, module), EXPECTED[name])
        print('PASS', name, flush=True)
    print('constant paths: counts and folded shapes passed')


if __name__ == '__main__':
    main()
