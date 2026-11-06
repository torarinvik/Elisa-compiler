target triple = "aarch64-unknown-linux-gnu"
declare {i64,i1} @llvm.sadd.with.overflow.i64(i64,i64)
declare void @llvm.trap()
define i64 @dsum(i64 %n) {
entry:
 %bad = icmp ugt i64 %n, 1000000000
 br i1 %bad, label %exit, label %pre
pre:
 br label %head
head:
 %r = phi i64 [%n,%pre], [%q,%ok]
 %s = phi i64 [0,%pre], [%sn,%ok]
 %q = udiv i64 %r, 5
 %m = urem i64 %r, 5
 %c = call {i64,i1} @llvm.sadd.with.overflow.i64(i64 %s, i64 %ADDEND)
 %o = extractvalue {i64,i1} %c, 1
 br i1 %o, label %trap, label %ok
trap:
 call void @llvm.trap()
 unreachable
ok:
 %sn = extractvalue {i64,i1} %c, 0
 %done = icmp eq i64 %q, 0
 br i1 %done, label %exit, label %head
exit:
 %x = phi i64 [-1,%entry], [%sn,%ok]
 ret i64 %x
}
