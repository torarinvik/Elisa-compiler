#!/usr/bin/env python3
"""Check the dead-trap-exit removal against its shapes.

Each case (dead_trap_exit_cases.py) runs through `elisac llvm-pass dead-trap-exits`. Its
count of functions changed, the branches on a constant the module is left with, and a
second run's count are what the C++ pass did with the same shape. A bounds check `i < len`
in a loop over `[0, n)` stays in the loop when the guards bound n below 100 and len above
99, whatever form the guards take (and, or, select, an offset, past an earlier loop);
a count the ranges do not bound, an i32 counter, or a loop with no exit but traps keeps it.
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE))
from dead_trap_exit_cases import CASES, EXPECTED
from elisa_llvm_pass import run_pass

PASS = 'dead-trap-exits'

failures = 0
for name, source in CASES.items():
    count, module = run_pass(PASS, source)
    again, _ = run_pass(PASS, module)
    got = (count, len(re.findall(r'br i1 (?:true|false),', module)), again)
    if got == EXPECTED[name]:
        print('PASS', name)
    else:
        failures += 1
        print('FAIL', name, 'got', got, 'want', EXPECTED[name])
assert failures == 0, f'{failures} dead-trap-exit cases differ'
