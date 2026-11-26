#!/usr/bin/env python3
"""Check the stack-prefix zero removal against its shapes.

Each case (stack_prefix_cases.py) runs through `elisac llvm-pass stack-prefix-zeros`.
Its count of fills removed, the module's memset lengths and a second run's count are
what the C++ pass did with the same shape. A 64-element i64 stack's fill goes when every
pop is guarded by an emptiness check (`== 0`, `!= 0` or `> 0`) and reads the element
just below the top, also after a partial fill or a `lifetime.start` before it. An
unchecked pop, a read at or two below the top, a volatile push, a nonzero or volatile
fill, a stack under 8 elements, a `lifetime.start` after the fill and a size-optimized
or sanitized function keep the fill.
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))
sys.path.insert(0, str(HERE))
from stack_prefix_cases import CASES, EXPECTED
from elisa_llvm_pass import run_pass

PASS = 'stack-prefix-zeros'


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
assert failures == 0, f'{failures} stack-prefix cases differ'
