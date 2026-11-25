#!/usr/bin/env python3
"""Check the AArch64 division reuse against its shapes.

A division a predecessor already computed is reused through a phi (`edge.quotient`), the
other edge computing it or, under a guard proving the dividend nonnegative, shifting
instead; a block whose predecessor joins both quotients takes that phi; factor loops start
from or carry the entry's quotient (`factor.quotient`); an induction divisor reuses the
latch's unsigned quotient (`induction.quotient`). At most four rewrites per function. The
expected counts are the ones the C++ pass reported for the same shapes
(edge_division_cases.py).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from elisa_llvm_pass import run_pass
from edge_division_cases import CASES

PASS = 'edge-division-reuse'
MARKERS = {
    'edge': '%edge.quotient = phi i64', 'shift': '%edge.quotient = phi i64',
    'carry': '%factor.quotient = phi i64', 'induction': '%induction.quotient = phi i64',
    'redundant': '%rem = phi i64 [ %qe, %entry2 ]', 'joined': 'ret i64 %q\n',
}
SHIFTED = {'shift-nonnegative': 'lshr i64 %fx, 3', 'shift-exact': 'lshr exact i64 %fx, 3', 'carry-shift': '%factor.initial.quotient = lshr i64 %n, 3'}
CAPPED = {'four-cap'}


def check_shape(name, module):
    family = name.split('-')[0]
    if family in MARKERS and name != 'induction-signed-latch':
        assert MARKERS[family] in module, (name, 'missing', MARKERS[family])
    if name in SHIFTED:
        assert SHIFTED[name] in module, (name, 'missing', SHIFTED[name])


def main():
    for name, (ir, reused) in CASES.items():
        changes, module = run_pass(PASS, ir)
        assert changes == reused, (name, changes, reused)
        if reused:
            check_shape(name, module)
        if name not in CAPPED:
            again, _ = run_pass(PASS, module)
            assert again == 0, (name, 'not idempotent', again)
        print('PASS', name, flush=True)
    print('edge division reuse: counts and rewritten shapes passed')


if __name__ == '__main__':
    main()
