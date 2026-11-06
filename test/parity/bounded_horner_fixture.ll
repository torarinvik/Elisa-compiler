target triple = "aarch64-unknown-linux-gnu"
declare {i64,i1} @llvm.smul.with.overflow.i64(i64,i64)
declare {i64,i1} @llvm.sadd.with.overflow.i64(i64,i64)
declare void @llvm.trap()
define i64 @horner(ptr %v, i64 %n) {
entry:
 %lo = add i64 %n, -1
 %bad = icmp ugt i64 %n, 12
 %none = icmp ult i64 %n, 1
 %reject = or i1 %bad, %none
 br i1 %reject, label %exit, label %pre
pre:
 br label %head
head:
 %i = phi i64 [0,%pre], [%next,%latch]
 %x = phi i64 [0,%pre], [%xn,%latch]
 %p = getelementptr i64, ptr %v, i64 %i
 %d = load i64, ptr %p
 %d_bad = icmp ugt i64 %d, 26
 br i1 %d_bad, label %exit, label %body
body:
 %m = call {i64,i1} @llvm.smul.with.overflow.i64(i64 %x, i64 26)
 %mo = extractvalue {i64,i1} %m, 1
 br i1 %mo, label %trap, label %add
add:
 %mv = extractvalue {i64,i1} %m, 0
 %a = call {i64,i1} @llvm.sadd.with.overflow.i64(i64 %mv, i64 %d)
 %ao = extractvalue {i64,i1} %a, 1
 br i1 %ao, label %trap, label %latch
trap:
 call void @llvm.trap()
 unreachable
latch:
 %xn = extractvalue {i64,i1} %a, 0
 %next = add i64 %i, 1
 %done = icmp eq i64 %next, %n
 br i1 %done, label %exit, label %head
exit:
 %r = phi i64 [-1,%entry], [-1,%head], [%xn,%latch]
 ret i64 %r
}
