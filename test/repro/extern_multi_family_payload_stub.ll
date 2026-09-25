; LLVM-level ABI stub for the compiler parity smoke. The C struct-returning counterpart
; characterizes a separate native C ABI mismatch and must not be used as the parity oracle.
define { i32, i32 } @external_probe(ptr %out_value, i64 %code) {
entry:
  store i64 0, ptr %out_value, align 8
  %tag = insertvalue { i32, i32 } undef, i32 2, 0
  %payload = insertvalue { i32, i32 } %tag, i32 41, 1
  ret { i32, i32 } %payload
}
