#!/usr/bin/env python3
"""Check the guarded-counter fold: a checked `+1` counter in a loop becomes `add nsw`
when a synchronized induction variable, bounded by the latch and the guards on its
limit, proves the counter cannot reach the signed maximum.

Covers the cursor proof (equality and ordered latches, with an argument limit frozen
unless it is `noundef`) and the ordered-latch proof, and leaves the counter alone without
a guard, when the overflow flag has another use, or off AArch64.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from elisa_llvm_pass import run_pass

ARM64 = 'target datalayout = "e-m:o-i64:64-i128:128-n32:64-S128"\ntarget triple = "arm64-apple-macosx14.0.0"\n'
X86 = 'target datalayout = "e-m:e-i64:64-i128:128-n8:16:32:64-S128"\ntarget triple = "x86_64-unknown-linux-gnu"\n'


def counter(guard='%small = icmp slt i64 %n, 1000', latch='%done = icmp eq i64 %i.next, %n',
            latch_branch='br i1 %done, label %exit, label %loop', limit='i64 %n', flag_extra='',
            target=ARM64):
    return target + f'''declare {{i64, i1}} @llvm.sadd.with.overflow.i64(i64, i64)
declare void @llvm.trap()
declare void @sink(i1)
define i64 @count(ptr %p, {limit}) nounwind {{
entry:
  {guard}
  br i1 %small, label %pre, label %none
pre:
  %positive = icmp sgt i64 %n, 0
  br i1 %positive, label %loop, label %none
loop:
  %i = phi i64 [ 0, %pre ], [ %i.next, %latch ]
  %c = phi i64 [ 0, %pre ], [ %c.next, %latch ]
  %slot = getelementptr i8, ptr %p, i64 %i
  %byte = load i8, ptr %slot, align 1
  %hit = icmp eq i8 %byte, 0
  br i1 %hit, label %bump, label %latch
bump:
  %checked = call {{i64, i1}} @llvm.sadd.with.overflow.i64(i64 %c, i64 1)
  %overflow = extractvalue {{i64, i1}} %checked, 1
{flag_extra}  br i1 %overflow, label %trap, label %bumped
bumped:
  %sum = extractvalue {{i64, i1}} %checked, 0
  br label %latch
latch:
  %c.next = phi i64 [ %c, %loop ], [ %sum, %bumped ]
  %i.next = add i64 %i, 1
  {latch}
  {latch_branch}
exit:
  ret i64 %c.next
trap:
  call void @llvm.trap()
  unreachable
none:
  ret i64 0
}}
'''


# name: (module, changes, frozen limit expected)
CASES = {
    'equality_latch': (counter(), 1, True),
    'equality_latch_noundef': (counter(limit='i64 noundef %n'), 1, False),
    'ordered_latch': (counter(latch='%more = icmp sle i64 %i.next, %n',
                              latch_branch='br i1 %more, label %loop, label %exit'), 1, False),
    'unguarded': (counter(guard='%small = icmp ne i64 %n, 7'), 0, False),
    'flag_reused': (counter(flag_extra='  call void @sink(i1 %overflow)\n'), 0, False),
    'x86': (counter(target=X86), 0, False),
}

if __name__ == '__main__':
    for name, (ir, want, frozen) in CASES.items():
        got, module = run_pass('guarded-counters', ir)
        assert got == want, (name, got, module)
        assert ('add nsw i64 %c, 1' in module) == bool(want), (name, module)
        assert ('guarded.counter.limit' in module) == frozen, (name, module)
        print('PASS', name)
