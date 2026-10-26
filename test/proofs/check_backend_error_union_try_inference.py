"""Source-bound guard for exact-site inferred `try` payload typing."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PARSER = (ROOT / "src/parser/parser_expr_query.elisa").read_text()
TABLE = (ROOT / "src/backend/codegen_struct_table.elisa").read_text()
ENV = (ROOT / "src/backend/codegen_env.elisa").read_text()
QUERIES = (ROOT / "src/backend/codegen_env_source_queries.elisa").read_text()
VARDECL = (ROOT / "src/backend/codegen_stmt_vardecl_emit.elisa").read_text()
ASSIGN = (ROOT / "src/backend/codegen_stmt_assign_place.elisa").read_text()
TRY_LOWERING = (ROOT / "src/backend/codegen_try_lowering.elisa").read_text()
FIXTURE = (ROOT / "test/fixtures/effects/helper_inferred_try_binding.elisa").read_text()
CAPTURE_FIXTURE = (ROOT / "test/fixtures/effects/helper_error_union_capture.elisa").read_text()
SMOKE = (ROOT / "test/parity/effect_handler_stage1_smoke.sh").read_text()


def compact(text: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in text.splitlines())


if "owner:\"__try_propagating_expr\"" not in compact(PARSER) or \
        "propagating_expr_pos:Ast::Pos=Ast::expr_pos(try_expression)" not in compact(PARSER) or \
        "offset:propagating_expr_pos.offset" not in compact(PARSER):
    raise SystemExit("parser must retain the exact raw root offset for erased no-else try expressions")

if "propagating_try_call_offsets:mutabledarray[u32]=[]" not in compact(TABLE) or \
        "ifannotation.owner==\"__try_propagating_expr\"" not in compact(ENV) or \
        "propagating_try_call_offsets.push(annotation.offset)" not in compact(ENV):
    raise SystemExit("backend must retain expression-site offsets without changing the offset-vector layout")

query = compact(QUERIES)
if "defpropagating_try_expr_at(offset:u32,structs:mutableStructTable&)" not in query or \
        "returnfalseifoffset==0" not in query or \
        "propagating_try_call_offsets[probe]==offset" not in query or \
        "propagating_try_call_modules" in query:
    raise SystemExit("backend try-site lookup must use nonzero raw offset only, not logical line or emitted owner")

vardecl = compact(VARDECL)
if "var_typeisExpr.Invalid" not in vardecl or \
        "declared_type.kind==TypeKind.ErrorUnion" not in vardecl or \
        "declared_type<-error_union_payload_of(declared_type,structs)" not in vardecl or \
        "propagating_try_expr_at(inferred_try_pos.offset,structs)" not in vardecl:
    raise SystemExit("only an unannotated VarDecl at the exact try expression may infer its success payload")
if "emit_propagating_error_union_value_try(marked_try_union,marked_try_type" not in vardecl or \
        "value_type_identity_equal(marked_try_payload,declared_type)" not in vardecl or \
        "declared_type.kind!=TypeKind.ErrorUnion" not in vardecl:
    raise SystemExit("marked non-Call try values must propagate only when payload identity matches the destination")

assign = compact(ASSIGN)
if "propagating_try_expr_at(inferred_try_pos.offset,structs)" not in assign or \
        "Stmt.VarDecl(new_local_name,Expr.Invalid,assign_value,new_local_line)" not in assign:
    raise SystemExit("bare first-assignment try expressions must reuse the VarDecl propagating-try lowering")

try_lowering = compact(TRY_LOWERING)
shared_propagation = try_lowering[try_lowering.index("defemit_propagating_error_union_value_try("):try_lowering.index("defemit_propagating_fn_value_try(")]
if "emit_deferred_actions(local_scope,false" not in shared_propagation or \
        "emit_region_unwind(regions" not in shared_propagation or \
        "remap_error_status(union_status,union_error_family,union_return_family" not in shared_propagation or \
        "LLVMBuildStore(builder,union_failed_payload,runtime.error_out)" in shared_propagation or \
        "emit_propagating_error_union_value_try(fn_union_value,fn_result_type" not in try_lowering:
    raise SystemExit("first-class union propagation must share defer, unwind, status forwarding, and avoid source-width error-out stores")

if FIXTURE.count("def make(") != 1 or \
        FIXTURE.count("#line 80 inferred-try-site.elisa") != 2 or \
        "captured = make(value)" not in FIXTURE or \
        "propagated = try make(value)" not in FIXTURE or \
        "return captured_payload + propagated" not in FIXTURE or \
        "failed: i64 = try exercise(false) else 50" not in FIXTURE or \
        "return success + failed" not in FIXTURE or \
        'run_positive "helper_inferred_try_binding.elisa"' not in SMOKE or \
        'run_native_result "helper_inferred_try_binding.elisa" 130' not in SMOKE:
    raise SystemExit("runtime fixture must cover plain ErrorUnion capture beside inferred success/failure propagation")

if "payload: i64 = try value" not in CAPTURE_FIXTURE or \
        "def make_failure() -> i64 error[CaptureError]" not in CAPTURE_FIXTURE or \
        "def success_case()" not in CAPTURE_FIXTURE or \
        "def failure_case()" not in CAPTURE_FIXTURE or \
        "def bool_error_caller(value: i64 error[CaptureError]) -> bool error[CaptureError]" not in CAPTURE_FIXTURE or \
        "def bool_success_case()" not in CAPTURE_FIXTURE or \
        "def bool_failure_case()" not in CAPTURE_FIXTURE or \
        "return success_case() + failure_case() + bool_success_case() + bool_failure_case()" not in CAPTURE_FIXTURE or \
        'run_native_result "helper_error_union_capture.elisa" 42' not in SMOKE:
    raise SystemExit("handler capture regression must cover both union success and failure with result 42")

plain_offset = FIXTURE.index("captured = make(value)")
try_offset = FIXTURE.index("propagated = try make(value)")
if plain_offset == try_offset:
    raise SystemExit("plain call and try call must occupy distinct raw source offsets")

print("backend ErrorUnion inferred-try source proof OK")
