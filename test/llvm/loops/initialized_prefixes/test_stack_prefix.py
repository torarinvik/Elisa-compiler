#!/usr/bin/env python3
"""Check the stack-prefix zero removal's worklist proof on small push/pop shapes.

Each case runs through `elisac llvm-pass stack-prefix-zeros`: the fill of an 8-element
i64 stack goes only when every load reads an element written since the fill on every
path to it.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from elisa_llvm_pass import run_pass

HEAD='''target triple = "TRIPLE"
target datalayout = "e-m:o-i64:64-i128:128-n32:64-S128"
declare void @llvm.memset.p0.i64(ptr, i8, i64, i1 immarg)
declare void @escape(ptr)
define i64 @f(i64 %i) {
entry:
 %a = alloca [8 x i64]
 call void @llvm.memset.p0.i64(ptr %a, i8 0, i64 64, i1 false)
'''.replace('TRIPLE',os.environ.get('ELISA_TEST_TRIPLE','arm64-apple-darwin'))
CASES={
 'push_pop':(' store i64 9, ptr %a\n %v = load i64, ptr %a',1),
 'read_before_write':(' %v = load i64, ptr %a',0),
 'gap':(' %p = getelementptr i64, ptr %a, i64 1\n store i64 9, ptr %p\n %v = load i64, ptr %a',0),
 'wrong_slot':(' store i64 9, ptr %a\n %p = getelementptr i64, ptr %a, i64 1\n %v = load i64, ptr %p',0),
 'escape':(' call void @escape(ptr %a)\n store i64 9, ptr %a\n %v = load i64, ptr %a',0),
 'volatile':(' store volatile i64 9, ptr %a\n %v = load i64, ptr %a',0),
 'dynamic_unproven':(' store i64 9, ptr %a\n %p = getelementptr i64, ptr %a, i64 %i\n %v = load i64, ptr %p',0),
 'conditional_write':(' %c = icmp eq i64 %i, 0\n br i1 %c, label %write, label %join\nwrite:\n store i64 9, ptr %a\n br label %join\njoin:\n %v = load i64, ptr %a',0),
 'both_branches_write':(' %c = icmp eq i64 %i, 0\n br i1 %c, label %left, label %right\nleft:\n store i64 9, ptr %a\n br label %join\nright:\n store i64 8, ptr %a\n br label %join\njoin:\n %v = load i64, ptr %a',1),
 'loop_maybe_empty':(' br label %head\nhead:\n %n = phi i64 [0, %entry], [%n1, %body]\n %c = icmp ult i64 %n, %i\n br i1 %c, label %body, label %exit\nbody:\n store i64 7, ptr %a\n %n1 = add i64 %n, 1\n br label %head\nexit:\n %v = load i64, ptr %a',0),
}
failures = 0
for name, (body, want) in CASES.items():
    count, _ = run_pass('stack-prefix-zeros', HEAD + body + '\n ret i64 %v\n}\n')
    if count == want:
        print('PASS', name)
    else:
        failures += 1
        print('FAIL', name, 'removed', count, 'want', want)
assert failures == 0, f'{failures} stack-prefix cases differ'
