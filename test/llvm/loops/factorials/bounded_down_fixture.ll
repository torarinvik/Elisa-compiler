target triple = "aarch64-unknown-linux-gnu"
declare {i64,i1} @llvm.smul.with.overflow.i64(i64,i64)
declare void @llvm.trap()
define i64 @down(i64 %n) {
entry:
 %bad = icmp ugt i64 %n, 33
 br i1 %bad, label %exit, label %pre
pre:
 %go = icmp ugt i64 %n, 1
 br i1 %go, label %body, label %exit
body:
 %p = phi i64 [1,%pre], [%v,%ok]
 %f = phi i64 [%n,%pre], [%next,%ok]
 %m = call {i64,i1} @llvm.smul.with.overflow.i64(i64 %p, i64 %f)
 %o = extractvalue {i64,i1} %m, 1
 br i1 %o, label %trap, label %ok
trap:
 call void @llvm.trap()
 unreachable
ok:
 %v = extractvalue {i64,i1} %m, 0
 %next = add i64 %f, -2
 %more = icmp sgt i64 %f, 3
 br i1 %more, label %body, label %exit
exit:
 %r = phi i64 [-1,%entry], [1,%pre], [%v,%ok]
 ret i64 %r
}
