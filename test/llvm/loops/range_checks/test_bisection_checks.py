#!/usr/bin/env python3
"""Check the bisection-check versioning against its shapes.

Each case (bisection_check_cases.py) runs through `elisac llvm-pass
bisection-check-versioning`. Its change count, the `bisect.*` values and freezes the module
is left with, its branch weights, and a second run's count are what the C++ pass did with
the same shape. A binary search whose `end` only moves down to the midpoint gets its
bounds check rewritten (the weights trade places with the successors when the trap was
the false edge); a different midpoint, guard, check, `end` update or a limit that cannot
move to the preheader leaves the check as it was.
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE))
from bisection_check_cases import CASES, EXPECTED
from elisa_llvm_pass import run_pass

PASS = 'bisection-check-versioning'


def numbers(module):
    """The `bisect.*` values and freezes MODULE defines, and its branch weights."""
    weights = ' '.join(re.findall(r'branch_weights", i32 (\d+, i32 \d+)', module))
    return len(re.findall(r'%bisect\.\S+ = ', module)), module.count('= freeze '), weights


failures = 0
for name, source in CASES.items():
    count, module = run_pass(PASS, source)
    again, _ = run_pass(PASS, module)
    got = (count, *numbers(module), again)
    if got == EXPECTED[name]:
        print('PASS', name)
    else:
        failures += 1
        print('FAIL', name, 'got', got, 'want', EXPECTED[name])
assert failures == 0, f'{failures} bisection-check cases differ'
