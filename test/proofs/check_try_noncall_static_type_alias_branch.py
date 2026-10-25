"""Bind Try's cached alias facts to exact static-if alias declarations."""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
CALLABLE_ROWS = (ROOT / "src/semantic/check_try_fallible/callable_rows.elisa").read_text()
NONCALL = (ROOT / "src/semantic/check_try_fallible/noncall_scan.elisa").read_text()
FALLBACK = (ROOT / "src/semantic/check_try_fallible/fallback_casts.elisa").read_text()
PARSER_DISPATCH = (ROOT / "src/parser/parser_decl_dispatch.elisa").read_text()
PARSER_LAW = (ROOT / "src/parser/parser_decl_law.elisa").read_text()
FIXTURE = (ROOT / "test/repro/try_noncall_static_type_alias_branch.elisa").read_text()
SMOKE = (ROOT / "test/parity/try_noncall_static_type_alias_branch_smoke.sh").read_text()


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


inactive_alias = function_source(CALLABLE_ROWS, "try_noncall_type_alias_declaration_is_static_inactive")
collect_aliases = function_source(CALLABLE_ROWS, "try_noncall_type_alias_facts_add")
inactive_scope = function_source(CALLABLE_ROWS, "try_noncall_static_scope_is_inactive")
binding = function_source(NONCALL, "try_noncall_binding_at_site")
parameter_binding = function_source(NONCALL, "try_noncall_parameter_error_family")
rows = function_source(NONCALL, "check_try_fallible_rows")

if not all(fragment in inactive_alias for fragment in (
    'marker.owner != "__static_if_branch"',
    'marker.name != "__type_alias_static_branch"',
    "marker.detail_name != alias_name",
    "marker.module != current_module",
    "marker.line != declaration_line",
    "marker.offset != declaration_offset",
    "marker.identity_id == 4294967295",
    "unresolved_branch <- true",
    "pma_static_if_row_selection(file, marker.identity_id.usize(), marker.module, table)",
    "return true if branch.known and not branch.selected",
    "return false",
)):
    raise SystemExit("Try must exclude only aliases proven inactive by their exact branch marker")

if not all(fragment in collect_aliases for fragment in (
    "file: Ast::File&",
    "annotations: darray[Ast::EnumAnnotation]&",
    "alias_position.line",
    "alias_position.offset",
    "try_noncall_type_alias_declaration_is_static_inactive",
    "try_noncall_type_alias_facts_add(file, module_body, annotations",
    "try_noncall_type_alias_facts_add(file, scoped_body, annotations",
    "Decl.Scoped(scoped_body, scope_position)",
    "continue if try_noncall_static_scope_is_inactive(file, scope_position, current_module, table)",
)) or not all(fragment in inactive_scope for fragment in (
    "pma_static_if_row_for_position(file, scope_position)",
    "pma_static_if_row_selection(file, branch_row, current_module, table)",
    "return branch.known and not branch.selected",
)) or not all(fragment in body for body in (binding, parameter_binding, rows) for fragment in ("file: Ast::File&",)):
    raise SystemExit("Try must thread the source file and annotations through cached alias construction")

if not all('record_static_if_branch_rows("__type_alias_static_branch", alias_name, token)' in source for source in (PARSER_DISPATCH, PARSER_LAW)):
    raise SystemExit("both type and refine aliases must emit exact static-branch rows")
if not all(fragment in FIXTURE for fragment in (
    "static if USE_INTEGER_PAYLOAD:",
    "static if USE_NESTED_INTEGER_PAYLOAD:",
    "type Payload = bool",
    "type Payload = i64",
    "static else:",
    "type Payload = f64",
    "static if true:",
    "static if USE_ALIAS_PAYLOAD:",
    "type NumberOrRecord = i64",
    "struct NumberOrRecord:",
    "bad_inactive_record_shadow",
    "return try value",
)) or not all(fragment in SMOKE for fragment in (
    "try_noncall_static_type_alias_branch.elisa",
    "Stage0 lost the selected integer alias's nonfallible fact",
    "Stage1 lost the selected integer alias's nonfallible fact",
)):
    raise SystemExit("the alias branch repro and Stage0/Stage1 smoke are required")

print("Try non-call static type-alias branch source binding passed")
