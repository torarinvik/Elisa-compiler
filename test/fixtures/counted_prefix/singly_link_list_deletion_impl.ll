target datalayout = "e-m:o-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-n32:64-S128-Fn32"
target triple = "arm64-apple-darwin27.2.0"

; Function Attrs: nounwind
define hidden void @store_i32_le(i32 %0, ptr %1, i64 %2) #0 {
  %4 = getelementptr i8, ptr %1, i64 %2
  %5 = and i32 %0, 255
  %6 = trunc i32 %5 to i8
  store i8 %6, ptr %4, align 1
  %7 = add i64 %2, 1
  %8 = getelementptr i8, ptr %1, i64 %7
  %9 = lshr i32 %0, 8
  %10 = and i32 %9, 255
  %11 = trunc i32 %10 to i8
  store i8 %11, ptr %8, align 1
  %12 = add i64 %2, 2
  %13 = getelementptr i8, ptr %1, i64 %12
  %14 = lshr i32 %0, 16
  %15 = and i32 %14, 255
  %16 = trunc i32 %15 to i8
  store i8 %16, ptr %13, align 1
  %17 = add i64 %2, 3
  %18 = getelementptr i8, ptr %1, i64 %17
  %19 = lshr i32 %0, 24
  %20 = and i32 %19, 255
  %21 = trunc i32 %20 to i8
  store i8 %21, ptr %18, align 1
  ret void
}

; Function Attrs: nounwind
define hidden i64 @singly_link_list_deletion_impl(ptr %0, i64 %1, ptr %2, i64 %3) #0 {
  %5 = alloca [64 x i32], align 4
  %6 = alloca [64 x i32], align 4
  %7 = icmp eq ptr %0, null
  br i1 %7, label %10, label %8

8:                                                ; preds = %4
  %9 = icmp ult i64 %1, 2
  br label %10

10:                                               ; preds = %8, %4
  %11 = phi i1 [ true, %4 ], [ %9, %8 ]
  br i1 %11, label %14, label %12

12:                                               ; preds = %10
  %13 = icmp ugt i64 %1, 66
  br label %14

14:                                               ; preds = %12, %10
  %15 = phi i1 [ true, %10 ], [ %13, %12 ]
  br i1 %15, label %16, label %17

16:                                               ; preds = %14
  ret i64 -1

17:                                               ; preds = %14
  br label %18

18:                                               ; preds = %17
  %19 = getelementptr i64, ptr %0, i64 0
  %20 = load i64, ptr %19, align 8
  %21 = icmp slt i64 %20, 1
  br i1 %21, label %26, label %22

22:                                               ; preds = %18
  %23 = getelementptr i64, ptr %0, i64 0
  %24 = load i64, ptr %23, align 8
  %25 = icmp sgt i64 %24, 64
  br label %26

26:                                               ; preds = %22, %18
  %27 = phi i1 [ true, %18 ], [ %25, %22 ]
  br i1 %27, label %28, label %29

28:                                               ; preds = %26
  ret i64 -1

29:                                               ; preds = %26
  br label %30

30:                                               ; preds = %29
  %31 = getelementptr i64, ptr %0, i64 0
  %32 = load i64, ptr %31, align 8
  %33 = add i64 %32, 2
  %34 = icmp ne i64 %1, %33
  br i1 %34, label %39, label %35

35:                                               ; preds = %30
  %36 = getelementptr i64, ptr %0, i64 1
  %37 = load i64, ptr %36, align 8
  %38 = icmp slt i64 %37, 1
  br label %39

39:                                               ; preds = %35, %30
  %40 = phi i1 [ true, %30 ], [ %38, %35 ]
  br i1 %40, label %45, label %41

41:                                               ; preds = %39
  %42 = getelementptr i64, ptr %0, i64 1
  %43 = load i64, ptr %42, align 8
  %44 = icmp sgt i64 %43, %32
  br label %45

45:                                               ; preds = %41, %39
  %46 = phi i1 [ true, %39 ], [ %44, %41 ]
  br i1 %46, label %47, label %48

47:                                               ; preds = %45
  ret i64 -1

48:                                               ; preds = %45
  br label %49

49:                                               ; preds = %48
  br label %50

50:                                               ; preds = %71, %49
  %51 = phi i64 [ 0, %49 ], [ %72, %71 ]
  %52 = icmp ult i64 %51, %32
  br i1 %52, label %53, label %58

53:                                               ; preds = %50
  %54 = add i64 %51, 2
  %55 = getelementptr i64, ptr %0, i64 %54
  %56 = load i64, ptr %55, align 8
  %57 = icmp slt i64 %56, -2147483648
  br i1 %57, label %67, label %62

58:                                               ; preds = %50
  %59 = sub i64 %32, 1
  %60 = mul i64 4, %59
  %61 = icmp eq ptr %2, null
  br i1 %61, label %75, label %73

62:                                               ; preds = %53
  %63 = add i64 %51, 2
  %64 = getelementptr i64, ptr %0, i64 %63
  %65 = load i64, ptr %64, align 8
  %66 = icmp sgt i64 %65, 2147483647
  br label %67

67:                                               ; preds = %62, %53
  %68 = phi i1 [ true, %53 ], [ %66, %62 ]
  br i1 %68, label %69, label %70

69:                                               ; preds = %67
  ret i64 -1

70:                                               ; preds = %67
  br label %71

71:                                               ; preds = %70
  %72 = add i64 %51, 1
  br label %50

73:                                               ; preds = %58
  %74 = icmp ult i64 %3, %60
  br label %75

75:                                               ; preds = %73, %58
  %76 = phi i1 [ true, %58 ], [ %74, %73 ]
  br i1 %76, label %77, label %78

77:                                               ; preds = %75
  ret i64 -2

78:                                               ; preds = %75
  br label %79

79:                                               ; preds = %78
  call void @llvm.memset.p0.i64(ptr align 4 %6, i8 0, i64 256, i1 false)
  call void @llvm.memset.p0.i64(ptr align 4 %5, i8 0, i64 256, i1 false)
  br label %80

80:                                               ; preds = %102, %79
  %81 = phi i64 [ 0, %79 ], [ %103, %102 ]
  %82 = icmp ult i64 %81, %32
  br i1 %82, label %83, label %85

83:                                               ; preds = %80
  %84 = icmp ult i64 %81, 64
  br i1 %84, label %89, label %97

85:                                               ; preds = %80
  %86 = getelementptr i64, ptr %0, i64 1
  %87 = load i64, ptr %86, align 8
  %88 = icmp eq i64 %87, 1
  br i1 %88, label %112, label %115

89:                                               ; preds = %83
  %90 = getelementptr [64 x i32], ptr %6, i64 0, i64 %81
  %91 = add i64 %81, 2
  %92 = getelementptr i64, ptr %0, i64 %91
  %93 = load i64, ptr %92, align 8
  %94 = trunc i64 %93 to i32
  store i32 %94, ptr %90, align 4
  %95 = add i64 %81, 1
  %96 = icmp ult i64 %95, %32
  br i1 %96, label %98, label %100

97:                                               ; preds = %83
  call void @llvm.trap()
  unreachable

98:                                               ; preds = %89
  %99 = icmp ult i64 %81, 64
  br i1 %99, label %104, label %108

100:                                              ; preds = %89
  %101 = icmp ult i64 %81, 64
  br i1 %101, label %109, label %111

102:                                              ; preds = %109, %104
  %103 = add i64 %81, 1
  br label %80

104:                                              ; preds = %98
  %105 = getelementptr [64 x i32], ptr %5, i64 0, i64 %81
  %106 = add i64 %81, 1
  %107 = trunc i64 %106 to i32
  store i32 %107, ptr %105, align 4
  br label %102

108:                                              ; preds = %98
  call void @llvm.trap()
  unreachable

109:                                              ; preds = %100
  %110 = getelementptr [64 x i32], ptr %5, i64 0, i64 %81
  store i32 -1, ptr %110, align 4
  br label %102

111:                                              ; preds = %100
  call void @llvm.trap()
  unreachable

112:                                              ; preds = %85
  %113 = sext i32 0 to i64
  %114 = icmp ult i64 %113, 64
  br i1 %114, label %118, label %121

115:                                              ; preds = %85
  br label %122

116:                                              ; preds = %148, %118
  %117 = phi i32 [ %120, %118 ], [ 0, %148 ]
  br label %152

118:                                              ; preds = %112
  %119 = getelementptr [64 x i32], ptr %5, i64 0, i64 %113
  %120 = load i32, ptr %119, align 4
  br label %116

121:                                              ; preds = %112
  call void @llvm.trap()
  unreachable

122:                                              ; preds = %132, %115
  %123 = phi i64 [ 2, %115 ], [ %135, %132 ]
  %124 = phi i32 [ 0, %115 ], [ %134, %132 ]
  %125 = icmp ult i64 %123, %87
  br i1 %125, label %126, label %129

126:                                              ; preds = %122
  %127 = sext i32 %124 to i64
  %128 = icmp ult i64 %127, 64
  br i1 %128, label %132, label %136

129:                                              ; preds = %122
  %130 = sext i32 %124 to i64
  %131 = icmp ult i64 %130, 64
  br i1 %131, label %137, label %142

132:                                              ; preds = %126
  %133 = getelementptr [64 x i32], ptr %5, i64 0, i64 %127
  %134 = load i32, ptr %133, align 4
  %135 = add i64 %123, 1
  br label %122

136:                                              ; preds = %126
  call void @llvm.trap()
  unreachable

137:                                              ; preds = %129
  %138 = getelementptr [64 x i32], ptr %5, i64 0, i64 %130
  %139 = load i32, ptr %138, align 4
  %140 = sext i32 %124 to i64
  %141 = icmp ult i64 %140, 64
  br i1 %141, label %143, label %147

142:                                              ; preds = %129
  call void @llvm.trap()
  unreachable

143:                                              ; preds = %137
  %144 = getelementptr [64 x i32], ptr %5, i64 0, i64 %140
  %145 = sext i32 %139 to i64
  %146 = icmp ult i64 %145, 64
  br i1 %146, label %148, label %151

147:                                              ; preds = %137
  call void @llvm.trap()
  unreachable

148:                                              ; preds = %143
  %149 = getelementptr [64 x i32], ptr %5, i64 0, i64 %145
  %150 = load i32, ptr %149, align 4
  store i32 %150, ptr %144, align 4
  br label %116

151:                                              ; preds = %143
  call void @llvm.trap()
  unreachable

152:                                              ; preds = %173, %116
  %153 = phi i64 [ 0, %116 ], [ %175, %173 ]
  %154 = phi i32 [ %117, %116 ], [ %174, %173 ]
  %155 = sub i64 %32, 1
  %156 = icmp ult i64 %153, %155
  br i1 %156, label %157, label %160

157:                                              ; preds = %152
  %158 = sext i32 %154 to i64
  %159 = icmp ult i64 %158, 64
  br i1 %159, label %161, label %168

160:                                              ; preds = %152
  ret i64 %60

161:                                              ; preds = %157
  %162 = getelementptr [64 x i32], ptr %6, i64 0, i64 %158
  %163 = load i32, ptr %162, align 4
  %164 = mul i64 %153, 4
  call void @store_i32_le(i32 %163, ptr %2, i64 %164)
  %165 = add i64 %153, 1
  %166 = sub i64 %32, 1
  %167 = icmp ult i64 %165, %166
  br i1 %167, label %169, label %172

168:                                              ; preds = %157
  call void @llvm.trap()
  unreachable

169:                                              ; preds = %161
  %170 = sext i32 %154 to i64
  %171 = icmp ult i64 %170, 64
  br i1 %171, label %176, label %179

172:                                              ; preds = %161
  br label %173

173:                                              ; preds = %176, %172
  %174 = phi i32 [ %178, %176 ], [ %154, %172 ]
  %175 = add i64 %153, 1
  br label %152

176:                                              ; preds = %169
  %177 = getelementptr [64 x i32], ptr %5, i64 0, i64 %170
  %178 = load i32, ptr %177, align 4
  br label %173

179:                                              ; preds = %169
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
