; LLVM-level ABI stub for the restricted two-family catch regression.
; Canonical family order is BarError then FooError, so BarError.Bad4 has tag 2.
define { i32, i32 } @foo(ptr %out_value) {
entry:
  store i64 0, ptr %out_value, align 8
  %tag = insertvalue { i32, i32 } undef, i32 2, 0
  %payload = insertvalue { i32, i32 } %tag, i32 42, 1
  ret { i32, i32 } %payload
}
