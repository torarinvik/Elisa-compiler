"""Guard the source lifetime of arrow-lambda body buffers and their runtime controls."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CURSOR = ROOT / "src/parser/parser_core_cursor.elisa"
EXPR = ROOT / "src/parser/parser_expr_query.elisa"
SMOKE = ROOT / "test/parity/backend_smoke_behavior.sh"
CLI_SMOKE = ROOT / "test/parity/lambda_body_source_region_smoke.sh"
GATE = ROOT / "test/parity/run_all.sh"
FIXTURES = ROOT / "test/fixtures/backend/lambda_body_source"


def compact(text: str) -> str:
    return "".join(line.split("#", 1)[0] for line in text.splitlines()).replace(" ", "").replace("\t", "").replace("\n", "")


cursor = compact(CURSOR.read_text())
expr = compact(EXPR.read_text())
smoke = SMOKE.read_text()
cli_smoke = CLI_SMOKE.read_text()
gate = GATE.read_text()

body_helper = "defsingle_statement_body(parser:lmutParser,only_statement:Ast::Stmt)->darray[Ast::Stmt]@source:"
if body_helper not in cursor:
    raise SystemExit("single-statement lambda bodies must return the source-owned statement array")
if "body:mutabledarray[Ast::Stmt]@source=[]body.push(only_statement)returnbody" not in cursor:
    raise SystemExit("single_statement_body must construct and return its buffer in @source")
if "return[only_statement]" in cursor:
    raise SystemExit("single_statement_body must not return a short-lived list literal")

if "body:mutabledarray[Ast::Stmt]@source=[]" not in expr:
    raise SystemExit("lambda_expression must keep its body buffer source-owned")
if "body,parser<-parser.single_statement_body((Ast::Stmt.Return(return_value,Ast::pos_of_token(value_token))))" not in expr:
    raise SystemExit("arrow lambda expressions must route their return through single_statement_body")
if "return(Ast::Expr.Lambda(parameters,body,Ast::pos_of_token(token)))" not in expr:
    raise SystemExit("the packed lambda node must retain its source token position")

expected_shapes = {
    "plain_arrow.elisa": ("fn() -> i64 => 17", "return callback()"),
    "plain_block.elisa": ("callback: fn() -> i64 = fn() -> i64:", "return apply(callback)"),
    "fallible_arrow.elisa": ("callback: fn() -> i64 error[E] = fn() -> i64 error[E] => 7", "try apply(callback)"),
    "fallible_block.elisa": ("callback: fn() -> i64 error[E] = fn() -> i64 error[E]:", "try apply(callback)"),
}
for filename, required in expected_shapes.items():
    source = (FIXTURES / filename).read_text()
    for fragment in required:
        if fragment not in source:
            raise SystemExit(f"{filename} lost its parser/backend control shape: {fragment}")

for name in (
    "lambda_body_plain_arrow",
    "lambda_body_plain_block",
    "lambda_body_fallible_arrow",
    "lambda_body_fallible_block",
):
    if f"run_fixture_case {name} " not in smoke:
        raise SystemExit(f"backend behavior smoke does not register {name}")
if 'python3 "$ROOT/test/proofs/check_lambda_arrow_body_source_region.py"' not in smoke:
    raise SystemExit("backend behavior smoke must run the lambda body source proof")
if 'python3 "$ROOT/test/proofs/check_lambda_arrow_body_source_region.py"' not in cli_smoke or \
        'bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"' not in cli_smoke or \
        '"$STAGE1" -emit exe "-O$optimization"' not in cli_smoke:
    raise SystemExit("full CLI smoke must run freshness, source proof, and optimized executable checks")
if "for optimization in 0 2" not in cli_smoke:
    raise SystemExit("full CLI lambda body smoke must cover both O0 and O2")
if "lambda_body_source_region_smoke.sh" not in gate or \
        'for smoke in "$REPO_ROOT"/test/parity/*_smoke.sh' not in gate:
    raise SystemExit("full parity gate discovery and backend profile must include the CLI smoke")

print("lambda arrow body source region proof passed")
