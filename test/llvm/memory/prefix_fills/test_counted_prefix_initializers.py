#!/usr/bin/env python3
"""Check the counted prefix initializers on functions taken from the benchmark corpus.

Each fixture (test/fixtures/counted_prefix/) is one benchmark function, with the functions
it calls, as the scratch-prefix sequence sees it before O3. It runs through
`elisac llvm-pass counted-prefix-initializers`. Its count of fills removed, the module's
memset lengths and a second run's count are what the C++ pass did with the same input.
The fixtures cover counted i16 and i32 arrays, index-linked i32 and i64 arrays and bucket
arrays. The same functions on an x86 target keep every fill.
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))
from elisa_llvm_pass import run_pass

PASS = 'counted-prefix-initializers'
FIXTURES = HERE.parents[2] / 'fixtures' / 'counted_prefix'
EXPECTED = {
    'hash_map_open_addressing_resize': (3, []),
    'predecessor_code': (1, []),
    'rehash': (1, []),
    'reservoir_r_solve': (1, []),
    'singly_link_list_deletion_impl': (2, []),
    'string_left_rotation_impl': (1, []),
    'subtractive_generate': (1, ['220']),
    'word_patterns_impl': (1, []),
}


def memset_lengths(module):
    """The sorted length operands of MODULE's memset intrinsics."""
    return sorted(re.findall(r'call void @llvm\.memset[^(]*\([^,]*, i8 [^,]*, i64 ([^,]+), i1', module))


failures = 0
for name, (count, lengths) in EXPECTED.items():
    source = (FIXTURES / f'{name}.ll').read_text()
    removed, module = run_pass(PASS, source)
    again, _ = run_pass(PASS, module)
    elsewhere, _ = run_pass(PASS, source.replace('arm64-apple-darwin', 'x86_64-apple-darwin'))
    got = (removed, memset_lengths(module), again, elsewhere)
    want = (count, lengths, 0, 0)
    if got == want:
        print('PASS', name)
    else:
        failures += 1
        print('FAIL', name, 'got', got, 'want', want)
assert failures == 0, f'{failures} counted-prefix fixtures differ'
