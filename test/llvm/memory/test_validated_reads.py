#!/usr/bin/env python3
"""Check the validated reads against their shapes.

Each case (validated_read_cases.py) runs through `elisac llvm-pass validated-reads`. Its
count of loads annotated, the `!range` bounds the module's loads carry, and a second
run's count are what the C++ pass did with the same shape. A read of an element a
counted loop checked against constants (signed or unsigned, joined by `or` or a select,
on a reload of the same element) gains the checked range when a guard keeps its index
below the loop's bound and only stack writes run in between; an unguarded index, an
intervening write that may reach the memory, an unknown call, an uncovered empty exit,
a misaligned read, an existing range, a volatile read and an `optnone` function keep it.
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
from validated_read_cases import CASES, EXPECTED
from elisa_llvm_pass import run_pass

PASS = 'validated-reads'


def load_ranges(module):
    """The sorted `!range` bounds every load in MODULE carries."""
    nodes = dict(re.findall(r'^(![0-9]+) = !\{(.*)\}$', module, re.M))
    return sorted(tuple(int(bound) for bound in re.findall(r'i\d+ (-?\d+)', nodes[node]))
                  for node in re.findall(r'= load [^\n]*!range (![0-9]+)', module))


failures = 0
for name, source in CASES.items():
    count, module = run_pass(PASS, source)
    again, _ = run_pass(PASS, module)
    got = (count, load_ranges(module), again)
    if got == EXPECTED[name]:
        print('PASS', name)
    else:
        failures += 1
        print('FAIL', name, 'got', got, 'want', EXPECTED[name])
assert failures == 0, f'{failures} validated-read cases differ'
