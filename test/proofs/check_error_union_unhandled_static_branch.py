"""Source-bind error-union discard analysis to static imports and static bodies."""
from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src/semantic/check_error_union_unhandled.elisa"
FIXTURE = ROOT / "test/repro/error_union_static_import_branches.elisa"
SMOKE = ROOT / "test/parity/error_union_static_import_branches_smoke.sh"
OFFSET_FIXTURE = ROOT / "test/repro/error_union_static_import_offset_zero.elisa"
OFFSET_SMOKE = ROOT / "test/parity/error_union_static_import_offset_zero_smoke.sh"
ORDER_FIXTURE = ROOT / "test/repro/error_union_static_import_order_offset_zero.elisa"
ORDER_SMOKE = ROOT / "test/parity/error_union_static_import_order_offset_zero_smoke.sh"


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


source = SOURCE.read_text()
branch_guard = function_source(source, "error_union_static_scope_is_inactive")
import_lookup = function_source(source, "error_imported_module")
callable_walk = function_source(source, "error_union_visible_callable_module")
call_name = function_source(source, "error_call_name")
call_parts = function_source(source, "error_call_name_from_parts")
statement_walk = function_source(source, "error_union_unhandled_statements")
declaration_walk = function_source(source, "check_error_union_unhandled_decls")
entrypoint = function_source(source, "check_error_union_unhandled")
if not all(fragment in branch_guard for fragment in (
        "pma_static_if_row_for_position(file, position)",
        "pma_static_if_row_selection(file, branch_row, current_module, table)",
        "branch.known and not branch.selected")):
    raise SystemExit("error-union static-body selection must use exact parser positions and skip only proven-inactive rows")
if not all(fragment in import_lookup for fragment in (
        'pma_import_row_branch_uncertain(annotations, "__from_member", imported.name, imported.module, imported.line, imported.offset)',
        "uncertain_scope_length > selected_scope_length",
        "unknown_can_win",
        'return "" if unknown_can_win')):
    raise SystemExit("error-union imported-call inference must decline when an unresolved import could outrank the known provider")
if not all(fragment in import_lookup for fragment in (
        "visible_before_call: bool = imported.offset < call_pos.offset",
        "earlier_unknown_same_scope: bool = imported.offset < uncertain_offset",
        "earlier_same_scope: bool = imported.offset < selected_offset",
        "uncertain_before_selected: bool = uncertain_offset < selected_offset")) or any(fragment in import_lookup for fragment in (
        "imported.offset != 0",
        "call_pos.offset != 0",
        "uncertain_offset != 0",
        "selected_offset != 0")):
    raise SystemExit("error-union import ordering must compare absolute offsets directly because offset zero is valid")
if not all(fragment in statement_walk for fragment in (
        'block_kind == "static" and error_union_static_scope_is_inactive(file, line, lexical_module, table)',
        "error_union_unhandled_statements(body, annotations, file,",
        "error_call_name(file, expression",
        "error_call_name(file, value")):
    raise SystemExit("error-union statement traversal must skip known-inactive static blocks and thread the source file")
if not all(fragment in call_name for fragment in (
        "def error_call_name(file: Ast::File&",
        "error_call_name_from_parts(file, callee",
        "error_call_name(file, inner")) or not all(fragment in call_parts for fragment in (
        "def error_call_name_from_parts(file: Ast::File&",
        "error_union_visible_callable_module(file, declarations")):
    raise SystemExit("ErrorUnion call classification must thread file context to the static-scope-aware candidate walk")
if not all(fragment in declaration_walk for fragment in (
        "error_union_static_scope_is_inactive(file, scoped_line, current_module, table)",
        "continue if error_union_static_scope_is_inactive")):
    raise SystemExit("error-union declaration traversal must skip known-inactive static scopes")
if not all(fragment in callable_walk for fragment in (
        "def error_union_visible_callable_module(file: Ast::File&",
        "Decl.Module(module_name, module_body, module_line)",
        "nested_module: sview @source = module_name",
        "error_union_visible_callable_module(file, module_body, callee_name, lexical_module, nested_module",
        "Decl.Scoped(scoped_body, scoped_line)",
        "continue if error_union_static_scope_is_inactive(file, scoped_line, current_module, table)",
        "error_union_visible_callable_module(file, scoped_body, callee_name, lexical_module, current_module")) or \
        not all(fragment in declaration_walk for fragment in (
        "Decl.Module(module_name, module_body, module_line)",
        "nested_module: sview @source = module_name",
        "check_error_union_unhandled_decls(module_body, all_declarations, annotations, file, extern_params, nested_module")):
    raise SystemExit("ErrorUnion module recursion must preserve canonical AST module paths")
if not all(fragment in entrypoint for fragment in (
        "pma_active_import_annotations(file, table)",
        "check_error_union_unhandled_decls(file.top_decls, file.top_decls, annotations, file")):
    raise SystemExit("error-union call lookup must consume branch-filtered imports and file context")

fixture = FIXTURE.read_text()
smoke = SMOKE.read_text()
if not all(fragment in fixture for fragment in (
        "def perform() -> i64 error[FallibleProvider::Fault]",
        "const USE_FALLIBLE_PROVIDER: bool = false",
        "from FallibleProvider import perform",
        "from SafeProvider import perform",
        "static if false:",
        "FallibleProvider::perform()",
        "module OverloadBranch:",
        "static if false:",
        "def choose(value: i64) -> i64:",
        "static else:",
        "def choose(value: i64) -> i64 error[OverloadBranch::Fault]:",
        "choose(1)")) or not all(fragment in smoke for fragment in (
        "error_union_static_import_branches.elisa",
        "error union result must be handled",
        "unhandled_count", "!= 1")):
    raise SystemExit("error-union regressions must cover inactive imports/bodies and inactive overload ambiguity")
offset_fixture = OFFSET_FIXTURE.read_text()
offset_smoke = OFFSET_SMOKE.read_text()
if not offset_fixture.startswith("from FallibleProvider import perform\n") or not all(fragment in offset_fixture for fragment in (
        "#line 1 shared-import-call.elisa",
        "perform()",
        "module FallibleProvider:")) or not all(fragment in offset_smoke for fragment in (
        "error_union_static_import_offset_zero.elisa",
        "error union result must be handled")):
    raise SystemExit("offset-zero regression must keep a first-byte import visible across a #line collision")
order_fixture = ORDER_FIXTURE.read_text()
order_smoke = ORDER_SMOKE.read_text()
if not order_fixture.startswith("from SafeProvider import perform\n") or not all(fragment in order_fixture for fragment in (
        "#line 0 later-import.elisa",
        "from FallibleProvider import perform",
        "#line 3 shared-import-call.elisa",
        "module SafeProvider:",
        "module FallibleProvider:")) or not all(fragment in order_smoke for fragment in (
        "error_union_static_import_order_offset_zero.elisa",
        "error union result must be handled")):
    raise SystemExit("offset-zero ordering regression must retain the first import despite a later import with an earlier #line")

print('{"source_bound": true, "branch_filtered_imports": true, "inactive_bodies": true, "offset_zero_ordering": true}')
