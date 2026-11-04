target triple = "arm64-apple-darwin27.2.0"
declare {i64, i1} @llvm.sadd.with.overflow.i64(i64, i64)
declare void @llvm.trap()
define i64 @count_with_offset(i64 %n, i64 %offset) {
entry:
 %shift = add i64 %n, -100000000
 %invalid = icmp ult i64 %shift, -99999999
 %initial0 = insertvalue {i64,i1} poison, i64 %offset, 0
 %initial = insertvalue {i64,i1} %initial0, i1 false, 1
 br i1 %invalid, label %bad, label %head
head:
 %digits = phi i64 [%n, %entry], [%div, %body]
 %counter = phi {i64,i1} [%initial, %entry], [%checked, %body]
 %count = extractvalue {i64,i1} %counter, 0
 %done = icmp ult i64 %digits, 10
 br i1 %done, label %exit, label %body
body:
 %div = udiv i64 %digits, 10
 %checked = call {i64,i1} @llvm.sadd.with.overflow.i64(i64 %count, i64 1)
 %overflow = extractvalue {i64,i1} %checked, 1
 br i1 %overflow, label %trap, label %head
trap:
 call void @llvm.trap()
 unreachable
exit:
 ret i64 %count
bad:
 ret i64 -1
}
