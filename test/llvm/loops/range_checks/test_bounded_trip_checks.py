#!/usr/bin/env python3
"""Check the bounded-trip check folding against its shapes.

Each case (bounded_trip_cases.py) runs through `elisac llvm-pass bounded-trip-checks`.
Its change count, the `i1 false` and `i1 true` constants the module is left with, and a
second run's count are what the C++ pass did with the same shape. The recurrence over 30
trips keeps both checks safe and decides the lowered sign test; widening the input, the
trip count, the loop body or the step's growth past what the ranges bound keeps them.
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE))
from bounded_trip_cases import CASES, EXPECTED
from elisa_llvm_pass import run_pass

PASS = 'bounded-trip-checks'

failures = 0
for name, source in CASES.items():
    count, module = run_pass(PASS, source)
    again, _ = run_pass(PASS, module)
    got = (count, len(re.findall(r'i1 false', module)), len(re.findall(r'i1 true', module)), again)
    if got == EXPECTED[name]:
        print('PASS', name)
    else:
        failures += 1
        print('FAIL', name, 'got', got, 'want', EXPECTED[name])
assert failures == 0, f'{failures} bounded-trip cases differ'
