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
SMOKE = (ROOT / "test/parity/effect_handler_stage1_smoke.sh").read_text()


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
        "error_union_family_of(union_expected,structs)!=direct_error_family",
        "iffns.is_extern[fn_index.usize()]andnotfns.is_error[fn_index.usize()]",
        "add_call_type_attribute(call_result",
        "emit_extern_ensure_checks",
        "LLVMBuildInsertValue(builder,union_value,call_result,0",
        "LLVMBuildInsertValue(builder,union_value,error_out_slot,1")) or \
        not (core.find("add_call_type_attribute(call_result") < core.find("emit_extern_ensure_checks") < package_at):
    raise SystemExit("indexed ErrorUnion packaging must validate exact row facts and preserve status/out-slot after call attrs and ensures")

if "emit_direct_call_indexed_as_error_union" not in compact(CALL_DIRECT) or \
        "emit_error_union_call_value(error_value_name,call_arguments,call_argument_names,expected" not in compact(EXPR_CALL) or \
        "emit_error_union_call_value(try_var_name,try_var_args,try_var_arg_names,declared_type" not in compact(VARS) or \
        "emit_error_union_call_value_from_callee(assign_try_callee,assign_try_args,assign_try_names" not in compact(ASSIGN):
    raise SystemExit("all ErrorUnion materialization sites must forward named labels")

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
