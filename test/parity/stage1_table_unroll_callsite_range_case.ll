declare i64 @table_unroll_range_identity(i64)
define i64 @callsite_range_attribute(i64 %input) {
entry:
  %result = call i64 @table_unroll_range_identity(i64 range(i64 0, 512) %input)
  ret i64 %result
}
