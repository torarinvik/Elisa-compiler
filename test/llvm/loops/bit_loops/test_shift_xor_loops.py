#!/usr/bin/env python3
"""Check the shift-xor fold: a loop adding `place` to `saved` where the low bits of two
shifted operands differ, finished by appending the remaining operand, is `a ^ b`.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from elisa_llvm_pass import run_pass

ARM64 = 'target datalayout = "e-m:o-i64:64-i128:128-n32:64-S128"\ntarget triple = "arm64-apple-macosx14.0.0"\n'
X86 = 'target datalayout = "e-m:e-i64:64-i128:128-n8:16:32:64-S128"\ntarget triple = "x86_64-unknown-linux-gnu"\n'


def loop(both='and i1 %a_nonzero, %b_nonzero', place_start='1', accumulate='add i64 %saved, %addend',
         right_shift='lshr', target=ARM64):
    return target + f'''define i64 @xor(i64 %a, i64 %b) nounwind {{
entry:
  %a_nonzero = icmp ne i64 %a, 0
  %b_nonzero = icmp ne i64 %b, 0
  %both = {both}
  br i1 %both, label %loop, label %exit
loop:
  %left = phi i64 [ %a, %entry ], [ %left_next, %loop ]
  %right = phi i64 [ %b, %entry ], [ %right_next, %loop ]
  %saved = phi i64 [ 0, %entry ], [ %saved_next, %loop ]
  %place = phi i64 [ {place_start}, %entry ], [ %place_next, %loop ]
  %combined = add i64 %left, %right
  %low = trunc i64 %combined to i1
  %addend = select i1 %low, i64 %place, i64 0
  %saved_next = {accumulate}
  %place_next = shl i64 %place, 1
  %left_next = lshr i64 %left, 1
  %right_next = {right_shift} i64 %right, 1
  %left_more = icmp ne i64 %left_next, 0
  %right_more = icmp ne i64 %right_next, 0
  %again = and i1 %left_more, %right_more
  br i1 %again, label %loop, label %exit
exit:
  %saved_tail = phi i64 [ 0, %entry ], [ %saved_next, %loop ]
  %place_tail = phi i64 [ {place_start}, %entry ], [ %place_next, %loop ]
  %left_tail = phi i64 [ %a, %entry ], [ %left_next, %loop ]
  %right_tail = phi i64 [ %b, %entry ], [ %right_next, %loop ]
  %rest = add i64 %left_tail, %right_tail
  %scaled = mul i64 %place_tail, %rest
  %sum = add i64 %saved_tail, %scaled
  ret i64 %sum
}}
'''


# name: (module, changes)
CASES = {
    'xor': (loop(), 1),
    'select_guard': (loop(both='select i1 %a_nonzero, i1 %b_nonzero, i1 false'), 1),
    'swapped_accumulate': (loop(accumulate='add i64 %addend, %saved'), 1),
    'place_starts_at_two': (loop(place_start='2'), 0),
    'arithmetic_shift': (loop(right_shift='ashr'), 0),
    'x86': (loop(target=X86), 0),
}

if __name__ == '__main__':
    for name, (ir, want) in CASES.items():
        got, module = run_pass('shift-xor-loops', ir)
        assert got == want, (name, got, module)
        assert ('shift.xor' in module) == bool(want), (name, module)
        print('PASS', name)
