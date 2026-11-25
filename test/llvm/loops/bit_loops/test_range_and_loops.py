#!/usr/bin/env python3
"""Check the range-and fold: clearing low bits of `upper` while it stays above `lower`
becomes `initial & ~(all_ones >> ctlz(lower ^ initial))`. Under a guard admitting only
ordered endpoints below 2^32, a 64-bit loop uses a 32-bit count and loses its entry test.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from elisa_llvm_pass import run_pass

ARM64 = 'target datalayout = "e-m:o-i64:64-i128:128-n32:64-S128"\ntarget triple = "arm64-apple-macosx14.0.0"\n'
X86 = 'target datalayout = "e-m:e-i64:64-i128:128-n8:16:32:64-S128"\ntarget triple = "x86_64-unknown-linux-gnu"\n'


def loop(width='i64', continue_test='icmp ult {t} %lo, %next', step_constant='-1', exit_use='',
         target=ARM64):
    t = width
    test = continue_test.format(t=t)
    return target + f'''define {t} @common({t} %lo, {t} %hi) nounwind {{
entry:
  %enter = icmp ult {t} %lo, %hi
  br i1 %enter, label %loop, label %exit
loop:
  %upper = phi {t} [ %hi, %entry ], [ %next, %loop ]
  %step = add {t} %upper, {step_constant}
  %next = and {t} %upper, %step
  %continue = {test}
  br i1 %continue, label %loop, label %exit
exit:
  %result = phi {t} [ %hi, %entry ], [ %next, %loop ]
{exit_use}  ret {t} %result
}}
'''


def narrow(bound='4294967295'):
    return ARM64 + f'''define i64 @common(i64 %lo, i64 %hi) nounwind {{
entry:
  %order = icmp ugt i64 %lo, %hi
  %bound = icmp ugt i64 %hi, {bound}
  %either = or i1 %order, %bound
  br i1 %either, label %bad, label %check
check:
  %enter = icmp ult i64 %lo, %hi
  br i1 %enter, label %loop, label %exit
loop:
  %upper = phi i64 [ %hi, %check ], [ %next, %loop ]
  %step = add i64 %upper, -1
  %next = and i64 %upper, %step
  %continue = icmp ult i64 %lo, %next
  br i1 %continue, label %loop, label %exit
exit:
  %result = phi i64 [ %hi, %check ], [ %next, %loop ]
  ret i64 %result
bad:
  ret i64 0
}}
'''


# name: (module, changes)
CASES = {
    'wide': (loop(), 1),
    'narrow_type': (loop(width='i32'), 1),
    'greater_form': (loop(continue_test='icmp ugt {t} %next, %lo'), 1),
    'other_step': (loop(step_constant='-2'), 0),
    'signed_test': (loop(continue_test='icmp slt {t} %lo, %next'), 0),
    'x86': (loop(target=X86), 0),
    'narrow_guard': (narrow(), 1),
    'wide_guard_bound': (narrow(bound='8589934591'), 1),
}

if __name__ == '__main__':
    for name, (ir, want) in CASES.items():
        got, module = run_pass('range-and-loops', ir)
        assert got == want, (name, got, module)
        assert ('range.and' in module) == bool(want), (name, module)
        # Only the ordered 32-bit guard takes the narrow count and drops the entry test.
        assert ('ctlz.i32(i32' in module) == (name in ('narrow_guard', 'narrow_type')), (name, module)
        assert ('%enter' in module) == (name != 'narrow_guard'), (name, module)
        print('PASS', name)
