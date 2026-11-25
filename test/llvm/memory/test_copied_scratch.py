#!/usr/bin/env python3
"""Check the copied-scratch initializer removal against its shapes.

Each case (copied_scratch_cases.py) runs through `elisac llvm-pass copied-scratch`. Its
count of fills removed, the zero fills and freezes the module is left with, and a second
run's count are what the C++ pass did with the same shape. A fill goes when a counted loop
(and the stores on the path after it, whose branches the argument decides) covers every
copied byte for each argument value the guards allow; an argument that may be undef is
frozen for the trial, and the freeze stays only when the fill goes. A range of arguments
ending at 2^64 is checked value by value, where the C++ pass checked none.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
from copied_scratch_cases import CASES, EXPECTED
from elisa_llvm_pass import run_pass

PASS = 'copied-scratch'

failures = 0
for name, source in CASES.items():
    count, module = run_pass(PASS, source)
    again, _ = run_pass(PASS, module)
    got = (count, module.count('call void @llvm.memset'), module.count('= freeze '), again)
    if got == EXPECTED[name]:
        print('PASS', name)
    else:
        failures += 1
        print('FAIL', name, 'got', got, 'want', EXPECTED[name])
assert failures == 0, f'{failures} copied-scratch cases differ'
