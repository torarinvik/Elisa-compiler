"""Bind handler-capture annotation decisions to source owners, not #line values."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src/semantic/check_handler_capture_escape.elisa"
WALK = ROOT / "src/semantic/check_handler_capture_escape_walk.elisa"
PARSER_STMT = ROOT / "src/parser/parser_stmt_control.elisa"
PARSER_FUNC = ROOT / "src/parser/parser_types_function.elisa"
FIXTURE = ROOT / "test/repro/handler_capture_escape/rejected/line_zero_annotation_owner_identity.elisa"
SMOKE = ROOT / "test/parity/handler_capture_escape_smoke.sh"


def compact(text: str) -> str:
    return "".join(line.split("#", 1)[0] for line in text.splitlines()).replace(" ", "").replace("\t", "").replace("\n", "")


source = compact(SOURCE.read_text())
walk = compact(WALK.read_text())
parser_stmt = compact(PARSER_STMT.read_text())
parser_func = compact(PARSER_FUNC.read_text())
fixture = FIXTURE.read_text()
smoke = SMOKE.read_text()

if "annotation.owner_offset==function_offset" not in source:
    raise SystemExit("callee region-bound lookup no longer checks the function declaration offset")
if "hce_callee_region_bound(parameters,line.line,line.offset,annotations)" not in source:
    raise SystemExit("callee region-bound lookup no longer receives Decl.Func's source offset")
if "pos.offset!=0" not in walk or "annotation.owner_offset==pos.offset" not in walk:
    raise SystemExit("local annotation lookup no longer checks the declared name's source offset")
if "owner_offset:name_token.start" not in parser_stmt or "Ast::pos_of_token(name_token)" not in parser_stmt:
    raise SystemExit("local annotation owner offsets no longer match VarDecl source positions")
if "active_function_region_offset<-token.start" not in parser_func or "Ast::pos_of_token(token)" not in parser_func:
    raise SystemExit("function annotation owner offsets no longer match Decl.Func source positions")

if fixture.count("#line 0 hce-owner-identity.elisa") != 3:
    raise SystemExit("regression fixture must put three declarations on logical line zero")
for fragment in (
    "def unrelated[@r](owner: mutable darray[u8]& @r) -> void:",
    "captures: mutable darray[Prm] @r = []",
    "def fill(items: mutable darray[Prm]&, bytes: mutable darray[u8]&) -> void:",
    "def handler(parser: mutable P&) -> void:",
    "captures: mutable darray[Prm] = []",
    "fill(captures, buf)",
    "parser.params.push(capture)",
):
    if fragment not in fixture:
        raise SystemExit(f"owner-identity fixture lost a required source shape: {fragment}")

if 'python3 "$ROOT/test/proofs/check_handler_capture_escape_owner_identity.py"' not in smoke:
    raise SystemExit("handler-capture smoke no longer runs the owner-identity source proof")
if '"$DIR"/rejected/*.elisa' not in smoke:
    raise SystemExit("handler-capture smoke no longer includes the line-zero regression fixture")

print("handler-capture annotation owner identity source checks passed")
