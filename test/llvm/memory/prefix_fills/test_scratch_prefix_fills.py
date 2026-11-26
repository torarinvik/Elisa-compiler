#!/usr/bin/env python3
"""Check the scratch-prefix fill removal against its shapes.

Each case (scratch_prefix_cases.py) runs through `elisac llvm-pass scratch-prefix-fills`.
Its count of fills removed, the module's memset lengths and a second run's count are
what the C++ pass did with the same shape. A byte buffer's fill goes when every store
appends at a cursor checked below the capacity and every read is checked below the
cursor and the capacity (either way round), and when the only call reads memory; a
library `memset` call is made the intrinsic first. An unchecked read, a flagged
increment, a store away from the cursor, a partial or repeated fill, a clobbering call,
a volatile read, a buffer under 256 bytes and a sanitized function keep the fill.
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))
sys.path.insert(0, str(HERE))
from scratch_prefix_cases import CASES, EXPECTED
from elisa_llvm_pass import run_pass

PASS = 'scratch-prefix-fills'


def memset_lengths(module):
    """The sorted length operands of MODULE's memset intrinsics."""
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
assert failures == 0, f'{failures} scratch-prefix cases differ'
