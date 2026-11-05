target triple = "aarch64-unknown-linux-gnu"
declare {i64,i1} @llvm.sadd.with.overflow.i64(i64,i64)
define i64 @header_counter() {
entry:
 br label %head
head:
 %n = phi i64 [1,%entry], [%quotient,%head]
 %counter = phi i64 [9223372036854775806,%entry], [%value,%head]
 %pair = call {i64,i1} @llvm.sadd.with.overflow.i64(i64 %counter,i64 1)
 %value = extractvalue {i64,i1} %pair,0
 %overflow = extractvalue {i64,i1} %pair,1
 %quotient = udiv i64 %n,2
 %done = icmp eq i64 %n,0
 br i1 %done,label %exit,label %head
exit:
 %result = zext i1 %overflow to i64
 ret i64 %result
}
