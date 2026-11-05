target triple = "aarch64-unknown-linux-gnu"
declare {i64,i1} @llvm.sadd.with.overflow.i64(i64,i64)
declare {i64,i1} @llvm.smul.with.overflow.i64(i64,i64)
declare void @llvm.trap()
define i64 @scan_power(i64 noundef %n, i64 noundef %pos, i64 noundef %base_arg) {
entry:
 %shift = add i64 %n, -100000000
 %bad_n = icmp ult i64 %shift, -99999999
 %pos_shift = add i64 %pos, -1
 %bad_pos = icmp ugt i64 %pos_shift, 7
 %bad = or i1 %bad_n, %bad_pos
 %base = srem i64 %base_arg, 10
 br i1 %bad, label %invalid, label %outer
outer:
 %remaining = phi i64 [%n,%entry], [%quotient,%next]
 %position = phi i64 [%pos,%entry], [%decrement,%next]
 %sum = phi i64 [0,%entry], [%sum_next,%next]
 %done = icmp eq i64 %remaining, 0
 br i1 %done, label %exit, label %pre
pre:
 %quotient = udiv i64 %remaining, 10
 %positive = icmp sgt i64 %position, 0
 br i1 %positive, label %power, label %after_power
power:
 %exponent = phi i64 [0,%pre], [%increment,%latch]
 %value = phi i64 [1,%pre], [%low,%latch]
 %frozen_base = freeze i64 %base
 %low = mul i64 %value, %frozen_base
 %cheap = icmp ult i64 %frozen_base, 2
 br i1 %cheap, label %latch, label %slow
slow:
 %product = call {i64,i1} @llvm.smul.with.overflow.i64(i64 %value, i64 %frozen_base)
 %overflow = extractvalue {i64,i1} %product, 1
 br i1 %overflow, label %trap, label %latch
latch:
 %increment = add nuw nsw i64 %exponent, 1
 %power_done = icmp eq i64 %increment, %position
 br i1 %power_done, label %after_power, label %power
after_power:
 %power_result = phi i64 [1,%pre], [%low,%latch]
 %sum_next = add i64 %sum, %power_result
 br label %next
next:
 %pair = call {i64,i1} @llvm.sadd.with.overflow.i64(i64 %position, i64 -1)
 %decrement = extractvalue {i64,i1} %pair, 0
 %underflow = extractvalue {i64,i1} %pair, 1
 br i1 %underflow, label %trap, label %outer
trap:
 call void @llvm.trap()
 unreachable
exit:
 ret i64 %sum
invalid:
 ret i64 -777
}
