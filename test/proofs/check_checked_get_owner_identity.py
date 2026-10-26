"""Checked-get exemptions must belong to the exact indexed expression."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
PARSER = (ROOT / "src/parser/parser_expr_query.elisa").read_text()
CHECKER = (ROOT / "src/semantic/check_index_else_fallback.elisa").read_text()
TUPLE_CHECKER = (ROOT / "src/semantic/check_tuple_var_scalar_mismatch.elisa").read_text()
OOB_CHECKER = (ROOT / "src/semantic/check_index_out_of_bounds.elisa").read_text()
STRICT_WALK = (ROOT / "src/semantic/check_strict_unsafe_ops_walk.elisa").read_text()
STRICT_VIEWS = (ROOT / "src/semantic/check_strict_unsafe_ops_views.elisa").read_text()
FIXTURE = (ROOT / "test/repro/checked_get_owner_line_zero.elisa").read_text()
CONSUMER_FIXTURE = (ROOT / "test/repro/checked_get_owner_consumers_line_zero.elisa").read_text()
SMOKE = (ROOT / "test/parity/index_else_fallback_owner_smoke.sh").read_text()


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


index_position_helper = function_source(PARSER, "checked_get_index_position")
position_helper = function_source(PARSER, "checked_get_owner_position")
producer = function_source(PARSER, "get_expression")
lookup = function_source(CHECKER, "ief_index_is_checked_get")
check = function_source(CHECKER, "ief_check_expression")
tuple_walk = function_source(TUPLE_CHECKER, "check_nonscalar_var_statements")
tuple_entry = function_source(TUPLE_CHECKER, "check_tuple_var_scalar_mismatch")
oob_walk = function_source(OOB_CHECKER, "walk_expression_for_index_out_of_bounds")
oob_entry = function_source(OOB_CHECKER, "check_index_out_of_bounds")
strict_position = function_source(STRICT_WALK, "strict_unsafe_checked_index_position")
strict_expression = function_source(STRICT_WALK, "strict_unsafe_expression")
strict_entry = function_source(STRICT_VIEWS, "check_strict_unsafe_ops")

if "Expr.Index(_, _, index_position)" not in index_position_helper or \
        "Expr.Paren(inner, _)" not in index_position_helper or \
        "Expr.Binary(left, operator, _, _) if operator == TokenKind.Else" not in index_position_helper or \
        "false, Ast::expr_pos(expression)" not in index_position_helper or \
        "return Ast::expr_pos(expression)" not in position_helper:
    raise SystemExit("checked-get position helper must normalize Index forms and retain non-index roots")
if 'owner: "__checked_get"' not in producer or \
        "line: checked_get_position.line" not in producer or \
        "offset: checked_get_position.offset" not in producer or \
        "pos: checked_get_position" not in producer or \
        "checked_get_owner_position(checked_get_expression)" not in producer:
    raise SystemExit("checked-get metadata must retain the owning AST position")
if "position: Ast::Pos" not in lookup or \
        'annotation.owner == "__checked_get"' not in lookup or \
        "annotation.pos.line == position.line" not in lookup or \
        "annotation.pos.offset == position.offset" not in lookup:
    raise SystemExit("checked-get lookup must match the exact Index position")
if "ief_index_is_checked_get(annotations, index_line)" not in check:
    raise SystemExit("index fallback check must query the Binary's owning Index position")

if "annotation.pos for annotation in file.enum_annotations" not in tuple_entry or \
        "get_position.line == value_position.line" not in tuple_walk or \
        "get_position.offset == value_position.offset" not in tuple_walk or \
        "value_position: Ast::Pos = Ast::expr_pos(value)" not in tuple_walk or \
        "Expr.Paren(inner, _)" not in function_source(TUPLE_CHECKER, "ident_name_of"):
    raise SystemExit("tuple optional-unwrapping suppression must match the initializer's exact checked-get position")

if "annotation.pos for annotation in file.enum_annotations" not in oob_entry or \
        "g.line == line.line and g.offset == line.offset" not in oob_walk:
    raise SystemExit("out-of-bounds suppression must match the exact Index position")

if "annotation.pos" not in strict_entry or \
        "g.line == index_line.line and g.offset == index_line.offset" not in strict_expression:
    raise SystemExit("unchecked-index exemptions must match exact Index positions")
if "Expr.Index(_, _, index_position)" not in strict_position or \
        "strict_unsafe_checked_index_position(guarded_value)" not in strict_expression or \
        "checked_positions.push(guarded_index.position)" not in strict_expression:
    raise SystemExit("control-flow GetElse must exempt only its guarded Index position")
if FIXTURE.count("#line 0 checked-get-owner.elisa") != 2 or \
        "value = get values[index] else 0" not in FIXTURE or \
        "value = values[index] else 0" not in FIXTURE:
    raise SystemExit("fixture must pair an explicit checked-get fallback with an implicit fallback on the same logical line")
if CONSUMER_FIXTURE.count("#line 0 checked-get-consumers.elisa") != 8 or \
        "get values[9] else 0" not in CONSUMER_FIXTURE or \
        "plain: i64 = values[9]" not in CONSUMER_FIXTURE or \
        "checked: i64 = get (maybe)" not in CONSUMER_FIXTURE or \
        "plain: i64 = maybe" not in CONSUMER_FIXTURE or \
        "checked: i64 = get values[index]" not in CONSUMER_FIXTURE or \
        "get values[index] else return 0" not in CONSUMER_FIXTURE:
    raise SystemExit("consumer fixture must cover OOB, optional unwrap, bare get, and GetElse same-line identities")
if "checked_get_owner_line_zero.elisa" not in SMOKE or \
        "checked_get_owner_consumers_line_zero.elisa" not in SMOKE or \
        "implicit `else` index fallback has been removed" not in SMOKE or \
        "constant index 9 out of bounds for i64[4]" not in SMOKE or \
        'variable "plain" expects i64, got i64?' not in SMOKE or \
        "unchecked index requires" not in SMOKE:
    raise SystemExit("smoke must require every unguarded same-line sibling diagnostic")

print("checked-get owner-offset source checks passed")
