target datalayout = "e-m:o-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-n32:64-S128-Fn32"
target triple = "arm64-apple-darwin27.2.0"

; Function Attrs: nounwind
define hidden i64 @word_patterns_impl(ptr %0, i64 %1, ptr %2, i64 %3) #0 {
  %5 = alloca [3 x i8], align 1
  %6 = alloca [128 x i32], align 4
  %7 = icmp ult i64 %1, 1
  br i1 %7, label %12, label %8

8:                                                ; preds = %4
  %9 = getelementptr i64, ptr %0, i64 0
  %10 = load i64, ptr %9, align 8
  %11 = icmp slt i64 %10, 0
  br label %12

12:                                               ; preds = %8, %4
  %13 = phi i1 [ true, %4 ], [ %11, %8 ]
  br i1 %13, label %18, label %14

14:                                               ; preds = %12
  %15 = getelementptr i64, ptr %0, i64 0
  %16 = load i64, ptr %15, align 8
  %17 = icmp sgt i64 %16, 256
  br label %18

18:                                               ; preds = %14, %12
  %19 = phi i1 [ true, %12 ], [ %17, %14 ]
  br i1 %19, label %20, label %21

20:                                               ; preds = %18
  ret i64 -1

21:                                               ; preds = %18
  br label %22

22:                                               ; preds = %21
  %23 = getelementptr i64, ptr %0, i64 0
  %24 = load i64, ptr %23, align 8
  %25 = add i64 %24, 1
  %26 = icmp ne i64 %1, %25
  br i1 %26, label %27, label %28

27:                                               ; preds = %22
  ret i64 -1

28:                                               ; preds = %22
  br label %29

29:                                               ; preds = %28
  call void @llvm.memset.p0.i64(ptr align 4 %6, i8 0, i64 512, i1 false)
  br label %30

30:                                               ; preds = %36, %29
  %31 = phi i64 [ 0, %29 ], [ %38, %36 ]
  %32 = icmp ult i64 %31, 128
  br i1 %32, label %33, label %35

33:                                               ; preds = %30
  %34 = icmp ult i64 %31, 128
  br i1 %34, label %36, label %39

35:                                               ; preds = %30
  br label %40

36:                                               ; preds = %33
  %37 = getelementptr [128 x i32], ptr %6, i64 0, i64 %31
  store i32 -1, ptr %37, align 4
  %38 = add i64 %31, 1
  br label %30

39:                                               ; preds = %33
  call void @llvm.trap()
  unreachable

40:                                               ; preds = %83, %35
  %41 = phi i32 [ 0, %35 ], [ %84, %83 ]
  %42 = phi i64 [ 0, %35 ], [ %85, %83 ]
  %43 = icmp ult i64 %42, %24
  br i1 %43, label %44, label %49

44:                                               ; preds = %40
  %45 = add i64 %42, 1
  %46 = getelementptr i64, ptr %0, i64 %45
  %47 = load i64, ptr %46, align 8
  %48 = icmp slt i64 %47, 0
  br i1 %48, label %55, label %53

49:                                               ; preds = %40
  %50 = mul i64 4, %24
  %51 = add i64 %50, 1
  %52 = icmp eq ptr %2, null
  br i1 %52, label %96, label %94

53:                                               ; preds = %44
  %54 = icmp sgt i64 %47, 127
  br label %55

55:                                               ; preds = %53, %44
  %56 = phi i1 [ true, %44 ], [ %54, %53 ]
  br i1 %56, label %57, label %58

57:                                               ; preds = %55
  ret i64 -1

58:                                               ; preds = %55
  br label %59

59:                                               ; preds = %58
  %60 = icmp sge i64 %47, 97
  br i1 %60, label %61, label %63

61:                                               ; preds = %59
  %62 = icmp sle i64 %47, 122
  br label %63

63:                                               ; preds = %61, %59
  %64 = phi i1 [ %62, %61 ], [ false, %59 ]
  br i1 %64, label %65, label %69

65:                                               ; preds = %63
  %66 = call { i64, i1 } @llvm.ssub.with.overflow.i64(i64 %47, i64 32)
  %67 = extractvalue { i64, i1 } %66, 0
  %68 = extractvalue { i64, i1 } %66, 1
  br i1 %68, label %73, label %74

69:                                               ; preds = %63
  br label %70

70:                                               ; preds = %74, %69
  %71 = phi i64 [ %67, %74 ], [ %47, %69 ]
  %72 = icmp ult i64 %71, 128
  br i1 %72, label %75, label %79

73:                                               ; preds = %65
  call void @llvm.trap()
  unreachable

74:                                               ; preds = %65
  br label %70

75:                                               ; preds = %70
  %76 = getelementptr [128 x i32], ptr %6, i64 0, i64 %71
  %77 = load i32, ptr %76, align 4
  %78 = icmp slt i32 %77, 0
  br i1 %78, label %80, label %82

79:                                               ; preds = %70
  call void @llvm.trap()
  unreachable

80:                                               ; preds = %75
  %81 = icmp ult i64 %71, 128
  br i1 %81, label %86, label %91

82:                                               ; preds = %75
  br label %83

83:                                               ; preds = %93, %82
  %84 = phi i32 [ %89, %93 ], [ %41, %82 ]
  %85 = add i64 %42, 1
  br label %40

86:                                               ; preds = %80
  %87 = getelementptr [128 x i32], ptr %6, i64 0, i64 %71
  store i32 %41, ptr %87, align 4
  %88 = call { i32, i1 } @llvm.sadd.with.overflow.i32(i32 %41, i32 1)
  %89 = extractvalue { i32, i1 } %88, 0
  %90 = extractvalue { i32, i1 } %88, 1
  br i1 %90, label %92, label %93

91:                                               ; preds = %80
  call void @llvm.trap()
  unreachable

92:                                               ; preds = %86
  call void @llvm.trap()
  unreachable

93:                                               ; preds = %86
  br label %83

94:                                               ; preds = %49
  %95 = icmp ult i64 %3, %51
  br label %96

96:                                               ; preds = %94, %49
  %97 = phi i1 [ true, %49 ], [ %95, %94 ]
  br i1 %97, label %98, label %99

98:                                               ; preds = %96
  ret i64 -2

99:                                               ; preds = %96
  br label %100

100:                                              ; preds = %99
  br label %101

101:                                              ; preds = %169, %100
  %102 = phi i64 [ 0, %100 ], [ %162, %169 ]
  %103 = phi i64 [ 0, %100 ], [ %170, %169 ]
  %104 = icmp ult i64 %103, %24
  br i1 %104, label %105, label %110

105:                                              ; preds = %101
  %106 = add i64 %103, 1
  %107 = getelementptr i64, ptr %0, i64 %106
  %108 = load i64, ptr %107, align 8
  %109 = icmp sge i64 %108, 97
  br i1 %109, label %112, label %114

110:                                              ; preds = %101
  %111 = getelementptr i8, ptr %2, i64 %102
  store i8 0, ptr %111, align 1
  ret i64 %102

112:                                              ; preds = %105
  %113 = icmp sle i64 %108, 122
  br label %114

114:                                              ; preds = %112, %105
  %115 = phi i1 [ %113, %112 ], [ false, %105 ]
  br i1 %115, label %116, label %120

116:                                              ; preds = %114
  %117 = call { i64, i1 } @llvm.ssub.with.overflow.i64(i64 %108, i64 32)
  %118 = extractvalue { i64, i1 } %117, 0
  %119 = extractvalue { i64, i1 } %117, 1
  br i1 %119, label %124, label %125

120:                                              ; preds = %114
  br label %121

121:                                              ; preds = %125, %120
  %122 = phi i64 [ %118, %125 ], [ %108, %120 ]
  %123 = icmp ugt i64 %103, 0
  br i1 %123, label %126, label %129

124:                                              ; preds = %116
  call void @llvm.trap()
  unreachable

125:                                              ; preds = %116
  br label %121

126:                                              ; preds = %121
  %127 = getelementptr i8, ptr %2, i64 %102
  store i8 46, ptr %127, align 1
  %128 = add i64 %102, 1
  br label %130

129:                                              ; preds = %121
  br label %130

130:                                              ; preds = %129, %126
  %131 = phi i64 [ %128, %126 ], [ %102, %129 ]
  %132 = icmp ult i64 %122, 128
  br i1 %132, label %133, label %136

133:                                              ; preds = %130
  %134 = getelementptr [128 x i32], ptr %6, i64 0, i64 %122
  %135 = load i32, ptr %134, align 4
  store [3 x i8] zeroinitializer, ptr %5, align 1
  br label %137

136:                                              ; preds = %130
  call void @llvm.trap()
  unreachable

137:                                              ; preds = %160, %133
  %138 = phi i32 [ %135, %133 ], [ %146, %160 ]
  %139 = phi i64 [ 0, %133 ], [ %156, %160 ]
  br label %140

140:                                              ; preds = %137
  %141 = icmp ult i64 %139, 3
  br i1 %141, label %143, label %152

142:                                              ; preds = %158
  br label %161

143:                                              ; preds = %140
  %144 = getelementptr [3 x i8], ptr %5, i64 0, i64 %139
  %145 = freeze i32 %138
  %146 = sdiv i32 %145, 10
  %147 = mul i32 %146, 10
  %148 = sub i32 %145, %147
  %149 = call { i32, i1 } @llvm.sadd.with.overflow.i32(i32 48, i32 %148)
  %150 = extractvalue { i32, i1 } %149, 0
  %151 = extractvalue { i32, i1 } %149, 1
  br i1 %151, label %153, label %154

152:                                              ; preds = %140
  call void @llvm.trap()
  unreachable

153:                                              ; preds = %143
  call void @llvm.trap()
  unreachable

154:                                              ; preds = %143
  %155 = trunc i32 %150 to i8
  store i8 %155, ptr %144, align 1
  %156 = add i64 %139, 1
  %157 = icmp eq i32 %146, 0
  br i1 %157, label %158, label %159

158:                                              ; preds = %154
  br label %142

159:                                              ; preds = %154
  br label %160

160:                                              ; preds = %159
  br label %137

161:                                              ; preds = %171, %142
  %162 = phi i64 [ %131, %142 ], [ %174, %171 ]
  %163 = phi i64 [ %156, %142 ], [ %166, %171 ]
  %164 = icmp ugt i64 %163, 0
  br i1 %164, label %165, label %169

165:                                              ; preds = %161
  %166 = sub i64 %163, 1
  %167 = getelementptr i8, ptr %2, i64 %162
  %168 = icmp ult i64 %166, 3
  br i1 %168, label %171, label %175

169:                                              ; preds = %161
  %170 = add i64 %103, 1
  br label %101

171:                                              ; preds = %165
  %172 = getelementptr [3 x i8], ptr %5, i64 0, i64 %166
  %173 = load i8, ptr %172, align 1
  store i8 %173, ptr %167, align 1
  %174 = add i64 %162, 1
  br label %161

175:                                              ; preds = %165
  call void @llvm.trap()
  unreachable
}

; Function Attrs: cold noreturn nounwind memory(inaccessiblemem: write)
declare void @llvm.trap() #1

; Function Attrs: nocallback nocreateundeforpoison nofree nosync nounwind speculatable willreturn memory(none)
declare { i64, i1 } @llvm.ssub.with.overflow.i64(i64, i64) #2

; Function Attrs: nocallback nocreateundeforpoison nofree nosync nounwind speculatable willreturn memory(none)
declare { i32, i1 } @llvm.sadd.with.overflow.i32(i32, i32) #2

; Function Attrs: nocallback nofree nosync nounwind willreturn memory(argmem: write)
declare void @llvm.memset.p0.i64(ptr writeonly captures(none), i8, i64, i1 immarg) #3

attributes #0 = { nounwind }
attributes #1 = { cold noreturn nounwind memory(inaccessiblemem: write) }
attributes #2 = { nocallback nocreateundeforpoison nofree nosync nounwind speculatable willreturn memory(none) }
attributes #3 = { nocallback nofree nosync nounwind willreturn memory(argmem: write) }
