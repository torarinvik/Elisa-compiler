from pathlib import Path


root = Path(__file__).resolve().parents[2]
return_source = (root / "src/backend/codegen_stmt_return_vardecl_emit.elisa").read_text()
try_source = (root / "src/backend/codegen_try_lowering.elisa").read_text()
parameter_control = (root / "test/fixtures/backend/return_error_union_local_forwarding.elisa").read_text()
subset_control = (root / "test/fixtures/backend/return_error_union_local_source_forwarding.elisa").read_text()
minimal_fixture = (root / "test/fixtures/backend/return_error_union_local_forwarding_minimal.elisa").read_text()
full_fixture = (root / "test/fixtures/backend/return_error_union_local_source_full_family.elisa").read_text()
smoke = (root / "test/parity/backend_error_union_local_forwarding_smoke.sh").read_text()

forward_start = return_source.index("if forwarded_type.kind == TypeKind.ErrorUnion:")
forward_end = return_source.index("# A direct large-aggregate call", forward_start)
forward = return_source[forward_start:forward_end]
assert "forwarded_payload_type.kind != TypeKind.Void" in forward
assert "emit_propagating_error_union_value_try(forwarded_union, forwarded_type" in forward
assert "LLVMBuildLoad2" not in forward
assert "emit_ensure_checks(forwarded_success" in forward
assert "emit_deferred_actions(local_scope, false" in forward
assert "emit_region_unwind(regions" in forward
assert "LLVMBuildStore(builder, forwarded_success, runtime.error_out)" in forward
assert "LLVMBuildRet(builder, error_success_return_value(structs, runtime, ctx))" in forward

helper_start = try_source.index("def emit_propagating_error_union_value_try(")
helper_end = try_source.index("# `try f(args)`", helper_start)
helper = try_source[helper_start:helper_end]
failure_start = helper.index("LLVMPositionBuilderAtEnd(builder, union_failure_block)")
success_start = helper.index("LLVMPositionBuilderAtEnd(builder, union_success_block)")
failure = helper[failure_start:success_start]
success = helper[success_start:]
assert "emit_deferred_actions" in failure
assert "emit_region_unwind" in failure
assert "LLVMBuildRet(builder, forwarded_union_status)" in failure
assert "LLVMBuildLoad2(builder, union_payload_llvm, union_payload_pointer" not in failure
assert "LLVMBuildLoad2(builder, union_payload_llvm, union_payload_pointer" in success

assert "error[E]" in minimal_fixture and "def bad() -> i64 error[E]:" in minimal_fixture
assert "def forward() -> i64 error[E]:" in minimal_fixture
assert "value: i64 error[E] = bad()" in minimal_fixture and "return value" in minimal_fixture
assert "return try forward() else 42" in minimal_fixture
assert "Global" not in minimal_fixture

assert "def produce(fail: bool) -> i64 error[Fault]:" in full_fixture
assert "source: i64 error[Fault] = produce(fail)" in full_fixture
assert "def forward_local(fail: bool) -> i64 error[Fault]" in full_fixture
assert "defer block:" in full_fixture and "return source" in full_fixture
assert "error[Fault{Busy}]" not in full_fixture
assert "inspect_local(false) != 42" in full_fixture and "inspect_local(true) != 9" in full_fixture
assert full_fixture.count("trace != 1") == 2

# The subset and parameter paths now have native regression coverage too.
assert "value: i64 error[Fault{Busy}]" in parameter_control
assert "source: i64 error[Fault{Busy}] = produce(fail)" in subset_control
positive_loop = smoke[smoke.index("for level in 0 2;"):smoke.index("ir=\"$WORK/full-family-stage1-O0.ll\"")]
assert "return_error_union_local_forwarding_minimal.elisa" in positive_loop
assert "return_error_union_local_source_full_family.elisa" in positive_loop
assert "return_error_union_local_source_forwarding.elisa" in positive_loop
assert "return_error_union_local_forwarding.elisa" in positive_loop

assert "-emit exe" in smoke and "elisa_run_timeout 10" in smoke
assert "check_failure_payload_order \"$ir\" forward_local" in smoke
assert "try\\.union\\.payload\\.ptr" in smoke and "try.union.success.payload" in smoke
assert "try.union.success" in smoke and "CFG reaches its success/done block" in smoke

print("source proof passed: helper cleanup, forwarding cases, and native/IR smoke coverage")
