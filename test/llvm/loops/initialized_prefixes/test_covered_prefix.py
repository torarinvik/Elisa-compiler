#!/usr/bin/env python3
"""Check the covered-prefix removal step on a guarded read after a prefix refill.

Each case runs through `elisac llvm-pass covered-prefix-removal`, the removal without the
O1 cleanup the full pass runs first: the whole-array fill goes only when the `n << 3`
(no unsigned wrap) refill dominates a read checked below `n`.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from elisa_llvm_pass import run_pass

BASE='''target triple = "arm64-apple-darwin"
declare void @llvm.memset.p0.i64(ptr, i8, i64, i1 immarg)
declare void @unknown(ptr)
define i64 @f(i64 %n, i64 %index) {
entry:
 %a = alloca [16 x i64], align 8
 call void @llvm.memset.p0.i64(ptr %a, i8 0, i64 128, i1 false)
 %bytes = shl nuw i64 %n, 3
 call void @llvm.memset.p0.i64(ptr %a, i8 1, i64 %bytes, i1 false)
 %ok = icmp ult i64 %index, %n
 br i1 %ok, label %read, label %exit
read:
 %p = getelementptr [8 x i8], ptr %a, i64 %index
 %v = load i64, ptr %p, align 8
 ret i64 %v
exit:
 ret i64 0
}
'''
COVER=' call void @llvm.memset.p0.i64(ptr %a, i8 1, i64 %bytes, i1 false)'
BASE=BASE.replace("arm64-apple-darwin",os.environ.get("ELISA_TEST_TRIPLE","arm64-apple-darwin"))
cases={
 'covered':(BASE,1),
 'escape':(BASE.replace(COVER,COVER+'\n call void @unknown(ptr %a)'),0),
 'early_read':(BASE.replace(COVER,' %early = load i64, ptr %a\n'+COVER),0),
 'no_overwrite':(BASE.replace(COVER,''),0),
 'wrapping_length':(BASE.replace('shl nuw','shl'),0),
 'volatile':(BASE.replace('load i64, ptr %p','load volatile i64, ptr %p'),0),
 'unguarded':(BASE.replace('br i1 %ok','br i1 true'),0),
 'outside_prefix':(BASE.replace('ptr %a, i64 %index','ptr %a, i64 %n'),0),
 'partial_initial':(BASE.replace('i64 128, i1 false','i64 120, i1 false'),0),
 'sanitizer':(BASE.replace('@f(i64 %n, i64 %index) {','@f(i64 %n, i64 %index) sanitize_address {'),0),
}
failures = 0
for name, (ir, expected) in cases.items():
    count, _ = run_pass('covered-prefix-removal', ir)
    if count == expected:
        print('PASS', name)
    else:
        failures += 1
        print('FAIL', name, 'removed', count, 'want', expected)
assert failures == 0, f'{failures} covered-prefix cases differ'
