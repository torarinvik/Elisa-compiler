#!/usr/bin/env python3
"""Check the AArch64 scalar idiom folds against their shapes.

`scalar-loop-idioms` replaces carry-addition loops by one add (`carry.sum`), trailing-zero
shift loops by `cttz` (`trailing.zero.word`), threshold searches by `umax(first,
umin(target, last))`, bit spreads plus one by a rounded power of two
(`bit.spread.rounded`) and nibble population sums by `ctpop`. `odd-trailing-zero-selects`
drops the select guarding `cttz` of an odd value. The expected counts are the ones the C++
passes reported for the same shapes (scalar_idiom_cases.py); both passes are idempotent.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from elisa_llvm_pass import run_pass
from scalar_idiom_cases import CASES

MARKERS = {
    'carry': ['%carry.sum = add i'],
    'zeros': ['%trailing.zero.word = lshr', '@llvm.cttz.'],
    'search': ['@llvm.umin.i64', '@llvm.umax.i64'],
    'spread': ['%bit.spread.rounded = shl'],
    'nibbles': ['@llvm.ctpop.i32'],
    'odd': ['@llvm.cttz.'],
}


def check_shape(name, module):
    family = name.split('-')[0]
    for marker in MARKERS[family]:
        assert marker in module, (name, 'missing', marker)
    if family == 'odd':
        assert ' select ' not in module, (name, 'select kept')


def main():
    for name, (ir, pass_name, expected) in CASES.items():
        changes, module = run_pass(pass_name, ir)
        assert changes == expected, (name, changes, expected)
        if expected:
            check_shape(name, module)
        again, _ = run_pass(pass_name, module)
        assert again == 0, (name, 'not idempotent', again)
        print('PASS', name, flush=True)
    print('scalar idioms: counts and rewritten shapes passed')


if __name__ == '__main__':
    main()
