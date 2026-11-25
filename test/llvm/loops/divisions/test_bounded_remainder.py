#!/usr/bin/env python3
"""Check the AArch64 bounded remainder fold against its shapes.

A remainder whose dividend is proven nonnegative and below twice the modulus becomes
`x >= m ? x - m : x` (`bounded.remainder`), each range-checked load the proof used frozen
once (`bounded.load`); a 64-bit remainder by a Mersenne modulus first folds its dividend
(`mersenne.remainder`); a validated divisor gets its accepted range as an assumption on a
frozen copy (`validated.divisor`). The expected counts are the ones the C++ pass reported
for the same shapes (bounded_remainder_cases.py); the pass is idempotent on all of them.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from elisa_llvm_pass import run_pass
from bounded_remainder_cases import CASES

PASS = 'bounded-remainders'
REMAINDER = re.compile(r'= [su]rem i(8|32|64) ')


def check_shape(name, ir, rewrites, module):
    family = name.split('-')[0]
    if family == 'validated':
        assert '%validated.divisor = freeze i64 %divisor' in module, (name, 'divisor not frozen')
        assert re.search(r'icmp ule i64 %validated\.divisor, \d+\n  call void @llvm\.assume', module), (name, 'no assumption')
        return
    marker = '%mersenne.remainder = and i64' if family == 'mersenne' else 'bounded.remainder'
    if family != 'guarded' or 'constant' not in name:
        assert marker in module, (name, 'missing', marker)
    remaining = len(REMAINDER.findall(module))
    assert remaining == len(REMAINDER.findall(ir)) - rewrites, (name, 'remainders left', remaining)
    if family in ('recurrence', 'guarded', 'sum', 'nested', 'many') and 'constant' not in name:
        assert '%bounded.load = freeze' in module, (name, 'load not frozen')


def main():
    for name, (ir, rewrites) in CASES.items():
        changes, module = run_pass(PASS, ir)
        assert changes == rewrites, (name, changes, rewrites)
        if rewrites:
            check_shape(name, ir, rewrites, module)
        again, _ = run_pass(PASS, module)
        assert again == 0, (name, 'not idempotent', again)
        print('PASS', name, flush=True)
    print('bounded remainders: counts and rewritten shapes passed')


if __name__ == '__main__':
    main()
