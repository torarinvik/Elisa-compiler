#!/usr/bin/env python3
"""Check the view-fill shrink against its shapes.

Each case (view_fill_cases.py) runs through `elisac llvm-pass view-fills`. Its count of
fills shrunk, the lengths of the module's memsets, and a second run's count are what the
C++ pass did with the same shape. A full zero fill of a local integer array used only
through one view of its first elements shrinks to `length * size` bytes when the length
fits the array and every access through the view stays below it: in the caller, in a
helper the view is passed to (cleaned first, so a pointer round trip folds away), in a
helper's helper, below a count the caller shows is at most the length, and through a
recursive call (assumed while it is checked). An access past the length, a looser
length, a fill in a loop, a partial, nonzero or volatile fill, another use of the
array, an escaping or compared pointer, a volatile store, a declared helper and an
`optnone` function keep the fill.
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
from view_fill_cases import CASES, EXPECTED
from elisa_llvm_pass import run_pass

PASS = 'view-fills'


def memset_lengths(module):
    """The sorted length operands of MODULE's memsets."""
    return sorted(re.findall(r'call void @llvm\.memset[^(]*\([^,]*, i8 [^,]*, i64 ([^,]+), i1', module))


failures = 0
for name, source in CASES.items():
    count, module = run_pass(PASS, source)
    again, _ = run_pass(PASS, module)
    got = (count, memset_lengths(module), again)
    if got == EXPECTED[name]:
        print('PASS', name)
    else:
        failures += 1
        print('FAIL', name, 'got', got, 'want', EXPECTED[name])
assert failures == 0, f'{failures} view-fill cases differ'
