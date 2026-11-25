; Generic fixtures for a bounded monotone accumulator proof.
; Inputs and buffers are defined by the C harness. No benchmark-specific names
; or optimization hints are required by the candidate.

declare { i8, i1 } @llvm.sadd.with.overflow.i8(i8, i8) #0
declare void @llvm.trap() #1
declare i8 @llvm.smin.i8(i8, i8) #0

define i8 @safe_checked(i8 noundef %n, ptr noundef %data) {
entry:
  %low = icmp ult i8 %n, 1
  %high = icmp ugt i8 %n, 8
  %bad = or i1 %low, %high
  br i1 %bad, label %invalid, label %loop

invalid:
  ret i8 -1

loop:
  %i = phi i8 [ 0, %entry ], [ %next, %latch ]
  %sum = phi i8 [ 0, %entry ], [ %sum.next, %latch ]
  %done = icmp eq i8 %i, %n
  br i1 %done, label %exit, label %body

body:
  %ptr = getelementptr i8, ptr %data, i8 %i
  %step = load i8, ptr %ptr, align 1
  %step.bad = icmp ugt i8 %step, 3
  br i1 %step.bad, label %invalid, label %check

check:
  %pair = call { i8, i1 } @llvm.sadd.with.overflow.i8(i8 %sum, i8 %step)
  %sum.next = extractvalue { i8, i1 } %pair, 0
  %overflow = extractvalue { i8, i1 } %pair, 1
  br i1 %overflow, label %trap, label %latch

latch:
  %next = add i8 %i, 1
  br label %loop

trap:
  call void @llvm.trap()
  unreachable

exit:
  ret i8 %sum
}

define i8 @safe_plain(i8 noundef %n, ptr noundef %data) {
entry:
  %low = icmp ult i8 %n, 1
  %high = icmp ugt i8 %n, 8
  %bad = or i1 %low, %high
  br i1 %bad, label %invalid, label %loop

invalid:
  ret i8 -1

loop:
  %i = phi i8 [ 0, %entry ], [ %next, %latch ]
  %sum = phi i8 [ 0, %entry ], [ %sum.next, %latch ]
  %done = icmp eq i8 %i, %n
  br i1 %done, label %exit, label %body

body:
  %ptr = getelementptr i8, ptr %data, i8 %i
  %step = load i8, ptr %ptr, align 1
  %step.bad = icmp ugt i8 %step, 3
  br i1 %step.bad, label %invalid, label %add

add:
  %sum.next = add i8 %sum, %step
  br label %latch

latch:
  %next = add i8 %i, 1
  br label %loop

exit:
  ret i8 %sum
}

; At n=8, eight updates of 33 exceed signed i8 and must still trap.
define i8 @unsafe_m33(i8 noundef %n, ptr noundef %data) {
entry:
  %low = icmp ult i8 %n, 1
  %high = icmp ugt i8 %n, 8
  %bad = or i1 %low, %high
  br i1 %bad, label %invalid, label %loop

invalid:
  ret i8 -1

loop:
  %i = phi i8 [ 0, %entry ], [ %next, %latch ]
  %sum = phi i8 [ 0, %entry ], [ %sum.next, %latch ]
  %done = icmp eq i8 %i, %n
  br i1 %done, label %exit, label %body

body:
  %ptr = getelementptr i8, ptr %data, i8 %i
  %step = load i8, ptr %ptr, align 1
  %step.bad = icmp ugt i8 %step, 33
  br i1 %step.bad, label %invalid, label %check

check:
  %pair = call { i8, i1 } @llvm.sadd.with.overflow.i8(i8 %sum, i8 %step)
  %sum.next = extractvalue { i8, i1 } %pair, 0
  %overflow = extractvalue { i8, i1 } %pair, 1
  br i1 %overflow, label %trap, label %latch

latch:
  %next = add i8 %i, 1
  br label %loop

trap:
  call void @llvm.trap()
  unreachable

exit:
  ret i8 %sum
}

; A nonzero seed prevents the zero-seed accumulator proof. Zero steps are safe;
; positive steps may overflow signed i8 and must retain the trap.
define i8 @nonzero_seed127(i8 noundef %n, ptr noundef %data) {
entry:
  %low = icmp ult i8 %n, 1
  %high = icmp ugt i8 %n, 8
  %bad = or i1 %low, %high
  br i1 %bad, label %invalid, label %loop

invalid:
  ret i8 -1

loop:
  %i = phi i8 [ 0, %entry ], [ %next, %latch ]
  %sum = phi i8 [ 127, %entry ], [ %sum.next, %latch ]
  %done = icmp eq i8 %i, %n
  br i1 %done, label %exit, label %body

body:
  %ptr = getelementptr i8, ptr %data, i8 %i
  %step = load i8, ptr %ptr, align 1
  %step.bad = icmp ugt i8 %step, 3
  br i1 %step.bad, label %invalid, label %check

check:
  %pair = call { i8, i1 } @llvm.sadd.with.overflow.i8(i8 %sum, i8 %step)
  %sum.next = extractvalue { i8, i1 } %pair, 0
  %overflow = extractvalue { i8, i1 } %pair, 1
  br i1 %overflow, label %trap, label %latch

latch:
  %next = add i8 %i, 1
  br label %loop

trap:
  call void @llvm.trap()
  unreachable

exit:
  ret i8 %sum
}

; The checked update happens before the equality exit test. n=3 therefore
; performs four updates (4*40), which must trap; n=0 performs one update.
define i8 @header_update_before_exit(i8 noundef %n, ptr noundef %unused) {
entry:
  %high = icmp ugt i8 %n, 3
  br i1 %high, label %invalid, label %loop

invalid:
  ret i8 -1

loop:
  %i = phi i8 [ 0, %entry ], [ %next, %continue ]
  %sum = phi i8 [ 0, %entry ], [ %sum.next, %continue ]
  %pair = call { i8, i1 } @llvm.sadd.with.overflow.i8(i8 %sum, i8 40)
  %sum.next = extractvalue { i8, i1 } %pair, 0
  %overflow = extractvalue { i8, i1 } %pair, 1
  br i1 %overflow, label %trap, label %after_update

after_update:
  %done = icmp eq i8 %i, %n
  br i1 %done, label %exit, label %continue

continue:
  %next = add i8 %i, 1
  br label %loop

trap:
  call void @llvm.trap()
  unreachable

exit:
  ret i8 %sum.next
}

; Same off-by-one case, with overflow observable as return value 1 rather than
; a trap. This control prevents treating the flag as unobservable.
define i8 @header_update_observable_flag(i8 noundef %n,
                                         ptr noundef %unused) {
entry:
  %high = icmp ugt i8 %n, 3
  br i1 %high, label %invalid, label %loop

invalid:
  ret i8 -1

loop:
  %i = phi i8 [ 0, %entry ], [ %next, %continue ]
  %sum = phi i8 [ 0, %entry ], [ %sum.next, %continue ]
  %pair = call { i8, i1 } @llvm.sadd.with.overflow.i8(i8 %sum, i8 40)
  %sum.next = extractvalue { i8, i1 } %pair, 0
  %overflow = extractvalue { i8, i1 } %pair, 1
  br i1 %overflow, label %overflow_result, label %after_update

after_update:
  %done = icmp eq i8 %i, %n
  br i1 %done, label %exit, label %continue

continue:
  %next = add i8 %i, 1
  br label %loop

overflow_result:
  ret i8 1

exit:
  ret i8 %sum.next
}

; The cap is a second recurrence whose nonnegative range is proved first.
define i8 @safe_clamped(i8 noundef %n, ptr noundef %data) {
entry:
  %valid = icmp ule i8 %n, 8
  br i1 %valid, label %guard, label %invalid

guard:
  %empty = icmp eq i8 %n, 0
  br i1 %empty, label %zero, label %loop

zero:
  ret i8 0

invalid:
  ret i8 -1

loop:
  %index = phi i8 [ 0, %guard ], [ %index.next, %continue ]
  %cap = phi i8 [ 0, %guard ], [ %cap.next, %continue ]
  %sum = phi i8 [ 0, %guard ], [ %clamped, %continue ]
  %address = getelementptr i8, ptr %data, i8 %index
  %raw = load i8, ptr %address
  %step = and i8 %raw, 3
  %pair = call { i8, i1 } @llvm.sadd.with.overflow.i8(i8 %sum, i8 %step)
  %value = extractvalue { i8, i1 } %pair, 0
  %overflow = extractvalue { i8, i1 } %pair, 1
  br i1 %overflow, label %trap, label %continue

continue:
  %clamped = call i8 @llvm.smin.i8(i8 %value, i8 %cap)
  %cap.next = add i8 %cap, 1
  %index.next = add nuw nsw i8 %index, 1
  %done = icmp eq i8 %index.next, %n
  br i1 %done, label %exit, label %loop

trap:
  call void @llvm.trap()
  unreachable

exit:
  ret i8 %clamped
}

attributes #0 = { nocallback nofree nosync nounwind speculatable willreturn memory(none) }
attributes #1 = { cold noreturn nounwind memory(inaccessiblemem: write) }
