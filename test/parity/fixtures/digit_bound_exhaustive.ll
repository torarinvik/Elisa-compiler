declare { i8, i1 } @llvm.sadd.with.overflow.i8(i8, i8)
define i32 @sum2(i32 %arg) {
entry:
 %start = trunc i32 %arg to i8
 br label %head
head:
 %n = phi i8 [ %start, %entry ], [ %div, %latch ]
 %t = phi i8 [ 0, %entry ], [ %value, %latch ]
 %more = icmp sgt i8 %n, 0
 br i1 %more, label %body, label %exit
body:
 %rem = srem i8 %n, 2
 %checked = call { i8, i1 } @llvm.sadd.with.overflow.i8(i8 %t, i8 %rem)
 %value = extractvalue { i8, i1 } %checked, 0
 %overflow = extractvalue { i8, i1 } %checked, 1
 br i1 %overflow, label %overflowed, label %latch
latch:
 %div = sdiv i8 %n, 2
 br label %head
exit:
 %out = sext i8 %t to i32
 ret i32 %out
overflowed:
 ret i32 -999
}
define i32 @sum3(i32 %arg) {
entry:
 %start = trunc i32 %arg to i8
 br label %head
head:
 %n = phi i8 [ %start, %entry ], [ %div, %latch ]
 %t = phi i8 [ 0, %entry ], [ %value, %latch ]
 %more = icmp sgt i8 %n, 0
 br i1 %more, label %body, label %exit
body:
 %rem = srem i8 %n, 3
 %checked = call { i8, i1 } @llvm.sadd.with.overflow.i8(i8 %t, i8 %rem)
 %value = extractvalue { i8, i1 } %checked, 0
 %overflow = extractvalue { i8, i1 } %checked, 1
 br i1 %overflow, label %overflowed, label %latch
latch:
 %div = sdiv i8 %n, 3
 br label %head
exit:
 %out = sext i8 %t to i32
 ret i32 %out
overflowed:
 ret i32 -999
}
define i32 @sum4(i32 %arg) {
entry:
 %start = trunc i32 %arg to i8
 br label %head
head:
 %n = phi i8 [ %start, %entry ], [ %div, %latch ]
 %t = phi i8 [ 0, %entry ], [ %value, %latch ]
 %more = icmp sgt i8 %n, 0
 br i1 %more, label %body, label %exit
body:
 %rem = srem i8 %n, 4
 %checked = call { i8, i1 } @llvm.sadd.with.overflow.i8(i8 %t, i8 %rem)
 %value = extractvalue { i8, i1 } %checked, 0
 %overflow = extractvalue { i8, i1 } %checked, 1
 br i1 %overflow, label %overflowed, label %latch
latch:
 %div = sdiv i8 %n, 4
 br label %head
exit:
 %out = sext i8 %t to i32
 ret i32 %out
overflowed:
 ret i32 -999
}
define i32 @sum5(i32 %arg) {
entry:
 %start = trunc i32 %arg to i8
 br label %head
head:
 %n = phi i8 [ %start, %entry ], [ %div, %latch ]
 %t = phi i8 [ 0, %entry ], [ %value, %latch ]
 %more = icmp sgt i8 %n, 0
 br i1 %more, label %body, label %exit
body:
 %rem = srem i8 %n, 5
 %checked = call { i8, i1 } @llvm.sadd.with.overflow.i8(i8 %t, i8 %rem)
 %value = extractvalue { i8, i1 } %checked, 0
 %overflow = extractvalue { i8, i1 } %checked, 1
 br i1 %overflow, label %overflowed, label %latch
latch:
 %div = sdiv i8 %n, 5
 br label %head
exit:
 %out = sext i8 %t to i32
 ret i32 %out
overflowed:
 ret i32 -999
}
define i32 @sum6(i32 %arg) {
entry:
 %start = trunc i32 %arg to i8
 br label %head
head:
 %n = phi i8 [ %start, %entry ], [ %div, %latch ]
 %t = phi i8 [ 0, %entry ], [ %value, %latch ]
 %more = icmp sgt i8 %n, 0
 br i1 %more, label %body, label %exit
body:
 %rem = srem i8 %n, 6
 %checked = call { i8, i1 } @llvm.sadd.with.overflow.i8(i8 %t, i8 %rem)
 %value = extractvalue { i8, i1 } %checked, 0
 %overflow = extractvalue { i8, i1 } %checked, 1
 br i1 %overflow, label %overflowed, label %latch
latch:
 %div = sdiv i8 %n, 6
 br label %head
exit:
 %out = sext i8 %t to i32
 ret i32 %out
overflowed:
 ret i32 -999
}
define i32 @sum7(i32 %arg) {
entry:
 %start = trunc i32 %arg to i8
 br label %head
head:
 %n = phi i8 [ %start, %entry ], [ %div, %latch ]
 %t = phi i8 [ 0, %entry ], [ %value, %latch ]
 %more = icmp sgt i8 %n, 0
 br i1 %more, label %body, label %exit
body:
 %rem = srem i8 %n, 7
 %checked = call { i8, i1 } @llvm.sadd.with.overflow.i8(i8 %t, i8 %rem)
 %value = extractvalue { i8, i1 } %checked, 0
 %overflow = extractvalue { i8, i1 } %checked, 1
 br i1 %overflow, label %overflowed, label %latch
latch:
 %div = sdiv i8 %n, 7
 br label %head
exit:
 %out = sext i8 %t to i32
 ret i32 %out
overflowed:
 ret i32 -999
}
define i32 @sum8(i32 %arg) {
entry:
 %start = trunc i32 %arg to i8
 br label %head
head:
 %n = phi i8 [ %start, %entry ], [ %div, %latch ]
 %t = phi i8 [ 0, %entry ], [ %value, %latch ]
 %more = icmp sgt i8 %n, 0
 br i1 %more, label %body, label %exit
body:
 %rem = srem i8 %n, 8
 %checked = call { i8, i1 } @llvm.sadd.with.overflow.i8(i8 %t, i8 %rem)
 %value = extractvalue { i8, i1 } %checked, 0
 %overflow = extractvalue { i8, i1 } %checked, 1
 br i1 %overflow, label %overflowed, label %latch
latch:
 %div = sdiv i8 %n, 8
 br label %head
exit:
 %out = sext i8 %t to i32
 ret i32 %out
overflowed:
 ret i32 -999
}
define i32 @sum9(i32 %arg) {
entry:
 %start = trunc i32 %arg to i8
 br label %head
head:
 %n = phi i8 [ %start, %entry ], [ %div, %latch ]
 %t = phi i8 [ 0, %entry ], [ %value, %latch ]
 %more = icmp sgt i8 %n, 0
 br i1 %more, label %body, label %exit
body:
 %rem = srem i8 %n, 9
 %checked = call { i8, i1 } @llvm.sadd.with.overflow.i8(i8 %t, i8 %rem)
 %value = extractvalue { i8, i1 } %checked, 0
 %overflow = extractvalue { i8, i1 } %checked, 1
 br i1 %overflow, label %overflowed, label %latch
latch:
 %div = sdiv i8 %n, 9
 br label %head
exit:
 %out = sext i8 %t to i32
 ret i32 %out
overflowed:
 ret i32 -999
}
define i32 @sum10(i32 %arg) {
entry:
 %start = trunc i32 %arg to i8
 br label %head
head:
 %n = phi i8 [ %start, %entry ], [ %div, %latch ]
 %t = phi i8 [ 0, %entry ], [ %value, %latch ]
 %more = icmp sgt i8 %n, 0
 br i1 %more, label %body, label %exit
body:
 %rem = srem i8 %n, 10
 %checked = call { i8, i1 } @llvm.sadd.with.overflow.i8(i8 %t, i8 %rem)
 %value = extractvalue { i8, i1 } %checked, 0
 %overflow = extractvalue { i8, i1 } %checked, 1
 br i1 %overflow, label %overflowed, label %latch
latch:
 %div = sdiv i8 %n, 10
 br label %head
exit:
 %out = sext i8 %t to i32
 ret i32 %out
overflowed:
 ret i32 -999
}
define i32 @sum11(i32 %arg) {
entry:
 %start = trunc i32 %arg to i8
 br label %head
head:
 %n = phi i8 [ %start, %entry ], [ %div, %latch ]
 %t = phi i8 [ 0, %entry ], [ %value, %latch ]
 %more = icmp sgt i8 %n, 0
 br i1 %more, label %body, label %exit
body:
 %rem = srem i8 %n, 11
 %checked = call { i8, i1 } @llvm.sadd.with.overflow.i8(i8 %t, i8 %rem)
 %value = extractvalue { i8, i1 } %checked, 0
 %overflow = extractvalue { i8, i1 } %checked, 1
 br i1 %overflow, label %overflowed, label %latch
latch:
 %div = sdiv i8 %n, 11
 br label %head
exit:
 %out = sext i8 %t to i32
 ret i32 %out
overflowed:
 ret i32 -999
}
define i32 @sum12(i32 %arg) {
entry:
 %start = trunc i32 %arg to i8
 br label %head
head:
 %n = phi i8 [ %start, %entry ], [ %div, %latch ]
 %t = phi i8 [ 0, %entry ], [ %value, %latch ]
 %more = icmp sgt i8 %n, 0
 br i1 %more, label %body, label %exit
body:
 %rem = srem i8 %n, 12
 %checked = call { i8, i1 } @llvm.sadd.with.overflow.i8(i8 %t, i8 %rem)
 %value = extractvalue { i8, i1 } %checked, 0
 %overflow = extractvalue { i8, i1 } %checked, 1
 br i1 %overflow, label %overflowed, label %latch
latch:
 %div = sdiv i8 %n, 12
 br label %head
exit:
 %out = sext i8 %t to i32
 ret i32 %out
overflowed:
 ret i32 -999
}
define i32 @sum13(i32 %arg) {
entry:
 %start = trunc i32 %arg to i8
 br label %head
head:
 %n = phi i8 [ %start, %entry ], [ %div, %latch ]
 %t = phi i8 [ 0, %entry ], [ %value, %latch ]
 %more = icmp sgt i8 %n, 0
 br i1 %more, label %body, label %exit
body:
 %rem = srem i8 %n, 13
 %checked = call { i8, i1 } @llvm.sadd.with.overflow.i8(i8 %t, i8 %rem)
 %value = extractvalue { i8, i1 } %checked, 0
 %overflow = extractvalue { i8, i1 } %checked, 1
 br i1 %overflow, label %overflowed, label %latch
latch:
 %div = sdiv i8 %n, 13
 br label %head
exit:
 %out = sext i8 %t to i32
 ret i32 %out
overflowed:
 ret i32 -999
}
define i32 @sum14(i32 %arg) {
entry:
 %start = trunc i32 %arg to i8
 br label %head
head:
 %n = phi i8 [ %start, %entry ], [ %div, %latch ]
 %t = phi i8 [ 0, %entry ], [ %value, %latch ]
 %more = icmp sgt i8 %n, 0
 br i1 %more, label %body, label %exit
body:
 %rem = srem i8 %n, 14
 %checked = call { i8, i1 } @llvm.sadd.with.overflow.i8(i8 %t, i8 %rem)
 %value = extractvalue { i8, i1 } %checked, 0
 %overflow = extractvalue { i8, i1 } %checked, 1
 br i1 %overflow, label %overflowed, label %latch
latch:
 %div = sdiv i8 %n, 14
 br label %head
exit:
 %out = sext i8 %t to i32
 ret i32 %out
overflowed:
 ret i32 -999
}
define i32 @sum15(i32 %arg) {
entry:
 %start = trunc i32 %arg to i8
 br label %head
head:
 %n = phi i8 [ %start, %entry ], [ %div, %latch ]
 %t = phi i8 [ 0, %entry ], [ %value, %latch ]
 %more = icmp sgt i8 %n, 0
 br i1 %more, label %body, label %exit
body:
 %rem = srem i8 %n, 15
 %checked = call { i8, i1 } @llvm.sadd.with.overflow.i8(i8 %t, i8 %rem)
 %value = extractvalue { i8, i1 } %checked, 0
 %overflow = extractvalue { i8, i1 } %checked, 1
 br i1 %overflow, label %overflowed, label %latch
latch:
 %div = sdiv i8 %n, 15
 br label %head
exit:
 %out = sext i8 %t to i32
 ret i32 %out
overflowed:
 ret i32 -999
}
define i32 @sum16(i32 %arg) {
entry:
 %start = trunc i32 %arg to i8
 br label %head
head:
 %n = phi i8 [ %start, %entry ], [ %div, %latch ]
 %t = phi i8 [ 0, %entry ], [ %value, %latch ]
 %more = icmp sgt i8 %n, 0
 br i1 %more, label %body, label %exit
body:
 %rem = srem i8 %n, 16
 %checked = call { i8, i1 } @llvm.sadd.with.overflow.i8(i8 %t, i8 %rem)
 %value = extractvalue { i8, i1 } %checked, 0
 %overflow = extractvalue { i8, i1 } %checked, 1
 br i1 %overflow, label %overflowed, label %latch
latch:
 %div = sdiv i8 %n, 16
 br label %head
exit:
 %out = sext i8 %t to i32
 ret i32 %out
overflowed:
 ret i32 -999
}
define i32 @sum17(i32 %arg) {
entry:
 %start = trunc i32 %arg to i8
 br label %head
head:
 %n = phi i8 [ %start, %entry ], [ %div, %latch ]
 %t = phi i8 [ 0, %entry ], [ %value, %latch ]
 %more = icmp sgt i8 %n, 0
 br i1 %more, label %body, label %exit
body:
 %rem = srem i8 %n, 17
 %checked = call { i8, i1 } @llvm.sadd.with.overflow.i8(i8 %t, i8 %rem)
 %value = extractvalue { i8, i1 } %checked, 0
 %overflow = extractvalue { i8, i1 } %checked, 1
 br i1 %overflow, label %overflowed, label %latch
latch:
 %div = sdiv i8 %n, 17
 br label %head
exit:
 %out = sext i8 %t to i32
 ret i32 %out
overflowed:
 ret i32 -999
}
define i32 @sum18(i32 %arg) {
entry:
 %start = trunc i32 %arg to i8
 br label %head
head:
 %n = phi i8 [ %start, %entry ], [ %div, %latch ]
 %t = phi i8 [ 0, %entry ], [ %value, %latch ]
 %more = icmp sgt i8 %n, 0
 br i1 %more, label %body, label %exit
body:
 %rem = srem i8 %n, 18
 %checked = call { i8, i1 } @llvm.sadd.with.overflow.i8(i8 %t, i8 %rem)
 %value = extractvalue { i8, i1 } %checked, 0
 %overflow = extractvalue { i8, i1 } %checked, 1
 br i1 %overflow, label %overflowed, label %latch
latch:
 %div = sdiv i8 %n, 18
 br label %head
exit:
 %out = sext i8 %t to i32
 ret i32 %out
overflowed:
 ret i32 -999
}
define i32 @sum19(i32 %arg) {
entry:
 %start = trunc i32 %arg to i8
 br label %head
head:
 %n = phi i8 [ %start, %entry ], [ %div, %latch ]
 %t = phi i8 [ 0, %entry ], [ %value, %latch ]
 %more = icmp sgt i8 %n, 0
 br i1 %more, label %body, label %exit
body:
 %rem = srem i8 %n, 19
 %checked = call { i8, i1 } @llvm.sadd.with.overflow.i8(i8 %t, i8 %rem)
 %value = extractvalue { i8, i1 } %checked, 0
 %overflow = extractvalue { i8, i1 } %checked, 1
 br i1 %overflow, label %overflowed, label %latch
latch:
 %div = sdiv i8 %n, 19
 br label %head
exit:
 %out = sext i8 %t to i32
 ret i32 %out
overflowed:
 ret i32 -999
}
define i32 @sum20(i32 %arg) {
entry:
 %start = trunc i32 %arg to i8
 br label %head
head:
 %n = phi i8 [ %start, %entry ], [ %div, %latch ]
 %t = phi i8 [ 0, %entry ], [ %value, %latch ]
 %more = icmp sgt i8 %n, 0
 br i1 %more, label %body, label %exit
body:
 %rem = srem i8 %n, 20
 %checked = call { i8, i1 } @llvm.sadd.with.overflow.i8(i8 %t, i8 %rem)
 %value = extractvalue { i8, i1 } %checked, 0
 %overflow = extractvalue { i8, i1 } %checked, 1
 br i1 %overflow, label %overflowed, label %latch
latch:
 %div = sdiv i8 %n, 20
 br label %head
exit:
 %out = sext i8 %t to i32
 ret i32 %out
overflowed:
 ret i32 -999
}
define i32 @bad_initial(i8 %start, i8 %init) {
entry:
 br label %head
head:
 %n = phi i8 [ %start, %entry ], [ %div, %latch ]
 %t = phi i8 [ %init, %entry ], [ %value, %latch ]
 %more = icmp sgt i8 %n, 0
 br i1 %more, label %body, label %exit
body:
 %rem = srem i8 %n, 2
 %checked = call { i8, i1 } @llvm.sadd.with.overflow.i8(i8 %t, i8 %rem)
 %value = extractvalue { i8, i1 } %checked, 0
 %overflow = extractvalue { i8, i1 } %checked, 1
 br i1 %overflow, label %overflowed, label %latch
latch:
 %div = sdiv i8 %n, 2
 br label %head
exit:
 %out = sext i8 %t to i32
 ret i32 %out
overflowed:
 ret i32 -999
}

define i32 @bad_guard(i32 %arg) {
entry:
 %start = trunc i32 %arg to i8
 br label %head
head:
 %n = phi i8 [ %start, %entry ], [ %div, %latch ]
 %t = phi i8 [ 0, %entry ], [ %value, %latch ]
 %more = icmp ne i8 %n, 0
 br i1 %more, label %body, label %exit
body:
 %rem = srem i8 %n, 2
 %checked = call { i8, i1 } @llvm.sadd.with.overflow.i8(i8 %t, i8 %rem)
 %value = extractvalue { i8, i1 } %checked, 0
 %overflow = extractvalue { i8, i1 } %checked, 1
 br i1 %overflow, label %overflowed, label %latch
latch:
 %div = sdiv i8 %n, 2
 br label %head
exit:
 %out = sext i8 %t to i32
 ret i32 %out
overflowed:
 ret i32 -999
}
define i32 @bad_divisor(i32 %arg) {
entry:
 %start = trunc i32 %arg to i8
 br label %head
head:
 %n = phi i8 [ %start, %entry ], [ %div, %latch ]
 %t = phi i8 [ 0, %entry ], [ %value, %latch ]
 %more = icmp sgt i8 %n, 0
 br i1 %more, label %body, label %exit
body:
 %rem = srem i8 %n, 2
 %checked = call { i8, i1 } @llvm.sadd.with.overflow.i8(i8 %t, i8 %rem)
 %value = extractvalue { i8, i1 } %checked, 0
 %overflow = extractvalue { i8, i1 } %checked, 1
 br i1 %overflow, label %overflowed, label %latch
latch:
 %div = sdiv i8 %n, 3
 br label %head
exit:
 %out = sext i8 %t to i32
 ret i32 %out
overflowed:
 ret i32 -999
}
