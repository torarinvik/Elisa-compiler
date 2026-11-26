target datalayout = "e-m:o-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-n32:64-S128-Fn32"
target triple = "arm64-apple-darwin27.2.0"

; Function Attrs: nounwind
define hidden void @subtractive_put_i64_le(ptr %0, i64 %1, i32 %2) #0 {
  %4 = sext i32 %2 to i64
  br label %5

5:                                                ; preds = %9, %3
  %6 = phi i64 [ %4, %3 ], [ %14, %9 ]
  %7 = phi i64 [ 0, %3 ], [ %15, %9 ]
  %8 = icmp ult i64 %7, 8
  br i1 %8, label %9, label %16

9:                                                ; preds = %5
  %10 = add i64 %1, %7
  %11 = getelementptr i8, ptr %0, i64 %10
  %12 = and i64 %6, 255
  %13 = trunc i64 %12 to i8
  store i8 %13, ptr %11, align 1
  %14 = lshr i64 %6, 8
  %15 = add i64 %7, 1
  br label %5

16:                                               ; preds = %5
  ret void
}

; Function Attrs: nounwind
define hidden void @subtractive_generate(ptr %0, ptr %1, i64 %2) #0 {
  %4 = alloca [55 x i32], align 4
  %5 = alloca [55 x i32], align 4
  call void @llvm.memset.p0.i64(ptr align 4 %5, i8 0, i64 220, i1 false)
  call void @llvm.memset.p0.i64(ptr align 4 %4, i8 0, i64 220, i1 false)
  %6 = getelementptr [55 x i32], ptr %5, i64 0, i64 0
  %7 = getelementptr i64, ptr %0, i64 0
  %8 = load i64, ptr %7, align 8
  %9 = trunc i64 %8 to i32
  store i32 %9, ptr %6, align 4
  %10 = getelementptr [55 x i32], ptr %5, i64 0, i64 1
  store i32 1, ptr %10, align 4
  br label %11

11:                                               ; preds = %44, %3
  %12 = phi i64 [ 2, %3 ], [ %46, %44 ]
  %13 = icmp ult i64 %12, 55
  br i1 %13, label %14, label %17

14:                                               ; preds = %11
  %15 = sub i64 %12, 2
  %16 = icmp ult i64 %15, 55
  br i1 %16, label %18, label %23

17:                                               ; preds = %11
  br label %48

18:                                               ; preds = %14
  %19 = getelementptr [55 x i32], ptr %5, i64 0, i64 %15
  %20 = load i32, ptr %19, align 4
  %21 = sub i64 %12, 1
  %22 = icmp ult i64 %21, 55
  br i1 %22, label %24, label %30

23:                                               ; preds = %14
  call void @llvm.trap()
  unreachable

24:                                               ; preds = %18
  %25 = getelementptr [55 x i32], ptr %5, i64 0, i64 %21
  %26 = load i32, ptr %25, align 4
  %27 = call { i32, i1 } @llvm.ssub.with.overflow.i32(i32 %20, i32 %26)
  %28 = extractvalue { i32, i1 } %27, 0
  %29 = extractvalue { i32, i1 } %27, 1
  br i1 %29, label %31, label %32

30:                                               ; preds = %18
  call void @llvm.trap()
  unreachable

31:                                               ; preds = %24
  call void @llvm.trap()
  unreachable

32:                                               ; preds = %24
  %33 = icmp slt i32 %28, 0
  br i1 %33, label %34, label %38

34:                                               ; preds = %32
  %35 = call { i32, i1 } @llvm.sadd.with.overflow.i32(i32 %28, i32 1000000000)
  %36 = extractvalue { i32, i1 } %35, 0
  %37 = extractvalue { i32, i1 } %35, 1
  br i1 %37, label %42, label %43

38:                                               ; preds = %32
  br label %39

39:                                               ; preds = %43, %38
  %40 = phi i32 [ %36, %43 ], [ %28, %38 ]
  %41 = icmp ult i64 %12, 55
  br i1 %41, label %44, label %47

42:                                               ; preds = %34
  call void @llvm.trap()
  unreachable

43:                                               ; preds = %34
  br label %39

44:                                               ; preds = %39
  %45 = getelementptr [55 x i32], ptr %5, i64 0, i64 %12
  store i32 %40, ptr %45, align 4
  %46 = add i64 %12, 1
  br label %11

47:                                               ; preds = %39
  call void @llvm.trap()
  unreachable

48:                                               ; preds = %61, %17
  %49 = phi i64 [ 0, %17 ], [ %64, %61 ]
  %50 = icmp ult i64 %49, 55
  br i1 %50, label %51, label %53

51:                                               ; preds = %48
  %52 = icmp ult i64 %49, 55
  br i1 %52, label %54, label %60

53:                                               ; preds = %48
  br label %66

54:                                               ; preds = %51
  %55 = getelementptr [55 x i32], ptr %4, i64 0, i64 %49
  %56 = add i64 %49, 1
  %57 = mul i64 34, %56
  %58 = urem i64 %57, 55
  %59 = icmp ult i64 %58, 55
  br i1 %59, label %61, label %65

60:                                               ; preds = %51
  call void @llvm.trap()
  unreachable

61:                                               ; preds = %54
  %62 = getelementptr [55 x i32], ptr %5, i64 0, i64 %58
  %63 = load i32, ptr %62, align 4
  store i32 %63, ptr %55, align 4
  %64 = add i64 %49, 1
  br label %48

65:                                               ; preds = %54
  call void @llvm.trap()
  unreachable

66:                                               ; preds = %108, %53
  %67 = phi i64 [ 0, %53 ], [ %110, %108 ]
  %68 = phi i64 [ 31, %53 ], [ %112, %108 ]
  %69 = phi i64 [ 0, %53 ], [ %113, %108 ]
  %70 = add i64 165, %2
  %71 = icmp ult i64 %69, %70
  br i1 %71, label %72, label %74

72:                                               ; preds = %66
  %73 = icmp ult i64 %67, 55
  br i1 %73, label %75, label %79

74:                                               ; preds = %66
  ret void

75:                                               ; preds = %72
  %76 = getelementptr [55 x i32], ptr %4, i64 0, i64 %67
  %77 = load i32, ptr %76, align 4
  %78 = icmp ult i64 %68, 55
  br i1 %78, label %80, label %86

79:                                               ; preds = %72
  call void @llvm.trap()
  unreachable

80:                                               ; preds = %75
  %81 = getelementptr [55 x i32], ptr %4, i64 0, i64 %68
  %82 = load i32, ptr %81, align 4
  %83 = call { i32, i1 } @llvm.ssub.with.overflow.i32(i32 %77, i32 %82)
  %84 = extractvalue { i32, i1 } %83, 0
  %85 = extractvalue { i32, i1 } %83, 1
  br i1 %85, label %87, label %88

86:                                               ; preds = %75
  call void @llvm.trap()
  unreachable

87:                                               ; preds = %80
  call void @llvm.trap()
  unreachable

88:                                               ; preds = %80
  %89 = icmp slt i32 %84, 0
  br i1 %89, label %90, label %94

90:                                               ; preds = %88
  %91 = call { i32, i1 } @llvm.sadd.with.overflow.i32(i32 %84, i32 1000000000)
  %92 = extractvalue { i32, i1 } %91, 0
  %93 = extractvalue { i32, i1 } %91, 1
  br i1 %93, label %98, label %99

94:                                               ; preds = %88
  br label %95

95:                                               ; preds = %99, %94
  %96 = phi i32 [ %92, %99 ], [ %84, %94 ]
  %97 = icmp ult i64 %67, 55
  br i1 %97, label %100, label %103

98:                                               ; preds = %90
  call void @llvm.trap()
  unreachable

99:                                               ; preds = %90
  br label %95

100:                                              ; preds = %95
  %101 = getelementptr [55 x i32], ptr %4, i64 0, i64 %67
  store i32 %96, ptr %101, align 4
  %102 = icmp uge i64 %69, 165
  br i1 %102, label %104, label %107

103:                                              ; preds = %95
  call void @llvm.trap()
  unreachable

104:                                              ; preds = %100
  %105 = sub i64 %69, 165
  %106 = mul i64 %105, 8
  call void @subtractive_put_i64_le(ptr %1, i64 %106, i32 %96)
  br label %108

107:                                              ; preds = %100
  br label %108

108:                                              ; preds = %107, %104
  %109 = add i64 %67, 1
  %110 = urem i64 %109, 55
  %111 = add i64 %68, 1
  %112 = urem i64 %111, 55
  %113 = add i64 %69, 1
  br label %66
}

; Function Attrs: cold noreturn nounwind memory(inaccessiblemem: write)
declare void @llvm.trap() #1

; Function Attrs: nocallback nocreateundeforpoison nofree nosync nounwind speculatable willreturn memory(none)
declare { i32, i1 } @llvm.ssub.with.overflow.i32(i32, i32) #2

; Function Attrs: nocallback nocreateundeforpoison nofree nosync nounwind speculatable willreturn memory(none)
declare { i32, i1 } @llvm.sadd.with.overflow.i32(i32, i32) #2

; Function Attrs: nocallback nofree nosync nounwind willreturn memory(argmem: write)
declare void @llvm.memset.p0.i64(ptr writeonly captures(none), i8, i64, i1 immarg) #3

attributes #0 = { nounwind }
attributes #1 = { cold noreturn nounwind memory(inaccessiblemem: write) }
attributes #2 = { nocallback nocreateundeforpoison nofree nosync nounwind speculatable willreturn memory(none) }
attributes #3 = { nocallback nofree nosync nounwind willreturn memory(argmem: write) }
