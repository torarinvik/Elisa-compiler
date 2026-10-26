"""Field default type/kind metadata must belong to the exact field token."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
PARSER = (ROOT / "src/parser/parser_types_struct.elisa").read_text()
CHECKER = (ROOT / "src/semantic/check_field_default_type.elisa").read_text()
FIXTURE = (ROOT / "test/repro/field_default_type_owner_line_zero.elisa").read_text()
SMOKE = (ROOT / "test/parity/diagnostics_smoke.sh").read_text()
TYPE_HEAD_FIXTURE = (ROOT / "test/repro/field_default_type_mutable_parens.elisa").read_text()
TYPE_HEAD_SMOKE = (ROOT / "test/parity/field_default_type_head_smoke.sh").read_text()
AST_TESTS = (ROOT / "test/parity/parser_ast_decls.elisa").read_text()


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


parser = function_source(PARSER, "struct_member_block")
lookup = function_source(CHECKER, "fdt_value_at")
checker = function_source(CHECKER, "check_field_default_type")

for marker in ("__field_default_name", "__field_default_type", "__field_default_kind"):
    rows = re.findall(rf'Ast::EnumAnnotation\{{owner: "{re.escape(marker)}",[^}}]*\}}', parser)
    if len(rows) != 1 or not all(fragment in rows[0] for fragment in (
        f'owner: "{marker}"',
        "line: member_name.line",
        "offset: member_name.start",
    )):
        raise SystemExit(f"field default {marker} row must be unique and use the field-name token line/offset")
type_row = re.search(r'Ast::EnumAnnotation\{owner: "__field_default_type",[^}]*\}', parser)
if type_row is None or "name: field_default_type_name" not in type_row.group(0):
    raise SystemExit("field default type row must use the normalized parsed type head")
if "field_default_type_name: sview = field_default_type_head(member_type_value, type_head_text)" not in parser:
    raise SystemExit("field default metadata must call the parsed type-head normalizer")
type_head = function_source(PARSER, "field_default_type_head")
if not all(fragment in type_head for fragment in (
    "Expr.Ident(name, _)",
    "Expr.Scope(_, name, _)",
    "Expr.Paren(inner, _) | Expr.Unary(_, inner, _) | Expr.Refinement(inner, _, _)",
    "Expr.Index(object, _, _) | Expr.IndexN(object, _, _)",
    "return fallback",
)):
    raise SystemExit("field default type-head normalization must peel wrappers and generic arguments")
if "owner_offset: u32" not in lookup or "annotation.offset == owner_offset" not in lookup:
    raise SystemExit("field default lookup must match the exact field owner offset")
if 'fdt_value_at(file.enum_annotations, "__field_default_type", annotation.line, annotation.offset)' not in checker or \
        'fdt_value_at(file.enum_annotations, "__field_default_kind", annotation.line, annotation.offset)' not in checker:
    raise SystemExit("field default type and kind lookups must use the name row's source offset")
if FIXTURE.count("#line 0 field-default-owner.elisa") != 3 or \
        "good: i64 = 1" not in FIXTURE or "bad: bool = 1" not in FIXTURE or \
        "mutable_bad: mutable bool = 1" not in FIXTURE or \
        "field_default_type_owner_line_zero.elisa" not in SMOKE:
    raise SystemExit("line-zero fixture must pair a valid and invalid field default on one logical line in diagnostics smoke")
if not all(fragment in TYPE_HEAD_FIXTURE for fragment in (
    "paren_bad: (bool) = 1",
    "mutable_paren_bad: mutable (bool) = 1",
    'mutable_values: mutable darray[i64] = "text"',
)) or "test_field_default_type_head_unwraps_wrappers" not in AST_TESTS:
    raise SystemExit("type-head regression must cover parenthesized, mutable-parenthesized, and generic mutable field types")
if "field_default_type_mutable_parens.elisa" not in TYPE_HEAD_SMOKE or \
        TYPE_HEAD_SMOKE.count("expects bool, got int") < 2:
    raise SystemExit("isolated type-head smoke must check both parenthesized primitive mismatch diagnostics")

print("field default owner-offset source checks passed")
