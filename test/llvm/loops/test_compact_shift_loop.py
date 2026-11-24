#!/usr/bin/env python3
"""Check when compact shift-recurrence unroll policy is applied."""
import os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from elisa_llvm_pass import run_pass
IR='''target triple = "TRIPLE"
define i64 @f(i64 %x, i64 %d) nounwind {
entry: br label %head
head:
 %i = phi i64 [0, %entry], [%next, %latch]
 %acc = phi i64 [0, %entry], [%new, %latch]
 %shift = sub i64 31, %i
 %right = lshr i64 %x, %shift
 %left = shl i64 %d, %shift
 %bit = shl i64 1, %shift
 %condition = icmp ule i64 %d, %right
 %term = select i1 %condition, i64 %left, i64 %bit
 %new = add i64 %acc, %term
 br label %latch
latch:
 %next = add nuw i64 %i, 1
 %more = icmp ult i64 %next, 32
 br i1 %more, label %head, label %exit
exit: ret i64 %new
}
'''.replace('TRIPLE',os.environ.get('ELISA_TEST_TRIPLE','arm64-apple-darwin'))
cases={'fixed_shift':(IR,1),'no_right':(IR.replace('lshr i64 %x, %shift','add i64 %x, %shift'),0),'one_left':(IR.replace('shl i64 1, %shift','add i64 1, %shift'),0),'short':(IR.replace('%next, 32','%next, 8'),0),'non_arm':(IR.replace(os.environ.get('ELISA_TEST_TRIPLE','arm64-apple-darwin'),'x86_64-unknown-linux-gnu'),0),'sanitized':(IR.replace('nounwind {','nounwind sanitize_address {'),0),'size_opt':(IR.replace('nounwind {','nounwind optsize {'),0),'existing_policy':(IR.replace('label %head, label %exit','label %head, label %exit, !llvm.loop !0')+'\n!0 = distinct !{!0, !1}\n!1 = !{!"llvm.loop.unroll.count", i32 2}\n',0)}
for name,(ir,want) in cases.items():
 got,output=run_pass('compact-shift-loops',ir);assert got==want,(name,got);assert ('llvm.loop.unroll.disable' in output)==bool(want),(name,output);print('PASS',name)
