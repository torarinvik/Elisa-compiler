#!/usr/bin/env python3
"""Check the loop load forwarding against its shapes.

Each case (loop_load_forwarding_cases.py) runs through `elisac llvm-pass
loop-load-forwarding`. Its count of loops changed, the forwarded-load phis the module is
left with, and a second run's count are what the C++ pass did with the same shape. A
reload of the slot the latch stored last becomes a phi when nothing else in the loop
writes memory and the load runs on every iteration; a loop without a preheader counts as
changed when it gets one, even if nothing is forwarded.
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
from loop_load_forwarding_cases import CASES, EXPECTED
from elisa_llvm_pass import run_pass

PASS = 'loop-load-forwarding'

failures = 0
for name, source in CASES.items():
    count, module = run_pass(PASS, source)
    again, _ = run_pass(PASS, module)
    got = (count, len(re.findall(r'%forwarded\.load\S* = phi', module)), again)
    if got == EXPECTED[name]:
        print('PASS', name)
    else:
        failures += 1
        print('FAIL', name, 'got', got, 'want', EXPECTED[name])
assert failures == 0, f'{failures} loop-load-forwarding cases differ'
