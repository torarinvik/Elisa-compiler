#!/usr/bin/env python3
"""Check the proven-check removal against its shapes.

Each case (proven_check_cases.py) runs through `elisac llvm-pass proven-checks`. Its
count of checks folded, the branches on a constant the module is left with, and a second
run's count are what the C++ pass did with the same shape. A check `index <u length`
(or `<=u`, `!=`, either operand order, trapping on either side) folds when guards,
recurrences, midpoints, minimums, joins, selects, scaled and subtracted indices, loop
exits, two-pointer header orders or a checked local array prove it; an unguarded index,
a looser guard, a signed loop test, a load the prover cannot bound and an `optnone`
function keep it.
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE))
from proven_check_cases import CASES, EXPECTED
from elisa_llvm_pass import run_pass

PASS = 'proven-checks'

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
assert failures == 0, f'{failures} proven-check cases differ'
