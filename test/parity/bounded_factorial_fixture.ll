target triple = "aarch64-unknown-linux-gnu"
declare {i64,i1} @llvm.smul.with.overflow.i64(i64,i64)
declare void @llvm.trap()
define i64 @fact(i64 %n) {
entry:
 %bad = icmp ugt i64 %n, 20
 br i1 %bad, label %exit, label %pre
pre:
 %small = icmp ult i64 %n, 2
 br i1 %small, label %exit, label %body
body:
 %p = phi i64 [1,%pre], [%low,%ok]
 %c = phi i64 [2,%pre], [%next,%ok]
 %low = mul i64 %p, %c
 %cheap = icmp ult i64 %c, 2
 br i1 %cheap, label %ok, label %slow
slow:
 %m = call {i64,i1} @llvm.smul.with.overflow.i64(i64 %p, i64 %c), !elisa.checkedmul.slow !0
 %o = extractvalue {i64,i1} %m, 1
 br i1 %o, label %trap, label %ok
trap:
 call void @llvm.trap()
 unreachable
ok:
 %next = add i64 %c, 1
 %done = icmp sgt i64 %next, %n
 br i1 %done, label %exit, label %body
exit:
 %r = phi i64 [-1,%entry], [1,%pre], [%low,%ok]
 ret i64 %r
}
!0 = !{}
