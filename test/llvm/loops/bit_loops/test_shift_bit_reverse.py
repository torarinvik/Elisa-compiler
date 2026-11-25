#!/usr/bin/env python3
"""Check the shift-and-append bit-reverse fold.

A loop appending the low bit of `word` to `reverse` until `word >> 1` is zero, entered
only for a nonzero input, becomes `bitreverse(input) >> ctlz(input)`. The checked signed
form traps when the partial reverse reaches 2^62 and qualifies only for an input known
nonnegative. Unstable inputs, extra uses, loop metadata and other targets are left alone.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from elisa_llvm_pass import run_pass

ARM64 = 'target datalayout = "e-m:o-i64:64-i128:128-n32:64-S128"\ntarget triple = "arm64-apple-macosx14.0.0"\n'
X86 = 'target datalayout = "e-m:e-i64:64-i128:128-n8:16:32:64-S128"\ntarget triple = "x86_64-unknown-linux-gnu"\n'


def single_block(parameter='i64 noundef %x', prologue='', input_value='%x', append='or i64 %grow, %bit',
                 exit_body='ret i64 %append', loop_metadata='', target=ARM64):
    return target + f'''define i64 @reverse({parameter}) nounwind {{
entry:
{prologue}  %zero_input = icmp eq i64 {input_value}, 0
  br i1 %zero_input, label %zero, label %loop
loop:
  %word = phi i64 [ {input_value}, %entry ], [ %shift, %loop ]
  %reversed = phi i64 [ 0, %entry ], [ %append, %loop ]
  %grow = shl i64 %reversed, 1
  %bit = and i64 %word, 1
  %append = {append}
  %shift = lshr i64 %word, 1
  %done = icmp eq i64 %shift, 0
  br i1 %done, label %exit, label %loop{loop_metadata}
exit:
  {exit_body}
zero:
  ret i64 0
}}
''' + ('!0 = distinct !{!0}\n' if loop_metadata else '')


def checked(sign_test='icmp slt i64 %x, 0'):
    return ARM64 + f'''declare void @llvm.trap()
define i64 @reverse(i64 noundef %x) nounwind {{
entry:
  %negative = {sign_test}
  br i1 %negative, label %fail, label %positive
positive:
  %zero_input = icmp eq i64 %x, 0
  br i1 %zero_input, label %zero, label %head
head:
  %word = phi i64 [ %x, %positive ], [ %shift, %latch ]
  %reversed = phi i64 [ 0, %positive ], [ %append, %latch ]
  %offset = add i64 %reversed, 4611686018427387904
  %overflow = icmp slt i64 %offset, 0
  br i1 %overflow, label %trap, label %latch
trap:
  call void @llvm.trap()
  unreachable
latch:
  %grow = shl i64 %reversed, 1
  %bit = and i64 %word, 1
  %append = or i64 %grow, %bit
  %shift = lshr i64 %word, 1
  %done = icmp eq i64 %shift, 0
  br i1 %done, label %exit, label %head
exit:
  ret i64 %append
zero:
  ret i64 0
fail:
  ret i64 -1
}}
'''


# name: (module, changes)
CASES = {
    'single_block': (single_block(), 1),
    'swapped_append': (single_block(append='or i64 %bit, %grow'), 1),
    'frozen_input': (single_block(parameter='i64 %y', prologue='  %frozen = freeze i64 %y\n', input_value='%frozen'), 1),
    'undef_input': (single_block(parameter='i64 %x'), 0),
    'extra_use': (single_block(exit_body='%both = add i64 %append, %shift\n  ret i64 %both'), 0),
    'loop_metadata': (single_block(loop_metadata=', !llvm.loop !0'), 0),
    'x86': (single_block(target=X86), 0),
    'checked': (checked(), 1),
    'checked_unsigned_guard': (checked(sign_test='icmp ult i64 %x, 0'), 0),
}

if __name__ == '__main__':
    for name, (ir, want) in CASES.items():
        got, module = run_pass('shift-bit-reverse-loops', ir)
        assert got == want, (name, got, module)
        assert ('significant.reverse' in module) == bool(want), (name, module)
        assert ('call void @llvm.trap()' in module) == (name.startswith('checked') and not want), (name, module)
        print('PASS', name)
