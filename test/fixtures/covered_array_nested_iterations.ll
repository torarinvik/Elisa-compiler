target datalayout = "e-m:o-i64:64-i128:128-n32:64-S128"
target triple = "arm64-apple-darwin"
declare void @llvm.memset.p0.i64(ptr, i8, i64, i1)
define double @nested(i64 %n, i64 %rounds, double %value, i1 %skip) {
entry:
 %array = alloca [128 x double], align 8
 call void @llvm.memset.p0.i64(ptr %array, i8 0, i64 1024, i1 false)
 br label %parent
parent:
 %round = phi i64 [0, %entry], [%round.next, %parent.latch]
 %total = phi double [0.0, %entry], [%sum.exit, %parent.latch]
 %parent.cond = icmp ult i64 %round, %rounds
 br i1 %parent.cond, label %writer.pre, label %exit
writer.pre:
 br label %writer
writer:
 %wi = phi i64 [0, %writer.pre], [%wnext, %writer.body]
 %wcond = icmp ult i64 %wi, %n
 br i1 %wcond, label %writer.body, label %reader.pre
writer.body:
 %wp = getelementptr [8 x i8], ptr %array, i64 %wi
 store double %value, ptr %wp, align 8
 %wnext = add i64 %wi, 1
 br label %writer
reader.pre:
 br label %reader
reader:
 %ri = phi i64 [0, %reader.pre], [%rnext, %reader.body]
 %sum = phi double [%total, %reader.pre], [%sum.next, %reader.body]
 %rcond = icmp ult i64 %ri, %n
 br i1 %rcond, label %reader.body, label %parent.latch
reader.body:
 %rp = getelementptr [8 x i8], ptr %array, i64 %ri
 %v = load double, ptr %rp, align 8
 %sum.next = fadd double %sum, %v
 %rnext = add i64 %ri, 1
 br label %reader
parent.latch:
 %sum.exit = phi double [%sum, %reader]
 %round.next = add i64 %round, 1
 br label %parent
exit:
 ret double %total
}
