target datalayout = "e-m:o-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-n32:64-S128-Fn32"
target triple = "arm64-apple-darwin27.2.0"

; Function Attrs: nounwind
define hidden i64 @string_left_rotation_impl(ptr %0, i64 %1, ptr %2, i64 %3) #0 {
  %5 = alloca [256 x i16], align 2
  %6 = icmp eq ptr %0, null
  br i1 %6, label %9, label %7

7:                                                ; preds = %4
  %8 = icmp ult i64 %1, 2
  br label %9

9:                                                ; preds = %7, %4
  %10 = phi i1 [ true, %4 ], [ %8, %7 ]
  br i1 %10, label %13, label %11

11:                                               ; preds = %9
  %12 = icmp ugt i64 %1, 259
  br label %13

13:                                               ; preds = %11, %9
  %14 = phi i1 [ true, %9 ], [ %12, %11 ]
  br i1 %14, label %15, label %16

15:                                               ; preds = %13
  ret i64 -1

16:                                               ; preds = %13
  br label %17

17:                                               ; preds = %16
  %18 = getelementptr i64, ptr %0, i64 0
  %19 = load i64, ptr %18, align 8
  %20 = getelementptr i64, ptr %0, i64 1
  %21 = load i64, ptr %20, align 8
  %22 = icmp slt i64 %19, 0
  br i1 %22, label %25, label %23

23:                                               ; preds = %17
  %24 = icmp sgt i64 %19, 256
  br label %25

25:                                               ; preds = %23, %17
  %26 = phi i1 [ true, %17 ], [ %24, %23 ]
  br i1 %26, label %29, label %27

27:                                               ; preds = %25
  %28 = icmp slt i64 %21, 0
  br label %29

29:                                               ; preds = %27, %25
  %30 = phi i1 [ true, %25 ], [ %28, %27 ]
  br i1 %30, label %33, label %31

31:                                               ; preds = %29
  %32 = icmp sgt i64 %21, %19
  br label %33

33:                                               ; preds = %31, %29
  %34 = phi i1 [ true, %29 ], [ %32, %31 ]
  br i1 %34, label %38, label %35

35:                                               ; preds = %33
  %36 = add i64 %19, 2
  %37 = icmp ne i64 %1, %36
  br label %38

38:                                               ; preds = %35, %33
  %39 = phi i1 [ true, %33 ], [ %37, %35 ]
  br i1 %39, label %40, label %41

40:                                               ; preds = %38
  ret i64 -1

41:                                               ; preds = %38
  br label %42

42:                                               ; preds = %41
  %43 = icmp eq i64 %19, 0
  br i1 %43, label %44, label %45

44:                                               ; preds = %42
  ret i64 0

45:                                               ; preds = %42
  br label %46

46:                                               ; preds = %45
  call void @llvm.memset.p0.i64(ptr align 2 %5, i8 0, i64 512, i1 false)
  br label %47

47:                                               ; preds = %57, %46
  %48 = phi i64 [ 0, %46 ], [ %58, %57 ]
  %49 = phi i64 [ 0, %46 ], [ %55, %57 ]
  %50 = icmp ult i64 %48, %19
  br i1 %50, label %51, label %59

51:                                               ; preds = %47
  %52 = add i64 %48, 2
  %53 = getelementptr i64, ptr %0, i64 %52
  %54 = load i64, ptr %53, align 8
  %55 = or i64 %49, %54
  %56 = icmp ult i64 %48, 256
  br i1 %56, label %61, label %64

57:                                               ; preds = %61
  %58 = add i64 %48, 1
  br label %47

59:                                               ; preds = %47
  %60 = icmp ugt i64 %49, 65535
  br i1 %60, label %65, label %66

61:                                               ; preds = %51
  %62 = getelementptr [256 x i16], ptr %5, i64 0, i64 %48
  %63 = trunc i64 %54 to i16
  store i16 %63, ptr %62, align 2
  br label %57

64:                                               ; preds = %51
  call void @llvm.trap()
  unreachable

65:                                               ; preds = %59
  ret i64 -1

66:                                               ; preds = %59
  br label %67

67:                                               ; preds = %66
  %68 = mul i64 %19, 2
  %69 = icmp eq ptr %2, null
  br i1 %69, label %72, label %70

70:                                               ; preds = %67
  %71 = icmp ult i64 %3, %68
  br label %72

72:                                               ; preds = %70, %67
  %73 = phi i1 [ true, %67 ], [ %71, %70 ]
  br i1 %73, label %74, label %75

74:                                               ; preds = %72
  ret i64 -2

75:                                               ; preds = %72
  br label %76

76:                                               ; preds = %75
  br label %77

77:                                               ; preds = %84, %76
  %78 = phi i64 [ %21, %76 ], [ %85, %84 ]
  %79 = icmp ult i64 %78, %19
  br i1 %79, label %80, label %86

80:                                               ; preds = %77
  %81 = sub i64 %78, %21
  %82 = mul i64 2, %81
  %83 = icmp ult i64 %78, 256
  br i1 %83, label %89, label %99

84:                                               ; preds = %89
  %85 = add i64 %78, 1
  br label %77

86:                                               ; preds = %77
  %87 = sub i64 %19, %21
  %88 = mul i64 2, %87
  br label %100

89:                                               ; preds = %80
  %90 = getelementptr [256 x i16], ptr %5, i64 0, i64 %78
  %91 = load i16, ptr %90, align 2
  %92 = getelementptr i8, ptr %2, i64 %82
  %93 = and i16 %91, 255
  %94 = trunc i16 %93 to i8
  store i8 %94, ptr %92, align 1
  %95 = add i64 %82, 1
  %96 = getelementptr i8, ptr %2, i64 %95
  %97 = lshr i16 %91, 8
  %98 = trunc i16 %97 to i8
  store i8 %98, ptr %96, align 1
  br label %84

99:                                               ; preds = %80
  call void @llvm.trap()
  unreachable

100:                                              ; preds = %107, %86
  %101 = phi i64 [ 0, %86 ], [ %108, %107 ]
  %102 = icmp ult i64 %101, %21
  br i1 %102, label %103, label %109

103:                                              ; preds = %100
  %104 = mul i64 2, %101
  %105 = add i64 %88, %104
  %106 = icmp ult i64 %101, 256
  br i1 %106, label %110, label %120

107:                                              ; preds = %110
  %108 = add i64 %101, 1
  br label %100

109:                                              ; preds = %100
  ret i64 %68

110:                                              ; preds = %103
  %111 = getelementptr [256 x i16], ptr %5, i64 0, i64 %101
  %112 = load i16, ptr %111, align 2
  %113 = getelementptr i8, ptr %2, i64 %105
  %114 = and i16 %112, 255
  %115 = trunc i16 %114 to i8
  store i8 %115, ptr %113, align 1
  %116 = add i64 %105, 1
  %117 = getelementptr i8, ptr %2, i64 %116
  %118 = lshr i16 %112, 8
  %119 = trunc i16 %118 to i8
  store i8 %119, ptr %117, align 1
  br label %107

120:                                              ; preds = %103
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
