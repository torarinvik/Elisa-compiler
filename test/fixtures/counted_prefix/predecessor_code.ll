target datalayout = "e-m:o-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-n32:64-S128-Fn32"
target triple = "arm64-apple-darwin27.2.0"

%DynArrayView = type { ptr, i64 }

; Function Attrs: nounwind
define hidden void @predecessor_code(%DynArrayView %0, i64 %1, i64 %2, %DynArrayView %3) #0 {
  %5 = alloca [16 x i64], align 8
  %6 = alloca %DynArrayView, align 8
  store %DynArrayView %3, ptr %6, align 8
  call void @llvm.memset.p0.i64(ptr align 8 %5, i8 0, i64 128, i1 false)
  br label %7

7:                                                ; preds = %13, %4
  %8 = phi i64 [ 0, %4 ], [ %15, %13 ]
  %9 = icmp ult i64 %8, 16
  br i1 %9, label %10, label %12

10:                                               ; preds = %7
  %11 = icmp ult i64 %8, 16
  br i1 %11, label %13, label %16

12:                                               ; preds = %7
  br label %17

13:                                               ; preds = %10
  %14 = getelementptr [16 x i64], ptr %5, i64 0, i64 %8
  store i64 -1, ptr %14, align 8
  %15 = add i64 %8, 1
  br label %7

16:                                               ; preds = %10
  call void @llvm.trap()
  unreachable

17:                                               ; preds = %59, %12
  %18 = phi i64 [ 0, %12 ], [ %61, %59 ]
  %19 = icmp ult i64 %18, %2
  br i1 %19, label %20, label %25

20:                                               ; preds = %17
  %21 = extractvalue %DynArrayView %0, 0
  %22 = add i64 %1, %18
  %23 = extractvalue %DynArrayView %0, 1
  %24 = icmp ult i64 %22, %23
  br i1 %24, label %26, label %34

25:                                               ; preds = %17
  ret void

26:                                               ; preds = %20
  %27 = getelementptr i64, ptr %21, i64 %22
  %28 = load i64, ptr %27, align 8
  %29 = getelementptr inbounds nuw %DynArrayView, ptr %6, i32 0, i32 0
  %30 = load ptr, ptr %29, align 8
  %31 = getelementptr inbounds nuw %DynArrayView, ptr %6, i32 0, i32 1
  %32 = load i64, ptr %31, align 8
  %33 = icmp ult i64 %18, %32
  br i1 %33, label %35, label %38

34:                                               ; preds = %20
  call void @llvm.trap()
  unreachable

35:                                               ; preds = %26
  %36 = getelementptr i64, ptr %30, i64 %18
  %37 = icmp ult i64 %28, 16
  br i1 %37, label %39, label %43

38:                                               ; preds = %26
  call void @llvm.trap()
  unreachable

39:                                               ; preds = %35
  %40 = getelementptr [16 x i64], ptr %5, i64 0, i64 %28
  %41 = load i64, ptr %40, align 8
  %42 = icmp slt i64 %41, 0
  br i1 %42, label %44, label %45

43:                                               ; preds = %35
  call void @llvm.trap()
  unreachable

44:                                               ; preds = %39
  br label %47

45:                                               ; preds = %39
  %46 = icmp ult i64 %28, 16
  br i1 %46, label %50, label %56

47:                                               ; preds = %58, %44
  %48 = phi i64 [ 0, %44 ], [ %54, %58 ]
  store i64 %48, ptr %36, align 8
  %49 = icmp ult i64 %28, 16
  br i1 %49, label %59, label %62

50:                                               ; preds = %45
  %51 = getelementptr [16 x i64], ptr %5, i64 0, i64 %28
  %52 = load i64, ptr %51, align 8
  %53 = call { i64, i1 } @llvm.ssub.with.overflow.i64(i64 %18, i64 %52)
  %54 = extractvalue { i64, i1 } %53, 0
  %55 = extractvalue { i64, i1 } %53, 1
  br i1 %55, label %57, label %58

56:                                               ; preds = %45
  call void @llvm.trap()
  unreachable

57:                                               ; preds = %50
  call void @llvm.trap()
  unreachable

58:                                               ; preds = %50
  br label %47

59:                                               ; preds = %47
  %60 = getelementptr [16 x i64], ptr %5, i64 0, i64 %28
  store i64 %18, ptr %60, align 8
  %61 = add i64 %18, 1
  br label %17

62:                                               ; preds = %47
  call void @llvm.trap()
  unreachable
}

; Function Attrs: cold noreturn nounwind memory(inaccessiblemem: write)
declare void @llvm.trap() #1

; Function Attrs: nocallback nocreateundeforpoison nofree nosync nounwind speculatable willreturn memory(none)
declare { i64, i1 } @llvm.ssub.with.overflow.i64(i64, i64) #2

; Function Attrs: nocallback nofree nosync nounwind willreturn memory(argmem: write)
declare void @llvm.memset.p0.i64(ptr writeonly captures(none), i8, i64, i1 immarg) #3

attributes #0 = { nounwind }
attributes #1 = { cold noreturn nounwind memory(inaccessiblemem: write) }
attributes #2 = { nocallback nocreateundeforpoison nofree nosync nounwind speculatable willreturn memory(none) }
attributes #3 = { nocallback nofree nosync nounwind willreturn memory(argmem: write) }
