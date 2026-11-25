#!/usr/bin/env python3
"""Check the paired index-bound fold against its shapes.

`a < 0 or b < 0` then `a >= n or b >= n`, rejecting to one block, becomes one select over
`a >=u n'` and `b >=u n'` with `n' = freeze(n) & SIGNED_MAX`, when LazyValueInfo bounds n to
a nonnegative range. On Darwin AArch64 the function's small leaf loops are aligned to 16
bytes unless they set an alignment. The expected counts are the ones the C++ pass reported
for the same shapes (index_bounds_cases.py); test/parity/index_bounds_smoke.py links the
rewritten functions against the originals.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from elisa_llvm_pass import run_pass
from index_bounds_cases import CASES

PASS = 'index-bounds'
ALIGNED = '!"llvm.loop.align", i32 16'
SIGNED_MAXIMA = {
    'i2': '1', 'i32': '2147483647', 'paired': '9223372036854775807',
    'i100': '633825300114114700748351602687', 'i128': '170141183460469231731687303715884105727',
}


def check_rewrite(name, module):
    """The rewritten check selects between the two unsigned compares against the masked bound."""
    assert 'freeze' in module and '%index.bound.defined = freeze' in module, (name, 'no frozen bound')
    assert '%index.invalid = select i1' in module, (name, 'no combined check')
    if name in SIGNED_MAXIMA:
        assert f'%index.bound.defined, {SIGNED_MAXIMA[name]}' in module, (name, 'wrong signed maximum')


def main():
    for name, (ir, rewrites, alignments) in CASES.items():
        changes, module = run_pass(PASS, ir)
        assert changes == rewrites, (name, changes, rewrites)
        again, _ = run_pass(PASS, module)
        assert again == 0, (name, 'not idempotent', again)
        if rewrites:
            check_rewrite(name, module)
        assert module.count(ALIGNED) == alignments, (name, 'alignments', module.count(ALIGNED), alignments)
        print('PASS', name, flush=True)
    _, explicit = run_pass(PASS, CASES['explicit_align'][0])
    assert '!"llvm.loop.align", i32 8' in explicit, 'explicit alignment dropped'
    _, kept = run_pass(PASS, CASES['other_property'][0])
    assert '!"llvm.loop.unroll.disable"' in kept, 'existing loop property dropped'
    print('index bounds: counts, rewrites and loop alignment passed')


if __name__ == '__main__':
    main()
