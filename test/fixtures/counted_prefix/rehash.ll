target datalayout = "e-m:o-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-n32:64-S128-Fn32"
target triple = "arm64-apple-darwin27.2.0"

%DynArrayView = type { ptr, i64 }

; Function Attrs: nounwind
define hidden i64 @insertion_slot(%DynArrayView %0, i64 %1, i32 %2) #0 {
  %4 = sext i32 %2 to i64
  %5 = urem i64 %4, %1
  br label %6

6:                                                ; preds = %33, %3
  %7 = phi i64 [ %5, %3 ], [ %35, %33 ]
  %8 = phi i64 [ 0, %3 ], [ %36, %33 ]
  %9 = icmp ult i64 %8, %1
  br i1 %9, label %10, label %14

10:                                               ; preds = %6
  %11 = extractvalue %DynArrayView %0, 0
  %12 = extractvalue %DynArrayView %0, 1
  %13 = icmp ult i64 %7, %12
  br i1 %13, label %15, label %19

14:                                               ; preds = %6
  ret i64 %1

15:                                               ; preds = %10
  %16 = getelementptr i32, ptr %11, i64 %7
  %17 = load i32, ptr %16, align 4
  %18 = icmp eq i32 %17, 0
  br i1 %18, label %24, label %20

19:                                               ; preds = %10
  call void @llvm.trap()
  unreachable

20:                                               ; preds = %15
  %21 = extractvalue %DynArrayView %0, 0
  %22 = extractvalue %DynArrayView %0, 1
  %23 = icmp ult i64 %7, %22
  br i1 %23, label %26, label %30

24:                                               ; preds = %26, %15
  %25 = phi i1 [ true, %15 ], [ %29, %26 ]
  br i1 %25, label %31, label %32

26:                                               ; preds = %20
  %27 = getelementptr i32, ptr %21, i64 %7
  %28 = load i32, ptr %27, align 4
  %29 = icmp eq i32 %28, -1
  br label %24

30:                                               ; preds = %20
  call void @llvm.trap()
  unreachable

31:                                               ; preds = %24
  ret i64 %7

32:                                               ; preds = %24
  br label %33

33:                                               ; preds = %32
  %34 = add i64 %7, 1
  %35 = urem i64 %34, %1
  %36 = add i64 %8, 1
  br label %6
}

; Function Attrs: nounwind
define hidden void @rehash(%DynArrayView %0, ptr %1) #0 {
  %3 = alloca [128 x i32], align 4
  %4 = alloca %DynArrayView, align 8
  store %DynArrayView %0, ptr %4, align 8
  call void @llvm.memset.p0.i64(ptr align 4 %3, i8 0, i64 512, i1 false)
  %5 = load i64, ptr %1, align 8
  br label %6

6:                                                ; preds = %21, %2
  %7 = phi i64 [ 0, %2 ], [ %24, %21 ]
  %8 = icmp ult i64 %7, %5
  br i1 %8, label %9, label %11

9:                                                ; preds = %6
  %10 = icmp ult i64 %7, 128
  br i1 %10, label %14, label %20

11:                                               ; preds = %6
  %12 = load i64, ptr %1, align 8
  %13 = mul i64 %12, 2
  store i64 %13, ptr %1, align 8
  br label %26

14:                                               ; preds = %9
  %15 = getelementptr [128 x i32], ptr %3, i64 0, i64 %7
  %16 = load %DynArrayView, ptr %4, align 8
  %17 = extractvalue %DynArrayView %16, 0
  %18 = extractvalue %DynArrayView %16, 1
  %19 = icmp ult i64 %7, %18
  br i1 %19, label %21, label %25

20:                                               ; preds = %9
  call void @llvm.trap()
  unreachable

21:                                               ; preds = %14
  %22 = getelementptr i32, ptr %17, i64 %7
  %23 = load i32, ptr %22, align 4
  store i32 %23, ptr %15, align 4
  %24 = add i64 %7, 1
  br label %6

25:                                               ; preds = %14
  call void @llvm.trap()
  unreachable

26:                                               ; preds = %37, %11
  %27 = phi i64 [ 0, %11 ], [ %39, %37 ]
  %28 = load i64, ptr %1, align 8
  %29 = icmp ult i64 %27, %28
  br i1 %29, label %30, label %36

30:                                               ; preds = %26
  %31 = getelementptr inbounds nuw %DynArrayView, ptr %4, i32 0, i32 0
  %32 = load ptr, ptr %31, align 8
  %33 = getelementptr inbounds nuw %DynArrayView, ptr %4, i32 0, i32 1
  %34 = load i64, ptr %33, align 8
  %35 = icmp ult i64 %27, %34
  br i1 %35, label %37, label %40

36:                                               ; preds = %26
  br label %41

37:                                               ; preds = %30
  %38 = getelementptr i32, ptr %32, i64 %27
  store i32 0, ptr %38, align 4
  %39 = add i64 %27, 1
  br label %26

40:                                               ; preds = %30
  call void @llvm.trap()
  unreachable

41:                                               ; preds = %71, %36
  %42 = phi i64 [ 0, %36 ], [ %72, %71 ]
  %43 = icmp ult i64 %42, %5
  br i1 %43, label %44, label %46

44:                                               ; preds = %41
  %45 = icmp ult i64 %42, 128
  br i1 %45, label %47, label %51

46:                                               ; preds = %41
  ret void

47:                                               ; preds = %44
  %48 = getelementptr [128 x i32], ptr %3, i64 0, i64 %42
  %49 = load i32, ptr %48, align 4
  %50 = icmp sgt i32 %49, 0
  br i1 %50, label %52, label %70

51:                                               ; preds = %44
  call void @llvm.trap()
  unreachable

52:                                               ; preds = %47
  %53 = load %DynArrayView, ptr %4, align 8
  %54 = extractvalue %DynArrayView %53, 0
  %55 = extractvalue %DynArrayView %53, 1
  %56 = icmp ugt i64 0, %55
  %57 = select i1 %56, i64 %55, i64 0
  %58 = icmp ugt i64 128, %55
  %59 = select i1 %58, i64 %55, i64 128
  %60 = icmp uge i64 %59, %57
  %61 = select i1 %60, i64 %59, i64 %57
  %62 = sub i64 %61, %57
  %63 = getelementptr i32, ptr %54, i64 %57
  %64 = insertvalue %DynArrayView undef, ptr %63, 0
  %65 = insertvalue %DynArrayView %64, i64 %62, 1
  %66 = load i64, ptr %1, align 8
  %67 = call i64 @insertion_slot(%DynArrayView %65, i64 %66, i32 %49)
  %68 = load i64, ptr %1, align 8
  %69 = icmp ult i64 %67, %68
  br i1 %69, label %73, label %79

70:                                               ; preds = %47
  br label %71

71:                                               ; preds = %80, %70
  %72 = add i64 %42, 1
  br label %41

73:                                               ; preds = %52
  %74 = getelementptr inbounds nuw %DynArrayView, ptr %4, i32 0, i32 0
  %75 = load ptr, ptr %74, align 8
  %76 = getelementptr inbounds nuw %DynArrayView, ptr %4, i32 0, i32 1
  %77 = load i64, ptr %76, align 8
  %78 = icmp ult i64 %67, %77
  br i1 %78, label %81, label %83

79:                                               ; preds = %52
  br label %80

80:                                               ; preds = %81, %79
  br label %71

81:                                               ; preds = %73
  %82 = getelementptr i32, ptr %75, i64 %67
  store i32 %49, ptr %82, align 4
  br label %80

83:                                               ; preds = %73
  call void @llvm.trap()
  unreachable
}

; Function Attrs: cold noreturn nounwind memory(inaccessiblemem: write)
declare void @llvm.trap() #1

; Function Attrs: nocallback nofree nosync nounwind willreturn memory(argmem: write)
declare void @llvm.memset.p0.i64(ptr writeonly captures(none), i8, i64, i1 immarg) #2

attributes #0 = { nounwind }
attributes #1 = { cold noreturn nounwind memory(inaccessiblemem: write) }
attributes #2 = { nocallback nofree nosync nounwind willreturn memory(argmem: write) }
