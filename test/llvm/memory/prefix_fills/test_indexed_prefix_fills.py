#!/usr/bin/env python3
"""Check the indexed-prefix fill removal against its shapes.

Each case (indexed_prefix_cases.py) runs through `elisac llvm-pass indexed-prefix-fills`.
Its count of fills removed or shortened, the module's memset lengths, whether the array
gained the written-prefix mark, and a second run's count are what the C++ pass did with
the same shape. A fill goes when every read stays below the length a fill loop or a copy
wrote (extended by a sentinel store), below values another proved array stores (a
permutation), below the length a view's callee keeps to, or below a stack's pushes, for
arrays of integers, of structs pushed whole, and of records regrouped from integers. A
stack that relies on the fill's leading zeros keeps the fill, shortened to them; a read,
copy or view past the prefix, a missing sentinel, an unbounded stored index, a half
written struct or record, and the shapes the C++ proof does not reach keep the fill.
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))
sys.path.insert(0, str(HERE))
from indexed_prefix_cases import CASES, EXPECTED
from elisa_llvm_pass import run_pass

PASS = 'indexed-prefix-fills'


def memset_lengths(module):
    """The sorted length operands of MODULE's memsets."""
    return sorted(re.findall(r'call void @llvm\.memset[^(]*\([^,]*, i8 [^,]*, i64 ([^,]+), i1', module))


failures = 0
for name, source in CASES.items():
    count, module = run_pass(PASS, source)
    again, _ = run_pass(PASS, module)
    got = (count, memset_lengths(module), '!elisa.written.prefix' in module, again)
    if got == EXPECTED[name]:
        print('PASS', name)
    else:
        failures += 1
        print('FAIL', name, 'got', got, 'want', EXPECTED[name])
assert failures == 0, f'{failures} indexed-prefix cases differ'
