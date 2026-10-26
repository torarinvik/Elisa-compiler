"""Keep discarded-lambda context markers tied to the lambda's source token."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PARSER = ROOT / "src/parser/parser_expr_query.elisa"
CONSUMER = ROOT / "src/semantic/check_block_lambda_context.elisa"
FIXTURE = ROOT / "test/repro/block_lambda_context_owner_line_collision.elisa"
SMOKE = ROOT / "test/parity/block_lambda_context_smoke.sh"


def compact(text: str) -> str:
    return "".join(line.split("#", 1)[0] for line in text.splitlines()).replace(" ", "").replace("\t", "").replace("\n", "")


parser = compact(PARSER.read_text())
consumer = compact(CONSUMER.read_text())
fixture = FIXTURE.read_text()
smoke = SMOKE.read_text()

for marker in ("__block_lambda", "__typed_lambda"):
    if f'name:"{marker}",line:token.line,offset:token.start' not in parser:
        raise SystemExit(f"{marker} marker must record the lambda token offset")
if "return(Ast::Expr.Lambda(parameters,body,Ast::pos_of_token(token)))" not in parser:
    raise SystemExit("lambda AST position must remain the exact marker owner position")
if "position:Ast::Pos" not in consumer or "annotation.offset==position.offset" not in consumer:
    raise SystemExit("lambda marker lookup must match the exact AST position, including offset zero")
if 'lambda_marker_at(annotations,"__block_lambda",lambda_position)' not in consumer:
    raise SystemExit("block lambda lookup must use Expr.Lambda's source position")
if 'lambda_marker_at(annotations,"__typed_lambda",lambda_position)' not in consumer:
    raise SystemExit("typed lambda lookup must use Expr.Lambda's source position")

if fixture.count("#line 60 ") != 2:
    raise SystemExit("collision fixture must put two lambda owners on the same logical line")
for fragment in ("_ = fn():", "_ = fn() -> i64 => 1"):
    if fragment not in fixture:
        raise SystemExit(f"collision fixture lost a required lambda shape: {fragment}")
if 'python3 "$REPO_ROOT/test/proofs/check_block_lambda_context_owner_identity.py"' not in smoke:
    raise SystemExit("block-lambda smoke must run the owner-identity source proof")
if '"$RPT" < "$REPO_ROOT/test/repro/block_lambda_context_owner_line_collision.elisa"' not in smoke:
    raise SystemExit("block-lambda smoke must cover the same-line owner collision fixture")

print("block lambda context owner identity source proof passed")
