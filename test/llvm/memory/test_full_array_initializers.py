#!/usr/bin/env python3
"""Check the full-array-initializer removal against its shapes.

Each case (full_array_initializer_cases.py) runs through `elisac llvm-pass
full-array-initializers`. Its count of fills removed, the zero fills the module is left
with, and a second run's count are what the C++ pass did with the same shape. A fill of a
private i64 array goes when a loop from zero by one stores every element before any read;
a short or offset count, a read before the loop, an escape or a narrower element keeps it.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
from full_array_initializer_cases import CASES, EXPECTED
from elisa_llvm_pass import run_pass

PASS = 'full-array-initializers'

failures = 0
for name, source in CASES.items():
    count, module = run_pass(PASS, source)
    again, _ = run_pass(PASS, module)
    got = (count, module.count('call void @llvm.memset'), again)
    if got == EXPECTED[name]:
        print('PASS', name)
    else:
        failures += 1
        print('FAIL', name, 'got', got, 'want', EXPECTED[name])
assert failures == 0, f'{failures} full-array-initializer cases differ'
