target triple = "aarch64-unknown-linux-gnu"
declare {i64,i1} @llvm.smul.with.overflow.i64(i64,i64)
declare {i64,i1} @llvm.sadd.with.overflow.i64(i64,i64)
declare void @llvm.trap()
define i64 @interval(ptr %v, i64 %n) {
entry:
 %bad = icmp ugt i64 %n, 15
 %none = icmp eq i64 %n, 0
 %reject = or i1 %bad, %none
 br i1 %reject, label %exit, label %pre
pre:
 br label %head
head:
 %i = phi i64 [0,%pre], [%next,%latch]
 %s = phi i64 [0,%pre], [%s2,%latch]
 %e = phi i64 [1,%pre], [%e2,%latch]
 %p = getelementptr i64, ptr %v, i64 %i
 %d = load i64, ptr %p
 %d_bad = icmp ugt i64 %d, 8
 br i1 %d_bad, label %exit, label %body
body:
 %m = call {i64,i1} @llvm.smul.with.overflow.i64(i64 %d, i64 %e)
 %mo = extractvalue {i64,i1} %m, 1
 br i1 %mo, label %trap, label %add
add:
 %mv = extractvalue {i64,i1} %m, 0
 %a = call {i64,i1} @llvm.sadd.with.overflow.i64(i64 %s, i64 %d)
 %ao = extractvalue {i64,i1} %a, 1
 br i1 %ao, label %trap, label %sq
sq:
 %t = extractvalue {i64,i1} %a, 0
 %q = call {i64,i1} @llvm.smul.with.overflow.i64(i64 %t, i64 3)
 %qo = extractvalue {i64,i1} %q, 1
 br i1 %qo, label %trap, label %cmp
cmp:
 %qv = extractvalue {i64,i1} %q, 0
 %big = icmp sgt i64 %qv, 50
 br i1 %big, label %reset, label %latch
reset:
 br label %latch
trap:
 call void @llvm.trap()
 unreachable
latch:
 %s2 = phi i64 [%t,%cmp], [0,%reset]
 %e2 = phi i64 [2,%cmp], [1,%reset]
 %next = add i64 %i, 1
 %done = icmp eq i64 %next, %n
 br i1 %done, label %exit, label %head
exit:
 %r = phi i64 [-1,%entry], [-1,%head], [%s2,%latch]
 ret i64 %r
}
