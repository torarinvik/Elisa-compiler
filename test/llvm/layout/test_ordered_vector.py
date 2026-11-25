#!/usr/bin/env python3
"""Check the ordered conversions and paired counters against their shapes.

`ordered-casts` vectorizes eight consecutive i64-to-double conversions summed in order;
`paired-counters` steps two zero-based loop counters as one `<2 x i64>`;
`ordered-conversions` runs both for a one-function AArch64 module with a target machine,
with `instcombine` between them. Each case's count and the reductions, vector phis and
pair loads it leaves are what the C++ passes did with the same shapes
(ordered_vector_cases.py).
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from elisa_llvm_pass import run_pass, run_pass_with_target
from ordered_vector_cases import CAST_CASES, COUNTER_CASES, ENTRY_CASES, EXPECTED, GENERIC_ENTRY_CASES


def shape(count, module):
    reductions = len(re.findall(r'call [a-z ]*double @llvm\.vector\.reduce\.fadd', module))
    vector_phis = len(re.findall(r'= phi <2 x i64>', module))
    pair_loads = len(re.findall(r'load <2 x i64>', module))
    return count, reductions, vector_phis, pair_loads


def check(name, outcome):
    count, module = outcome
    assert shape(count, module) == EXPECTED[name], (name, shape(count, module), EXPECTED[name])
    print('PASS', name, flush=True)


def main():
    for name, ir in CAST_CASES.items():
        check(name, run_pass('ordered-casts', ir))
    for name, ir in COUNTER_CASES.items():
        check(name, run_pass('paired-counters', ir))
    for name, ir in ENTRY_CASES.items():
        check(name, run_pass_with_target('ordered-conversions', ir, 'apple-m1', ''))
    for name, ir in GENERIC_ENTRY_CASES.items():
        check(name, run_pass_with_target('ordered-conversions', ir, 'generic', ''))
    check('entry-no-target', run_pass('ordered-conversions', ENTRY_CASES['entry-eligible']))
    print('ordered vector: counts and vector shapes passed')


if __name__ == '__main__':
    main()
