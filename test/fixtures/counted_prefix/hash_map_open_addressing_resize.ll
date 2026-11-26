target datalayout = "e-m:o-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-n32:64-S128-Fn32"
target triple = "arm64-apple-darwin27.2.0"

%DynArrayView = type { ptr, i64 }

; Function Attrs: nounwind
define hidden void @hash_map_open_addressing_place(%DynArrayView %0, %DynArrayView %1, %DynArrayView %2, i64 %3, i64 %4, i64 %5) #0 {
  %7 = alloca %DynArrayView, align 8
  %8 = alloca %DynArrayView, align 8
  %9 = alloca %DynArrayView, align 8
  store %DynArrayView %0, ptr %9, align 8
  store %DynArrayView %1, ptr %8, align 8
  store %DynArrayView %2, ptr %7, align 8
  %10 = srem i64 %4, %3
  br label %11

11:                                               ; preds = %69, %6
  %12 = phi i64 [ %10, %6 ], [ %71, %69 ]
  %13 = phi i64 [ 0, %6 ], [ %72, %69 ]
  %14 = icmp ult i64 %13, %3
  br i1 %14, label %15, label %20

15:                                               ; preds = %11
  %16 = load %DynArrayView, ptr %9, align 8
  %17 = extractvalue %DynArrayView %16, 0
  %18 = extractvalue %DynArrayView %16, 1
  %19 = icmp ult i64 %12, %18
  br i1 %19, label %21, label %25

20:                                               ; preds = %11
  ret void

21:                                               ; preds = %15
  %22 = getelementptr i64, ptr %17, i64 %12
  %23 = load i64, ptr %22, align 8
  %24 = icmp ne i64 %23, 1
  br i1 %24, label %26, label %32

25:                                               ; preds = %15
  call void @llvm.trap()
  unreachable

26:                                               ; preds = %21
  %27 = getelementptr inbounds nuw %DynArrayView, ptr %9, i32 0, i32 0
  %28 = load ptr, ptr %27, align 8
  %29 = getelementptr inbounds nuw %DynArrayView, ptr %9, i32 0, i32 1
  %30 = load i64, ptr %29, align 8
  %31 = icmp ult i64 %12, %30
  br i1 %31, label %38, label %45

32:                                               ; preds = %21
  br label %33

33:                                               ; preds = %32
  %34 = load %DynArrayView, ptr %8, align 8
  %35 = extractvalue %DynArrayView %34, 0
  %36 = extractvalue %DynArrayView %34, 1
  %37 = icmp ult i64 %12, %36
  br i1 %37, label %57, label %61

38:                                               ; preds = %26
  %39 = getelementptr i64, ptr %28, i64 %12
  store i64 1, ptr %39, align 8
  %40 = getelementptr inbounds nuw %DynArrayView, ptr %8, i32 0, i32 0
  %41 = load ptr, ptr %40, align 8
  %42 = getelementptr inbounds nuw %DynArrayView, ptr %8, i32 0, i32 1
  %43 = load i64, ptr %42, align 8
  %44 = icmp ult i64 %12, %43
  br i1 %44, label %46, label %53

45:                                               ; preds = %26
  call void @llvm.trap()
  unreachable

46:                                               ; preds = %38
  %47 = getelementptr i64, ptr %41, i64 %12
  store i64 %4, ptr %47, align 8
  %48 = getelementptr inbounds nuw %DynArrayView, ptr %7, i32 0, i32 0
  %49 = load ptr, ptr %48, align 8
  %50 = getelementptr inbounds nuw %DynArrayView, ptr %7, i32 0, i32 1
  %51 = load i64, ptr %50, align 8
  %52 = icmp ult i64 %12, %51
  br i1 %52, label %54, label %56

53:                                               ; preds = %38
  call void @llvm.trap()
  unreachable

54:                                               ; preds = %46
  %55 = getelementptr i64, ptr %49, i64 %12
  store i64 %5, ptr %55, align 8
  ret void

56:                                               ; preds = %46
  call void @llvm.trap()
  unreachable

57:                                               ; preds = %33
  %58 = getelementptr i64, ptr %35, i64 %12
  %59 = load i64, ptr %58, align 8
  %60 = icmp eq i64 %59, %4
  br i1 %60, label %62, label %68

61:                                               ; preds = %33
  call void @llvm.trap()
  unreachable

62:                                               ; preds = %57
  %63 = getelementptr inbounds nuw %DynArrayView, ptr %7, i32 0, i32 0
  %64 = load ptr, ptr %63, align 8
  %65 = getelementptr inbounds nuw %DynArrayView, ptr %7, i32 0, i32 1
  %66 = load i64, ptr %65, align 8
  %67 = icmp ult i64 %12, %66
  br i1 %67, label %73, label %75

68:                                               ; preds = %57
  br label %69

69:                                               ; preds = %68
  %70 = add i64 %12, 1
  %71 = urem i64 %70, %3
  %72 = add i64 %13, 1
  br label %11

73:                                               ; preds = %62
  %74 = getelementptr i64, ptr %64, i64 %12
  store i64 %5, ptr %74, align 8
  ret void

75:                                               ; preds = %62
  call void @llvm.trap()
  unreachable
}

; Function Attrs: nounwind
define hidden void @hash_map_open_addressing_resize(%DynArrayView %0, %DynArrayView %1, %DynArrayView %2, ptr %3, i64 %4, ptr %5) #0 {
  %7 = alloca [1024 x i64], align 8
  %8 = alloca [1024 x i64], align 8
  %9 = alloca [1024 x i64], align 8
  %10 = alloca %DynArrayView, align 8
  %11 = alloca %DynArrayView, align 8
  %12 = alloca %DynArrayView, align 8
  store %DynArrayView %0, ptr %12, align 8
  store %DynArrayView %1, ptr %11, align 8
  store %DynArrayView %2, ptr %10, align 8
  %13 = load i64, ptr %3, align 8
  call void @llvm.memset.p0.i64(ptr %9, i8 0, i64 8192, i1 false)
  call void @llvm.memset.p0.i64(ptr %8, i8 0, i64 8192, i1 false)
  call void @llvm.memset.p0.i64(ptr %7, i8 0, i64 8192, i1 false)
  br label %14

14:                                               ; preds = %51, %6
  %15 = phi i64 [ 0, %6 ], [ %54, %51 ]
  %16 = icmp ult i64 %15, %13
  br i1 %16, label %17, label %19

17:                                               ; preds = %14
  %18 = icmp ult i64 %15, 1024
  br i1 %18, label %20, label %26

19:                                               ; preds = %14
  br label %56

20:                                               ; preds = %17
  %21 = getelementptr [1024 x i64], ptr %9, i64 0, i64 %15
  %22 = load %DynArrayView, ptr %12, align 8
  %23 = extractvalue %DynArrayView %22, 0
  %24 = extractvalue %DynArrayView %22, 1
  %25 = icmp ult i64 %15, %24
  br i1 %25, label %27, label %31

26:                                               ; preds = %17
  call void @llvm.trap()
  unreachable

27:                                               ; preds = %20
  %28 = getelementptr i64, ptr %23, i64 %15
  %29 = load i64, ptr %28, align 8
  store i64 %29, ptr %21, align 8
  %30 = icmp ult i64 %15, 1024
  br i1 %30, label %32, label %38

31:                                               ; preds = %20
  call void @llvm.trap()
  unreachable

32:                                               ; preds = %27
  %33 = getelementptr [1024 x i64], ptr %8, i64 0, i64 %15
  %34 = load %DynArrayView, ptr %11, align 8
  %35 = extractvalue %DynArrayView %34, 0
  %36 = extractvalue %DynArrayView %34, 1
  %37 = icmp ult i64 %15, %36
  br i1 %37, label %39, label %43

38:                                               ; preds = %27
  call void @llvm.trap()
  unreachable

39:                                               ; preds = %32
  %40 = getelementptr i64, ptr %35, i64 %15
  %41 = load i64, ptr %40, align 8
  store i64 %41, ptr %33, align 8
  %42 = icmp ult i64 %15, 1024
  br i1 %42, label %44, label %50

43:                                               ; preds = %32
  call void @llvm.trap()
  unreachable

44:                                               ; preds = %39
  %45 = getelementptr [1024 x i64], ptr %7, i64 0, i64 %15
  %46 = load %DynArrayView, ptr %10, align 8
  %47 = extractvalue %DynArrayView %46, 0
  %48 = extractvalue %DynArrayView %46, 1
  %49 = icmp ult i64 %15, %48
  br i1 %49, label %51, label %55

50:                                               ; preds = %39
  call void @llvm.trap()
  unreachable

51:                                               ; preds = %44
  %52 = getelementptr i64, ptr %47, i64 %15
  %53 = load i64, ptr %52, align 8
  store i64 %53, ptr %45, align 8
  %54 = add i64 %15, 1
  br label %14

55:                                               ; preds = %44
  call void @llvm.trap()
  unreachable

56:                                               ; preds = %82, %19
  %57 = phi i64 [ 0, %19 ], [ %84, %82 ]
  %58 = icmp ult i64 %57, %4
  br i1 %58, label %59, label %65

59:                                               ; preds = %56
  %60 = getelementptr inbounds nuw %DynArrayView, ptr %12, i32 0, i32 0
  %61 = load ptr, ptr %60, align 8
  %62 = getelementptr inbounds nuw %DynArrayView, ptr %12, i32 0, i32 1
  %63 = load i64, ptr %62, align 8
  %64 = icmp ult i64 %57, %63
  br i1 %64, label %66, label %73

65:                                               ; preds = %56
  store i64 %4, ptr %3, align 8
  store i64 0, ptr %5, align 8
  br label %86

66:                                               ; preds = %59
  %67 = getelementptr i64, ptr %61, i64 %57
  store i64 0, ptr %67, align 8
  %68 = getelementptr inbounds nuw %DynArrayView, ptr %11, i32 0, i32 0
  %69 = load ptr, ptr %68, align 8
  %70 = getelementptr inbounds nuw %DynArrayView, ptr %11, i32 0, i32 1
  %71 = load i64, ptr %70, align 8
  %72 = icmp ult i64 %57, %71
  br i1 %72, label %74, label %81

73:                                               ; preds = %59
  call void @llvm.trap()
  unreachable

74:                                               ; preds = %66
  %75 = getelementptr i64, ptr %69, i64 %57
  store i64 0, ptr %75, align 8
  %76 = getelementptr inbounds nuw %DynArrayView, ptr %10, i32 0, i32 0
  %77 = load ptr, ptr %76, align 8
  %78 = getelementptr inbounds nuw %DynArrayView, ptr %10, i32 0, i32 1
  %79 = load i64, ptr %78, align 8
  %80 = icmp ult i64 %57, %79
  br i1 %80, label %82, label %85

81:                                               ; preds = %66
  call void @llvm.trap()
  unreachable

82:                                               ; preds = %74
  %83 = getelementptr i64, ptr %77, i64 %57
  store i64 0, ptr %83, align 8
  %84 = add i64 %57, 1
  br label %56

85:                                               ; preds = %74
  call void @llvm.trap()
  unreachable

86:                                               ; preds = %103, %65
  %87 = phi i64 [ 0, %65 ], [ %104, %103 ]
  %88 = icmp ult i64 %87, %13
  br i1 %88, label %89, label %91

89:                                               ; preds = %86
  %90 = icmp ult i64 %87, 1024
  br i1 %90, label %92, label %96

91:                                               ; preds = %86
  ret void

92:                                               ; preds = %89
  %93 = getelementptr [1024 x i64], ptr %9, i64 0, i64 %87
  %94 = load i64, ptr %93, align 8
  %95 = icmp eq i64 %94, 1
  br i1 %95, label %97, label %102

96:                                               ; preds = %89
  call void @llvm.trap()
  unreachable

97:                                               ; preds = %92
  %98 = load %DynArrayView, ptr %12, align 8
  %99 = load %DynArrayView, ptr %11, align 8
  %100 = load %DynArrayView, ptr %10, align 8
  %101 = icmp ult i64 %87, 1024
  br i1 %101, label %105, label %109

102:                                              ; preds = %92
  br label %103

103:                                              ; preds = %110, %102
  %104 = add i64 %87, 1
  br label %86

105:                                              ; preds = %97
  %106 = getelementptr [1024 x i64], ptr %8, i64 0, i64 %87
  %107 = load i64, ptr %106, align 8
  %108 = icmp ult i64 %87, 1024
  br i1 %108, label %110, label %115

109:                                              ; preds = %97
  call void @llvm.trap()
  unreachable

110:                                              ; preds = %105
  %111 = getelementptr [1024 x i64], ptr %7, i64 0, i64 %87
  %112 = load i64, ptr %111, align 8
  call void @hash_map_open_addressing_place(%DynArrayView %98, %DynArrayView %99, %DynArrayView %100, i64 %4, i64 %107, i64 %112)
  %113 = load i64, ptr %5, align 8
  %114 = add i64 %113, 1
  store i64 %114, ptr %5, align 8
  br label %103

115:                                              ; preds = %105
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
