#!/usr/bin/env python3
"""Check the covered array initializer removal against its shapes.

Each case (covered_array_cases.py) runs through `elisac llvm-pass covered-array-initializers`.
Its count of fills removed, the module's memset lengths and a second run's count are
what the C++ pass did with the same shape. A double array's zero fill goes when a counted
loop writes every element before any read on an AArch64 Linux or Darwin target, also when
the fill is a library memset. A shifted write, another bound, a constant read, an early
exit, a partial fill, a small array, a volatile store, a size-optimized function and an
x86 target keep the fill.
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))
sys.path.insert(0, str(HERE))
from covered_array_cases import CASES, EXPECTED
from elisa_llvm_pass import run_pass

PASS = 'covered-array-initializers'


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
assert failures == 0, f'{failures} covered-array cases differ'
