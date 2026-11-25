#!/usr/bin/env python3
"""Check the signed-check prover and the recursive argument bounds against their shapes.

Each case (signed_check_cases.py) runs through `elisac llvm-pass` with a generic CPU's
target machine. Its change count, the checked operations, freezes and conditional
branches the module is left with, and a second run's count are what the C++ passes did
with the same shape. Among them: a sum of one bounded term per iteration of a loop counted
to a guarded limit, and a stack top pushed below a capacity and popped above zero, make
checked arithmetic over them safe; Euler's totient divides `remaining` by its factors and
takes `result - result / factor`, both only shrinking from a nonnegative start, while the
counter `factor` is bounded by the guard `factor <= remaining / factor`. Each negative
removes the fact a proof needs, and the check stays.
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE))
from signed_check_cases import CASES, EXPECTED
from elisa_llvm_pass import run_pass_with_target

CPU = 'generic'


def numbers(module):
    """The checked operations, freezes and conditional branches MODULE has."""
    checks = len(re.findall(r'= call \{ i64, i1 \} @llvm\.[su]\w+\.with\.overflow', module))
    return checks, module.count('= freeze '), len(re.findall(r'\bbr i1 ', module))


failures = 0
for name, (pass_name, source) in CASES.items():
    count, module = run_pass_with_target(pass_name, source, CPU, None)
    again, _ = run_pass_with_target(pass_name, module, CPU, None)
    got = (count, *numbers(module), again)
    if got == EXPECTED[name]:
        print('PASS', name)
    else:
        failures += 1
        print('FAIL', name, 'got', got, 'want', EXPECTED[name])
assert failures == 0, f'{failures} signed-check cases differ'
