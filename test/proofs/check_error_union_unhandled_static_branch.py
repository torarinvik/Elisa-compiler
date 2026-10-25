"""Source-bind error-union discard analysis to static imports and static bodies."""
from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src/semantic/check_error_union_unhandled.elisa"
CATCH_SOURCE = ROOT / "src/semantic/check_catch_exhaustive.elisa"
PMA_SOURCE = ROOT / "src/semantic/check_private_member_access.elisa"
FIXTURE = ROOT / "test/repro/error_union_static_import_branches.elisa"
SMOKE = ROOT / "test/parity/error_union_static_import_branches_smoke.sh"
OFFSET_FIXTURE = ROOT / "test/repro/error_union_static_import_offset_zero.elisa"
OFFSET_SMOKE = ROOT / "test/parity/error_union_static_import_offset_zero_smoke.sh"
ORDER_FIXTURE = ROOT / "test/repro/error_union_static_import_order_offset_zero.elisa"
ORDER_SMOKE = ROOT / "test/parity/error_union_static_import_order_offset_zero_smoke.sh"
OVERLOAD_FIXTURE = ROOT / "test/repro/error_union_overload_offset_zero.elisa"
OVERLOAD_SMOKE = ROOT / "test/parity/error_union_overload_offset_zero_smoke.sh"
FORWARD_FIXTURE = ROOT / "test/repro/error_union_forwarding_offset_identity.elisa"
FORWARD_SMOKE = ROOT / "test/parity/error_union_forwarding_offset_identity_smoke.sh"
ARG_FORWARDING_SOURCE = ROOT / "src/semantic/check_arg_forwarding.elisa"
EXPR_WALK_SOURCE = ROOT / "src/semantic/resolve_expr_walk_context.elisa"
POSTFIX_SOURCE = ROOT / "src/parser/parser_expr_postfix.elisa"
FUNCTION_PARSER_SOURCE = ROOT / "src/parser/parser_types_function.elisa"


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


source = SOURCE.read_text()
catch_source = CATCH_SOURCE.read_text()
pma_source = PMA_SOURCE.read_text()
branch_guard = function_source(source, "error_union_static_scope_is_inactive")
import_lookup = function_source(source, "error_imported_module")
callable_walk = function_source(source, "error_union_visible_callable_module")
call_name = function_source(source, "error_call_name")
call_parts = function_source(source, "error_call_name_from_parts")
statement_walk = function_source(source, "error_union_unhandled_statements")
declaration_walk = function_source(source, "check_error_union_unhandled_decls")
entrypoint = function_source(source, "check_error_union_unhandled")
forwarded_call = function_source(source, "error_union_call_forwards_args")
fallible_declaration = function_source(source, "error_union_declaration_is_fallible_at")
alias_qualifier = function_source(catch_source, "catch_module_qualifier_alias_target")
alias_unknown_marker = function_source(catch_source, "catch_module_alias_annotation_is_unknown")
pma_import_filter = function_source(pma_source, "pma_active_import_annotations")
arg_forwarding = function_source(ARG_FORWARDING_SOURCE.read_text(), "forwarding_marker_matches")
postfix_call = function_source(POSTFIX_SOURCE.read_text(), "postfix_call_suffix")
function_parser = function_source(FUNCTION_PARSER_SOURCE.read_text(), "function_declaration")
expr_walk = EXPR_WALK_SOURCE.read_text()
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
        "catch_module_qualifier_alias_target(annotations, qualifier, lexical_module, call_pos.line, call_pos.offset)",
        "alias_target.uncertain",
        'return sview("", 0, 0) if alias_target.uncertain',
        "error_union_visible_callable_module(file, declarations")):
    raise SystemExit("ErrorUnion call classification must thread file context to the static-scope-aware candidate walk")
if not all(fragment in alias_unknown_marker for fragment in (
        'alias.owner == "__pma_unknown_static_import"',
        'alias.detail_name == "__using_alias"')) or not all(fragment in alias_qualifier for fragment in (
        "alias_target.uncertain",
        'return (false, true, "", "", suffixes)')) or not all(fragment in pma_import_filter for fragment in (
        'owner: "__pma_unknown_static_import"',
        "name: annotation.owner",
        "detail_name: annotation.name",
        "if import_row and not branch.known")):
    raise SystemExit("ErrorUnion qualified aliases must block raw-module fallback for unresolved alias winners")
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
if not all(fragment in forwarded_call for fragment in (
        'marker.owner != "__arg_forward"',
        "marker.line != call_pos.line",
        "marker.offset != call_pos.offset")) or not all(fragment in fallible_declaration for fragment in (
        "marker.offset != declaration_offset",
        "module_row.offset == marker.offset")) or any(fragment in fallible_declaration for fragment in (
        "declaration_offset != 0",
        "module_row.offset != 0")):
    raise SystemExit("ErrorUnion call/declaration identity must compare exact offsets, including byte offset zero")
if not all(fragment in function_parser for fragment in (
        'owner: function_name, name: "__error_return", line: token.line, offset: token.start',
        'owner: "__fn_module", name: parser.current_module, line: token.line, offset: token.start')):
    raise SystemExit("fallible function markers must carry the exact declaration token offset")
if not all(fragment in arg_forwarding for fragment in (
        "forward_lines[marker_index] != call_pos.line",
        "marker_index >= forward_offsets.count",
        "marker_offset == call_pos.offset")) or not all(fragment in expr_walk for fragment in (
        "forward_index >= table.forward_arg_offsets.count",
        "table.forward_arg_lines[forward_index] == line.line and marker_offset == line.offset")) or not all(fragment in postfix_call for fragment in (
        'owner: "__arg_forward"',
        "offset: token.start",
        "Ast::Expr.Call(rewritten_active, argument_items, argument_names, Ast::pos_of_token(token))")):
    raise SystemExit("all __arg_forward readers must bind the parser's exact call offset")

fixture = FIXTURE.read_text()
smoke = SMOKE.read_text()
if not all(fragment in fixture for fragment in (
        "def perform() -> i64 error[FallibleProvider::Fault]",
        "const USE_FALLIBLE_PROVIDER: bool = false",
        "from FallibleProvider import perform",
        "from SafeProvider import perform",
        "module RootCollision:",
        "module AliasSafeProvider:",
        "module AliasInstallerA:\n    static if UNKNOWN_ALIAS_TARGET:\n        using AliasSafeProvider as RootCollision",
        "module AliasInstallerB:\n    static if UNKNOWN_ALIAS_TARGET:\n        using AliasSafeProvider as RootCollision",
        "def unresolved_alias_does_not_fall_back_to_root_module()",
        "RootCollision::load()",
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
        "unresolved module aliases blocking same-name raw-module fallback",
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
overload_fixture = OVERLOAD_FIXTURE.read_text()
overload_smoke = OVERLOAD_SMOKE.read_text()
if not overload_fixture.startswith("def choose() -> i64:") or not all(fragment in overload_fixture for fragment in (
        "#line 1 offset-zero-overload.elisa",
        "def choose(value: i64) -> i64 error[Fault]:",
        "choose()",
        "choose(1)")) or not all(fragment in overload_smoke for fragment in (
        "error_union_overload_offset_zero.elisa",
        "error union result must be handled",
        '!= "1"')):
    raise SystemExit("repeated-#line overload regression must reject a fallibility marker borrowed by the byte-zero overload")
forward_fixture = FORWARD_FIXTURE.read_text()
forward_smoke = FORWARD_SMOKE.read_text()
if not all(fragment in forward_fixture for fragment in (
        "def perform(value: i64) -> i64 error[Fault]:",
        "def caller(value: i64) -> i64:",
        "#line 2 forwarding-sibling.elisa\n    perform(..)\n#line 2 forwarding-sibling.elisa\n    perform()",
        "error Fault:")) or not all(fragment in forward_smoke for fragment in (
        "error_union_forwarding_offset_identity.elisa",
        "error union result must be handled",
        "expects 1 arguments, got 0",
        '!= "1"')):
    raise SystemExit("same-line forwarding regression must isolate each `..` marker and preserve ordinary call arity")

print('{"source_bound": true, "branch_filtered_imports": true, "inactive_bodies": true, "exact_offset_identity": true, "offset_zero_overload": true}')
