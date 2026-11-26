#!/usr/bin/env python3
"""Check the covered-prefix zero removal against its shapes.

Each case (covered_prefix_cases.py) runs through `elisac llvm-pass covered-prefix-zeros`.
Its count of fills removed, the module's memset lengths and a second run's count are
what the C++ pass did with the same shape, after the same O1 function simplification.
The whole-array fill goes when the refill of the first `count` elements dominates the
read and a branch proves `j <u count` directly, inverted, or through an `and` or `or`
formula, also on Linux. A `count > j` compare, an unchecked read, a refill of `count`
words, a size-optimized or sanitized function and an x86 target keep the fill.
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))
sys.path.insert(0, str(HERE))
from covered_prefix_cases import CASES, EXPECTED
from elisa_llvm_pass import run_pass

PASS = 'covered-prefix-zeros'


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
assert failures == 0, f'{failures} covered-prefix cases differ'
