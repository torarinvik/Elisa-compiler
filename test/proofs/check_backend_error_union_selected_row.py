"""Source-bound regression guard for fallible overload ErrorUnion materialization."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OVERLOADS = (ROOT / "src/backend/codegen_overloads.elisa").read_text()
RETURN_TYPE = (ROOT / "src/backend/codegen_expression_type_place.elisa").read_text()
CALL = (ROOT / "src/backend/codegen_call.elisa").read_text()
CALL_DIRECT = (ROOT / "src/backend/codegen_call_direct.elisa").read_text()
TRY = (ROOT / "src/backend/codegen_try_lowering.elisa").read_text()
EXPR_CALL = (ROOT / "src/backend/codegen_expr_direct_call.elisa").read_text()
VARS = (ROOT / "src/backend/codegen_stmt_vardecl_emit.elisa").read_text()
ASSIGN = (ROOT / "src/backend/codegen_stmt_assign_place.elisa").read_text()
FIXTURE = (ROOT / "test/fixtures/effects/helper_error_union_overload_capture.elisa").read_text()
UNSUPPORTED_INIT = (ROOT / "test/fixtures/backend/extern_unsupported_ensure_initializer.elisa").read_text()
UNSUPPORTED_ASSIGN = (ROOT / "test/fixtures/backend/extern_unsupported_ensure_assignment.elisa").read_text()
UNSUPPORTED_ARG = (ROOT / "test/fixtures/backend/extern_unsupported_ensure_argument.elisa").read_text()
SMOKE = (ROOT / "test/parity/effect_handler_stage1_smoke.sh").read_text()
DECLINE_SMOKE = (ROOT / "test/parity/extern_unsupported_ensure_decline_smoke.sh").read_text()


def compact(text: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in text.splitlines())


if "resolved_call_function_index_at_depth" not in OVERLOADS or \
        "resolved_call_function_index_at_depth(fns,owner,name,arguments,argument_names,local_scope,structs,generics,depth)" not in compact(RETURN_TYPE) or \
        "resolved_call_function_index_at_depth(fns,callee_owner,callee_name,arguments,argument_names,local_scope,structs,generics,0)" not in compact(CALL):
    raise SystemExit("call typing and emission must share the concrete overload row selector")

union_start = TRY.find("def emit_error_union_call_value[")
union_end = TRY.find("def emit_error_union_call_value_from_callee", union_start)
if union_start < 0 or union_end < 0 or \
        "argument_names" not in compact(TRY[union_start:union_end]) or \
        "->(selected:bool,owner_row:i64)" not in compact(TRY) or \
        "selected_owner:sview=fns.owners[monomorphic_owner.owner_row.usize()]" not in compact(TRY) or \
        "monomorphic_owner.owner_row<0" not in compact(TRY) or \
        "emit_direct_call_indexed_as_error_union(fn_index,arguments,argument_names,expected" not in compact(CALL):
    raise SystemExit("ErrorUnion calls must retain named labels and resolve an ephemeral owner from its FnTable row")

core_start = CALL_DIRECT.find("def emit_direct_call_indexed_result[")
core_end = CALL_DIRECT.find("def emit_direct_call_indexed[", core_start)
core = compact(CALL_DIRECT[core_start:core_end])
package_at = core.rfind("iferror_union_expectedisunion_expected:")
if core_start < 0 or core_end < 0 or package_at < 0 or not all(fragment in core for fragment in (
        "notfns.is_error[fn_index.usize()]",
        "value_type_identity_equal(call_return_type,union_payload)",
        "noterror_status_remap_supported(direct_error_family,direct_error_expected_family,structs)",
        "iffns.is_extern[fn_index.usize()]andnotfns.is_error[fn_index.usize()]",
        "add_call_type_attribute(call_result",
        "emit_extern_ensure_checks",
        "direct_error_needs_remap",
        "remap_error_status(call_result,direct_error_family,direct_error_expected_family",
        "union_status<-remapped_direct_error_status",
        "LLVMBuildInsertValue(builder,union_value,union_status,0",
        "LLVMBuildInsertValue(builder,union_value,error_out_slot,1")) or \
        not (core.find("add_call_type_attribute(call_result") < core.find("emit_extern_ensure_checks") < package_at < core.find("remap_error_status(call_result") < core.find("LLVMBuildInsertValue(builder,union_value,union_status,0")):
    raise SystemExit("indexed ErrorUnion packaging must preserve the raw call through attributes/ensures, then remap union_status and retain the out slot")

if "emit_direct_call_indexed_as_error_union" not in compact(CALL_DIRECT) or \
        "->(selected:bool,value:LLVMValueRef?)" not in compact(TRY) or \
        "->(selected:bool,value:LLVMValueRef?)" not in compact(TRY[TRY.find("def emit_error_union_call_value_from_callee"):]) or \
        "union_var_call: (selected: bool, value: LLVMValueRef?) = emit_error_union_call_value(try_var_name, try_var_args, try_var_arg_names, declared_type" not in VARS or \
        "return EmitStatus.Declined if union_var_call.selected" not in VARS or \
        "assign_union_call: (selected: bool, value: LLVMValueRef?) = emit_error_union_call_value_from_callee(assign_try_callee, assign_try_args, assign_try_names" not in ASSIGN or \
        "return EmitStatus.Declined if assign_union_call.selected" not in ASSIGN or \
        "error_union_call: (selected: bool, value: LLVMValueRef?) = emit_error_union_call_value(error_value_name, call_arguments, call_argument_names, expected" not in EXPR_CALL or \
        "if error_union_call.selected:" not in EXPR_CALL or \
        "return error_union_call.value" not in EXPR_CALL or \
        "handled <- true" not in EXPR_CALL[EXPR_CALL.find("if error_union_call.selected:"):]:
    raise SystemExit("all ErrorUnion materialization sites must preserve selected-row failure instead of falling back")

unsupported = (UNSUPPORTED_INIT, UNSUPPORTED_ASSIGN, UNSUPPORTED_ARG)
for source in unsupported:
    if "extern contract_probe(input: i64) -> i64 error[ProbeError] ensure result == old(input)" not in source or \
            "error ProbeError:" not in source or "Failed" not in source:
        raise SystemExit("unsupported ensure controls must retain the fallible extern and missing old-snapshot predicate")
if "value: i64 error[ProbeError] = contract_probe(42)" not in UNSUPPORTED_INIT or \
        "return try run() else 7" not in UNSUPPORTED_INIT or \
        "value <- contract_probe(42)" not in UNSUPPORTED_ASSIGN or \
        "return try reassign(initial) else 7" not in UNSUPPORTED_ASSIGN or \
        "consume(contract_probe(42))" not in UNSUPPORTED_ARG or \
        "return try run() else 7" not in UNSUPPORTED_ARG:
    raise SystemExit("unsupported controls must reach initializer, assignment, and nested-argument callsites through live callers")
if "ELISA_DUMP_INVALID_IR" not in DECLINE_SMOKE or \
        "backend could not produce a linkable unit" not in DECLINE_SMOKE or \
        "does not have terminator" not in DECLINE_SMOKE or \
        "unterminated basic block" not in DECLINE_SMOKE or \
        "extern_unsupported_ensure_initializer.elisa" not in DECLINE_SMOKE or \
        "extern_unsupported_ensure_assignment.elisa" not in DECLINE_SMOKE or \
        "extern_unsupported_ensure_argument.elisa" not in DECLINE_SMOKE or \
        "for optimization in 0 2" not in DECLINE_SMOKE or \
        '-emit exe "-O$optimization"' not in DECLINE_SMOKE:
    raise SystemExit("focused smoke must check three clean declines and retain the supported O0/O2 ErrorUnion control")

if FIXTURE.count("def choose(value: ") != 2 or \
        "def choose(value: i64, code: i64 = 2) -> i64 error[FirstFault]" not in FIXTURE or \
        "def choose(value: bool, code: i64 = 2) -> i64 error[SecondFault]" not in FIXTURE or \
        "return 40 + code" not in FIXTURE or \
        "raise SecondFault.Chosen(code + 5)" not in FIXTURE or \
        "success = choose(code: 2, value: true)" not in FIXTURE or \
        "failure = choose(value: false)" not in FIXTURE or \
        "SecondFault.Chosen(code)" not in FIXTURE or \
        'run_positive "helper_error_union_overload_capture.elisa"' not in SMOKE or \
        'run_native_result "helper_error_union_overload_capture.elisa" 42' not in SMOKE:
    raise SystemExit("overload regression must check both the selected success payload and selected family tag")

print("backend ErrorUnion selected-row source proof OK")
