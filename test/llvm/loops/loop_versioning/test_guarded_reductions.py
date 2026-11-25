#!/usr/bin/env python3
"""Check the guarded-reduction unrolling against its shape.

A single-block loop of two double loads, one fadd and one fmul, exiting when its counter
equals N, is unrolled by four, remainder included, when a branch proves 1 <= N <= 16 on the way in
(`N + -17 <u -16` failing). Without that guard or a dedicated preheader, with a side effect in the body, or in a
function with a debug location or size optimization, it is left alone.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from elisa_llvm_pass import run_pass


def reduction(guard='%biased = add i64 %n, -17\n  %large = icmp ult i64 %biased, -16',
              body_extra='', attributes='nounwind', exit_compare='icmp eq i64 %next, %n',
              preheader=True):
    into_loop = 'preheader' if preheader else 'entry'
    preheader_block = 'preheader:\n  br label %loop\n' if preheader else ''
    return f'''target datalayout = "e-m:o-i64:64-i128:128-n32:64-S128"
target triple = "arm64-apple-macosx14.0.0"
declare void @sink(double)
define double @dot(ptr %a, ptr %b, i64 %n) {attributes} {{
entry:
  {guard}
  br i1 %large, label %fallback, label %{'preheader' if preheader else 'loop'}
{preheader_block}loop:
  %i = phi i64 [ 0, %{into_loop} ], [ %next, %loop ]
  %sum = phi double [ 0.0, %{into_loop} ], [ %total, %loop ]
  %pa = getelementptr double, ptr %a, i64 %i
  %pb = getelementptr double, ptr %b, i64 %i
  %x = load double, ptr %pa, align 8
  %y = load double, ptr %pb, align 8
  %product = fmul double %x, %y
  %total = fadd double %sum, %product
{body_extra}  %next = add i64 %i, 1
  %done = {exit_compare}
  br i1 %done, label %exit, label %loop
exit:
  ret double %total
fallback:
  ret double 0.0
}}
'''


# name: (module, changes)
CASES = {
    'guarded': (reduction(), 1),
    'unguarded': (reduction(guard='%large = icmp ult i64 %n, 3'), 0),
    'other_offset': (reduction(guard='%biased = add i64 %n, -9\n  %large = icmp ult i64 %biased, -16'), 0),
    'side_effect': (reduction(body_extra='  call void @sink(double %total)\n'), 0),
    'size_optimized': (reduction(attributes='nounwind optsize'), 0),
    'ordered_exit': (reduction(exit_compare='icmp uge i64 %next, %n'), 0),
    'no_preheader': (reduction(preheader=False), 0),
}

if __name__ == '__main__':
    for name, (ir, want) in CASES.items():
        got, module = run_pass('guarded-reductions', ir)
        assert got == want, (name, got, module)
        # Four copies in the unrolled body and three in the unrolled remainder.
        multiplies = module.count('fmul double')
        assert multiplies == (7 if want else 1), (name, module)
        print('PASS', name)
