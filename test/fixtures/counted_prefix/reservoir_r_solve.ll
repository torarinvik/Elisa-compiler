target datalayout = "e-m:o-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-n32:64-S128-Fn32"
target triple = "arm64-apple-darwin27.2.0"

; Function Attrs: nounwind
define hidden i64 @reservoir_r_solve(ptr %0, ptr %1) #0 {
  %3 = alloca [64 x i64], align 8
  %4 = getelementptr i64, ptr %0, i64 0
  %5 = load i64, ptr %4, align 8
  %6 = getelementptr i64, ptr %0, i64 1
  %7 = load i64, ptr %6, align 8
  call void @llvm.memset.p0.i64(ptr align 8 %3, i8 0, i64 512, i1 false)
  br label %8

8:                                                ; preds = %13, %2
  %9 = phi i64 [ 0, %2 ], [ %14, %13 ]
  %10 = icmp ult i64 %9, %7
  br i1 %10, label %11, label %15

11:                                               ; preds = %8
  %12 = icmp ult i64 %9, 64
  br i1 %12, label %16, label %21

13:                                               ; preds = %16
  %14 = add i64 %9, 1
  br label %8

15:                                               ; preds = %8
  br label %22

16:                                               ; preds = %11
  %17 = getelementptr [64 x i64], ptr %3, i64 0, i64 %9
  %18 = add i64 2, %9
  %19 = getelementptr i64, ptr %0, i64 %18
  %20 = load i64, ptr %19, align 8
  store i64 %20, ptr %17, align 8
  br label %13

21:                                               ; preds = %11
  call void @llvm.trap()
  unreachable

22:                                               ; preds = %32, %15
  %23 = phi i64 [ %7, %15 ], [ %33, %32 ]
  %24 = icmp ult i64 %23, %5
  br i1 %24, label %25, label %34

25:                                               ; preds = %22
  %26 = add i64 2, %5
  %27 = add i64 %26, %23
  %28 = sub i64 %27, %7
  %29 = getelementptr i64, ptr %0, i64 %28
  %30 = load i64, ptr %29, align 8
  %31 = icmp ult i64 %30, %7
  br i1 %31, label %35, label %37

32:                                               ; preds = %38
  %33 = add i64 %23, 1
  br label %22

34:                                               ; preds = %22
  br label %45

35:                                               ; preds = %25
  %36 = icmp ult i64 %30, 64
  br i1 %36, label %39, label %44

37:                                               ; preds = %25
  br label %38

38:                                               ; preds = %39, %37
  br label %32

39:                                               ; preds = %35
  %40 = getelementptr [64 x i64], ptr %3, i64 0, i64 %30
  %41 = add i64 2, %23
  %42 = getelementptr i64, ptr %0, i64 %41
  %43 = load i64, ptr %42, align 8
  store i64 %43, ptr %40, align 8
  br label %38

44:                                               ; preds = %35
  call void @llvm.trap()
  unreachable

45:                                               ; preds = %50, %34
  %46 = phi i64 [ 0, %34 ], [ %51, %50 ]
  %47 = icmp ult i64 %46, %7
  br i1 %47, label %48, label %52

48:                                               ; preds = %45
  %49 = icmp ult i64 %46, 64
  br i1 %49, label %54, label %57

50:                                               ; preds = %71
  %51 = add i64 %46, 1
  br label %45

52:                                               ; preds = %45
  %53 = mul i64 8, %7
  ret i64 %53

54:                                               ; preds = %48
  %55 = getelementptr [64 x i64], ptr %3, i64 0, i64 %46
  %56 = load i64, ptr %55, align 8
  br label %58

57:                                               ; preds = %48
  call void @llvm.trap()
  unreachable

58:                                               ; preds = %69, %54
  %59 = phi i64 [ %56, %54 ], [ %68, %69 ]
  %60 = phi i64 [ 0, %54 ], [ %70, %69 ]
  %61 = icmp slt i64 %60, 8
  br i1 %61, label %62, label %71

62:                                               ; preds = %58
  %63 = mul i64 8, %46
  %64 = add i64 %63, %60
  %65 = getelementptr i8, ptr %1, i64 %64
  %66 = and i64 %59, 255
  %67 = trunc i64 %66 to i8
  store i8 %67, ptr %65, align 1
  %68 = lshr i64 %59, 8
  br label %69

69:                                               ; preds = %62
  %70 = add i64 %60, 1
  br label %58

71:                                               ; preds = %58
  br label %50
}

; Function Attrs: cold noreturn nounwind memory(inaccessiblemem: write)
declare void @llvm.trap() #1

; Function Attrs: nocallback nofree nosync nounwind willreturn memory(argmem: write)
declare void @llvm.memset.p0.i64(ptr writeonly captures(none), i8, i64, i1 immarg) #2

attributes #0 = { nounwind }
attributes #1 = { cold noreturn nounwind memory(inaccessiblemem: write) }
attributes #2 = { nocallback nofree nosync nounwind willreturn memory(argmem: write) }
