#!/usr/bin/env python3
"""Check the remainder rewrites on AArch64.

A Euclid loop `while (r = x % y) != 0` past a `y == 0` guard is split: two leading
remainder steps, then `x - y` whenever it is below y and a division otherwise. The guard
may be a short-circuit `select`, and an inlined loop's exit gets a result phi.

A 64-bit remainder by a divisor invariant in an innermost nested loop, of a dividend
bounded by 65535, becomes a multiply by a reciprocal hoisted to the preheader.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from elisa_llvm_pass import run_pass

ARM64 = 'target datalayout = "e-m:o-i64:64-i128:128-n32:64-S128"\ntarget triple = "arm64-apple-macosx14.0.0"\n'
X86 = 'target datalayout = "e-m:e-i64:64-i128:128-n8:16:32:64-S128"\ntarget triple = "x86_64-unknown-linux-gnu"\n'


def euclid(guard='%zero = icmp eq i64 %b, 0', condition='%zero', loop_extra='', test='icmp eq i64 %r, 0',
           target=ARM64):
    return target + f'''define i64 @gcd(i64 %a, i64 %b, i1 %c) nounwind {{
entry:
  {guard}
  br i1 {condition}, label %exit, label %loop
loop:
  %x = phi i64 [ %a, %entry ], [ %y, %loop ]
  %y = phi i64 [ %b, %entry ], [ %r, %loop ]
  %r = urem i64 %x, %y
{loop_extra}  %done = {test}
  br i1 %done, label %exit, label %loop
exit:
  %result = phi i64 [ %a, %entry ], [ %y, %loop ]
  ret i64 %result
}}
'''


def inlined_euclid():
    return ARM64 + '''define i64 @lcm(i64 %a, i64 %b) nounwind {
entry:
  %zero = icmp eq i64 %b, 0
  br i1 %zero, label %none, label %loop
loop:
  %x = phi i64 [ %a, %entry ], [ %y, %loop ]
  %y = phi i64 [ %b, %entry ], [ %r, %loop ]
  %r = urem i64 %x, %y
  %done = icmp eq i64 %r, 0
  br i1 %done, label %exit, label %loop
exit:
  %quotient = udiv i64 %a, %y
  %product = mul i64 %quotient, %b
  ret i64 %product
none:
  ret i64 0
}
'''


def nested(dividend='%masked = and i64 %value, 1023', operation='urem', divisor='%d', target=ARM64):
    return target + f'''define i64 @table(ptr %p, i64 %n, i64 %d) nounwind {{
entry:
  %any = icmp eq i64 %n, 0
  br i1 %any, label %exit, label %outer
outer:
  %i = phi i64 [ 0, %entry ], [ %i_next, %outer_latch ]
  %outer_sum = phi i64 [ 0, %entry ], [ %inner_total, %outer_latch ]
  br label %inner
inner:
  %j = phi i64 [ 0, %outer ], [ %j_next, %inner ]
  %sum = phi i64 [ %outer_sum, %outer ], [ %total, %inner ]
  %slot = getelementptr i64, ptr %p, i64 %j
  %value = load i64, ptr %slot, align 8
  {dividend}
  %rem = {operation} i64 %masked, {divisor}
  %total = add i64 %sum, %rem
  %j_next = add i64 %j, 1
  %inner_done = icmp eq i64 %j_next, %n
  br i1 %inner_done, label %outer_latch, label %inner
outer_latch:
  %inner_total = phi i64 [ %total, %inner ]
  %i_next = add i64 %i, 1
  %outer_done = icmp eq i64 %i_next, %n
  br i1 %outer_done, label %exit, label %outer
exit:
  %result = phi i64 [ 0, %entry ], [ %inner_total, %outer_latch ]
  ret i64 %result
}}
'''


# name: (module, changes, marker expected when it changes)
CASES = {
    'euclid': (euclid(), 1, 'remainder.first'),
    'select_guard': (euclid(guard='%zero = icmp eq i64 %b, 0\n  %either = select i1 %c, i1 true, i1 %zero',
                            condition='%either'), 1, 'remainder.first'),
    'inlined_euclid': (inlined_euclid(), 1, 'remainder.result'),
    'extra_instruction': (euclid(loop_extra='  %spare = add i64 %r, 1\n'), 0, ''),
    'nonzero_exit': (euclid(test='icmp ne i64 %r, 0'), 0, ''),
    'euclid_x86': (euclid(target=X86), 0, ''),
    'small_dividend': (nested(), 1, 'remainder.reciprocal'),
    'signed_small_dividend': (nested(operation='srem'), 1, 'remainder.reciprocal'),
    'scaled_dividend': (nested(dividend='%byte = and i64 %value, 255\n  %masked = mul nuw i64 %byte, 100'), 1,
                        'remainder.reciprocal'),
    'large_dividend': (nested(dividend='%masked = and i64 %value, 65536'), 0, ''),
    'constant_divisor': (nested(divisor='7'), 0, ''),
    'nested_x86': (nested(target=X86), 0, ''),
}

if __name__ == '__main__':
    for name, (ir, want, marker) in CASES.items():
        got, module = run_pass('remainder-recurrences', ir)
        assert got == want, (name, got, module)
        if marker:
            assert marker in module, (name, module)
        print('PASS', name)
