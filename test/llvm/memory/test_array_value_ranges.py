#!/usr/bin/env python3
"""Check the array value ranges against their shapes.

Each case (array_value_range_cases.py) runs through `elisac llvm-pass array-value-ranges`.
Its count of arrays annotated, the `!range` bounds the module's loads carry, and a second
run's count are what the C++ pass did with the same shape. A zero-filled private array
whose every use is an element-aligned access, fill or copy gets the signed union of zero
and its stored values' ranges (remainders by their divisors, phis and selects by their
choices, vector stores by their lanes, copies by the source array's range) on its loads;
an escaping, viewed or unfilled array, an unbounded store or a misaligned access keeps
its loads as they were.
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
from array_value_range_cases import CASES, EXPECTED
from elisa_llvm_pass import run_pass

PASS = 'array-value-ranges'


def load_ranges(module):
    """The `!range` bounds MODULE's instructions carry, sorted."""
    nodes = dict(re.findall(r'^(!\d+) = !\{([^}]*)\}', module, re.M))
    return tuple(sorted(nodes[node] for node in re.findall(r'!range (!\d+)', module)))


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
assert failures == 0, f'{failures} array-value-range cases differ'
