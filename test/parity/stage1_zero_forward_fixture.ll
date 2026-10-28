target datalayout = "e-m:o-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-n32:64-S128-Fn32"
target triple = "arm64-apple-darwin"
declare void @llvm.memset.p0.i64(ptr, i8, i64, i1 immarg)
declare void @capture(ptr)

define i64 @covered() {
  %a = alloca [16 x i64], align 8
  %p = getelementptr inbounds i8, ptr %a, i64 24
  call void @llvm.memset.p0.i64(ptr %p, i8 0, i64 104, i1 false)
  store i64 9, ptr %a, align 8
  %v = load i64, ptr %p, align 8
  ret i64 %v
}
define i64 @nonzero() {
  %a = alloca [16 x i64], align 8
  %p = getelementptr inbounds i8, ptr %a, i64 24
  call void @llvm.memset.p0.i64(ptr %p, i8 1, i64 104, i1 false)
  %v = load i64, ptr %p, align 8
  ret i64 %v
}
define i64 @overlap() {
  %a = alloca [16 x i64], align 8
  %p = getelementptr inbounds i8, ptr %a, i64 24
  call void @llvm.memset.p0.i64(ptr %p, i8 0, i64 104, i1 false)
  store i64 9, ptr %p, align 8
  %v = load i64, ptr %p, align 8
  ret i64 %v
}
define i64 @partial() {
  %a = alloca [16 x i64], align 8
  %p = getelementptr inbounds i8, ptr %a, i64 24
  call void @llvm.memset.p0.i64(ptr %p, i8 0, i64 7, i1 false)
  %v = load i64, ptr %p, align 8
  ret i64 %v
}
define i64 @escape() {
  %a = alloca [16 x i64], align 8
  %p = getelementptr inbounds i8, ptr %a, i64 24
  call void @capture(ptr %a)
  call void @llvm.memset.p0.i64(ptr %p, i8 0, i64 104, i1 false)
  %v = load i64, ptr %p, align 8
  ret i64 %v
}
define i64 @volatile() {
  %a = alloca [16 x i64], align 8
  %p = getelementptr inbounds i8, ptr %a, i64 24
  call void @llvm.memset.p0.i64(ptr %p, i8 0, i64 104, i1 false)
  %v = load volatile i64, ptr %p, align 8
  ret i64 %v
}
define i64 @unaligned() {
  %a = alloca [16 x i64], align 8
  %p = getelementptr inbounds i8, ptr %a, i64 25
  call void @llvm.memset.p0.i64(ptr %p, i8 0, i64 8, i1 false)
  %v = load i64, ptr %p, align 8
  ret i64 %v
}
define i64 @intervening_call() {
  %a = alloca [16 x i64], align 8
  %p = getelementptr inbounds i8, ptr %a, i64 24
  call void @llvm.memset.p0.i64(ptr %p, i8 0, i64 104, i1 false)
  call void @capture(ptr null)
  %v = load i64, ptr %p, align 8
  ret i64 %v
}
define i64 @dynamic_gep(i64 %n) {
  %a = alloca [16 x i64], align 8
  %p = getelementptr inbounds i8, ptr %a, i64 %n
  call void @llvm.memset.p0.i64(ptr %p, i8 0, i64 8, i1 false)
  %v = load i64, ptr %p, align 8
  ret i64 %v
}
define i64 @out_of_range() {
  %a = alloca [16 x i64], align 8
  %p = getelementptr inbounds i8, ptr %a, i64 128
  call void @llvm.memset.p0.i64(ptr %p, i8 0, i64 8, i1 false)
  %v = load i64, ptr %p, align 8
  ret i64 %v
}

define i8 @covered8() {
  %a = alloca [16 x i64], align 8
  %p = getelementptr inbounds i8, ptr %a, i64 24
  call void @llvm.memset.p0.i64(ptr %p, i8 0, i64 104, i1 false)
  %v = load i8, ptr %p, align 1
  ret i8 %v
}

define i16 @covered16() {
  %a = alloca [16 x i64], align 8
  %p = getelementptr inbounds i8, ptr %a, i64 24
  call void @llvm.memset.p0.i64(ptr %p, i8 0, i64 104, i1 false)
  %v = load i16, ptr %p, align 1
  ret i16 %v
}

define i32 @covered32() {
  %a = alloca [16 x i64], align 8
  %p = getelementptr inbounds i8, ptr %a, i64 24
  call void @llvm.memset.p0.i64(ptr %p, i8 0, i64 104, i1 false)
  %v = load i32, ptr %p, align 1
  ret i32 %v
}

define i64 @atomic_load() {
  %a = alloca [16 x i64], align 8
  %p = getelementptr inbounds i8, ptr %a, i64 24
  call void @llvm.memset.p0.i64(ptr %p, i8 0, i64 104, i1 false)
  %v = load atomic i64, ptr %p monotonic, align 8
  ret i64 %v
}
define i64 @atomic_store() {
  %a = alloca [16 x i64], align 8
  %p = getelementptr inbounds i8, ptr %a, i64 24
  call void @llvm.memset.p0.i64(ptr %p, i8 0, i64 104, i1 false)
  store atomic i64 1, ptr %a monotonic, align 8
  %v = load i64, ptr %p, align 8
  ret i64 %v
}
define i64 @cast_escape() {
  %a = alloca [16 x i64], align 8
  %p = getelementptr inbounds i8, ptr %a, i64 24
  %i = ptrtoint ptr %a to i64
  call void @llvm.memset.p0.i64(ptr %p, i8 0, i64 104, i1 false)
  %v = load i64, ptr %p, align 8
  ret i64 %v
}
define i64 @volatile_memset() {
  %a = alloca [16 x i64], align 8
  %p = getelementptr inbounds i8, ptr %a, i64 24
  call void @llvm.memset.p0.i64(ptr %p, i8 0, i64 104, i1 true)
  %v = load i64, ptr %p, align 8
  ret i64 %v
}
define i64 @last_memset_nonzero() {
  %a = alloca [16 x i64], align 8
  %p = getelementptr inbounds i8, ptr %a, i64 24
  call void @llvm.memset.p0.i64(ptr %p, i8 0, i64 104, i1 false)
  call void @llvm.memset.p0.i64(ptr %p, i8 1, i64 104, i1 false)
  %v = load i64, ptr %p, align 8
  ret i64 %v
}
define i64 @range_metadata() {
  %a = alloca [16 x i64], align 8
  %p = getelementptr inbounds i8, ptr %a, i64 24
  call void @llvm.memset.p0.i64(ptr %p, i8 0, i64 104, i1 false)
  %v = load i64, ptr %p, align 8, !range !0
  ret i64 %v
}

define i64 @zero_length() {
  %a = alloca [16 x i64], align 8
  %p = getelementptr inbounds i8, ptr %a, i64 24
  call void @llvm.memset.p0.i64(ptr %p, i8 0, i64 0, i1 false)
  %v = load i64, ptr %p, align 8
  ret i64 %v
}
define i64 @oversized_length() {
  %a = alloca [16 x i64], align 8
  %p = getelementptr inbounds i8, ptr %a, i64 24
  call void @llvm.memset.p0.i64(ptr %p, i8 0, i64 105, i1 false)
  %v = load i64, ptr %p, align 8
  ret i64 %v
}
define i64 @negative_gep() {
  %a = alloca [16 x i64], align 8
  %p = getelementptr inbounds i8, ptr %a, i64 -1
  call void @llvm.memset.p0.i64(ptr %p, i8 0, i64 8, i1 false)
  %v = load i64, ptr %p, align 1
  ret i64 %v
}
define i64 @non_inbounds_gep() {
  %a = alloca [16 x i64], align 8
  %p = getelementptr i8, ptr %a, i64 24
  call void @llvm.memset.p0.i64(ptr %p, i8 0, i64 104, i1 false)
  %v = load i64, ptr %p, align 8
  ret i64 %v
}
define i64 @cross_block() {
entry:
  %a = alloca [16 x i64], align 8
  %p = getelementptr inbounds i8, ptr %a, i64 24
  call void @llvm.memset.p0.i64(ptr %p, i8 0, i64 104, i1 false)
  br label %next
next:
  %v = load i64, ptr %p, align 8
  ret i64 %v
}
define i64 @pointer_escape_store(ptr %external) {
  %a = alloca [16 x i64], align 8
  %p = getelementptr inbounds i8, ptr %a, i64 24
  store ptr %a, ptr %external, align 8
  call void @llvm.memset.p0.i64(ptr %p, i8 0, i64 104, i1 false)
  %v = load i64, ptr %p, align 8
  ret i64 %v
}
define i64 @fence_barrier() {
  %a = alloca [16 x i64], align 8
  %p = getelementptr inbounds i8, ptr %a, i64 24
  call void @llvm.memset.p0.i64(ptr %p, i8 0, i64 104, i1 false)
  fence acquire
  %v = load i64, ptr %p, align 8
  ret i64 %v
}
!0 = !{i64 0, i64 1}

define i64 @debug_location() !dbg !2 {
  %a = alloca [16 x i64], align 8
  %p = getelementptr inbounds i8, ptr %a, i64 24
  call void @llvm.memset.p0.i64(ptr %p, i8 0, i64 104, i1 false)
  %v = load i64, ptr %p, align 8, !dbg !7
  ret i64 %v
}
!llvm.dbg.cu = !{!1}
!llvm.module.flags = !{!8}
!1 = distinct !DICompileUnit(language: DW_LANG_C, file: !3, producer: "test", isOptimized: false, runtimeVersion: 0, emissionKind: FullDebug)
!2 = distinct !DISubprogram(name: "debug_location", scope: !3, file: !3, line: 1, type: !4, scopeLine: 1, spFlags: DISPFlagDefinition, unit: !1)
!3 = !DIFile(filename: "test.c", directory: "/")
!4 = !DISubroutineType(types: !5)
!5 = !{null}
!7 = !DILocation(line: 1, column: 1, scope: !2)
!8 = !{i32 2, !"Debug Info Version", i32 3}
