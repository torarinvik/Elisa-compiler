"""Keep static-function semantic facts aligned with exact static-if branches."""
from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
RECURSION = (ROOT / "src/semantic/check_static_def_recursion.elisa").read_text()
INTERPOLATION = (ROOT / "src/semantic/check_static_generate_interp.elisa").read_text()
STATIC_EVAL = (ROOT / "src/semantic/check_static_eval.elisa").read_text()
STATIC_ERROR = (ROOT / "src/semantic/check_static_error.elisa").read_text()
STATIC_ASSERT = (ROOT / "src/semantic/check_static_assert.elisa").read_text()
PMA = (ROOT / "src/semantic/check_private_member_access.elisa").read_text()
PARSER = (ROOT / "src/parser/parser_types_function.elisa").read_text()
PARSER_DECL = (ROOT / "src/parser/parser_decl.elisa").read_text()
PARSER_TOKENS = (ROOT / "src/parser/parser_tokens.elisa").read_text()
PARSER_CORE = (ROOT / "src/parser/parser_core.elisa").read_text()
PARSER_TABLES = (ROOT / "src/parser/parser_core_member_tables.elisa").read_text()
PARSER_ENTRY = (ROOT / "src/parser/parser_types_entry.elisa").read_text()
LOOP_VIEW = (ROOT / "src/semantic/semantic_loop_view.elisa").read_text()
FIXTURE = (ROOT / "test/repro/static_function_inactive_branch.elisa").read_text()
UNKNOWN_ASSERT_FIXTURE = (ROOT / "test/repro/static_assert_unknown_branch.elisa").read_text()
UNKNOWN_ASSERT_SMOKE = (ROOT / "test/parity/static_assert_unknown_branch_smoke.sh").read_text()
INTERP_FIXTURE = (ROOT / "test/repro/static_generate_interp_module_visibility.elisa").read_text()
INTERP_SMOKE = (ROOT / "test/parity/static_generate_interp_module_visibility_smoke.sh").read_text()


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


branch_filter = function_source(RECURSION, "sdr_static_fn_branch_selection")
collect_static_identities = function_source(RECURSION, "sdr_collect_static_fn_annotations")
static_declaration_index = function_source(RECURSION, "sdr_static_fn_declaration_index")
static_call_index = function_source(RECURSION, "sdr_static_fn_call_index")
scan_calls = function_source(RECURSION, "sdr_scan_calls")
scope_filter = function_source(RECURSION, "sdr_static_scope_is_inactive")
check_decls = function_source(RECURSION, "sdr_check_declarations")
scan_body = function_source(RECURSION, "sdr_scan_body")
scan_guards = function_source(RECURSION, "sdr_scan_guards")
sgi_static_filter = function_source(INTERPOLATION, "sgi_static_fn_branch_selection")
sgi_visibility = function_source(INTERPOLATION, "sgi_function_visible")
sgi_candidate = function_source(INTERPOLATION, "sgi_interpolation_function_kind")
sgi_check = function_source(INTERPOLATION, "check_static_generate_interp")
eval_runner = function_source(STATIC_EVAL, "static_run_func")
eval_expr = function_source(STATIC_EVAL, "static_eval_expr")
eval_entry = function_source(STATIC_EVAL, "check_static_eval")
assert_branch_activity = function_source(STATIC_ASSERT, "static_assert_branch_activity")
assert_entry = function_source(STATIC_ASSERT, "check_static_assert")
error_branch_selection = function_source(STATIC_ERROR, "static_error_function_branch_selection")
error_candidate_count = function_source(STATIC_ERROR, "static_error_count_function_candidates")
error_body = function_source(STATIC_ERROR, "static_def_body_error")
error_scan = function_source(STATIC_ERROR, "static_error_scan_calls")
error_entry = function_source(STATIC_ERROR, "check_static_error")
pma_function_filter = function_source(PMA, "pma_static_if_function_branch_selection")

for source, label in ((branch_filter, "recursion"), (sgi_static_filter, "interpolation")):
    if not all(fragment in source for fragment in (
        'marker.owner != "__static_if_branch"',
        'marker.name != "__function_static_branch"',
        "marker.detail_name != annotation.name",
        "marker.module != annotation.module or marker.line != annotation.line or marker.offset != annotation.offset",
        "marker.identity_id.usize()",
        "marker.identity_id == 4294967295 or not branch.known",
        "return (true, false) if branch.known and not branch.selected",
    )):
        raise SystemExit(f"{label} static-function selection must match exact markers and preserve unknown rows")

if not all(fragment in collect_static_identities for fragment in (
    'annotation.owner == "__static_fn"',
    "sdr_static_fn_branch_selection(annotation, file.enum_annotations, file, table)",
    "out.push(annotation) if not branch.known or branch.active",
)) or not all(fragment in static_declaration_index for fragment in (
    "annotation.name == function_name",
    "annotation.module == current_module",
    "annotation.line == function_position.line and annotation.offset == function_position.offset",
)):
    raise SystemExit("recursion must retain exact static declaration identities")
if not all(fragment in compact_inline(static_call_index) for fragment in (
    "symbol_chain_head(table, function_name)",
    "symbol.module_owner == current_module",
    "pma_static_if_function_branch_selection(file, function_name, symbol, table, 0)",
    "if not branch.known or branch.active: function_count <- function_count + 1",
    "function_count == 1 and static_index >= 0",
    "return -1",
)) or not all(fragment in scan_calls for fragment in (
    "Expr.Ident(name, _)",
    "sdr_static_fn_call_index(file, static_fns, callee_name, current_module, table)",
    "called: mutable darray[i64]",
)) or not all(fragment in check_decls for fragment in (
    "sdr_static_fn_declaration_index(static_fns, function_name, line, current_module)",
    "function_index >= 0",
    "sdr_index_in(reported_cycle, function_index)",
)):
    raise SystemExit("recursion call and cycle edges must preserve module-scoped declaration identity")
if not all(fragment in scope_filter for fragment in (
    "pma_static_if_row_for_position(file, position)",
    "pma_static_if_row_selection(file, branch_row, current_module, table)",
    "return branch.known and not branch.selected",
)):
    raise SystemExit("recursion declaration/body walks need exact branch-position selection")
if not all(fragment in check_decls for fragment in (
    "Decl.Scoped(scoped_body, scoped_line)",
    "if not sdr_static_scope_is_inactive(file, scoped_line, current_module, table)",
    "sdr_check_declarations(file, all_declarations, module_body, module_name",
)):
    raise SystemExit("recursion declaration walk must prune inactive scopes and retain canonical modules")
for source, label in ((scan_body, "call scan"), (scan_guards, "guard scan")):
    if "if not sdr_static_scope_is_inactive(file, block_line, current_module, table)" not in source:
        raise SystemExit(f"{label} must ignore proven-inactive static-if bodies")

if not all(fragment in sgi_visibility for fragment in (
    "table: mutable SymbolTable&",
    "can Memory.Allocate, Abort.Panic:",
    "try_noncall_module_is_ancestor(symbol.module_owner, current_module)",
    "return (true, true, true)",
    'import_annotation.name == "__binding_wildcard_import"',
    'import_annotation.owner == "__from_member" and import_annotation.name == symbol.name',
    "pma_import_annotation_branch_selection(import_annotation, annotations, file, table)",
    "return (false, true, false) if import_uncertain",
)) or not all(fragment in sgi_candidate for fragment in (
    "table: mutable SymbolTable&",
    "can Memory.Allocate, Abort.Panic:",
    "symbol_chain_head(table, name)",
    "visibility.lexical",
    "symbol.module_owner.len > lexical_depth",
    "lexical_count == 1 and not lexical_uncertain",
    "import_count == 1 and not import_uncertain",
    "pma_static_if_function_branch_selection(file, name, symbol, table, 0)",
    "annotation.module != symbol.module_owner or annotation.line != symbol.line or annotation.offset != symbol.offset",
)) or "sgi_interpolation_function_kind(file, file.enum_annotations, table, callee, annotation.module)" not in sgi_check or not all(fragment in PARSER_DECL for fragment in (
    'owner: "__static_gen_interp_call"',
    "offset: call_token.start",
    "module: parser.current_module",
    "pos: Ast::pos_of_token(call_token)",
)):
    raise SystemExit("interpolation classification must use parser provenance and a unique module-visible function")
if "sdr_collect_static_fn_annotations(file, static_fns, table)" not in eval_entry or "sdr_static_fn_call_index(file, static_fns, callee_name, current_module, table)" not in eval_expr or not all(fragment in eval_runner for fragment in (
    "sdr_static_fn_declaration_index(static_fns, name, line, current_module) == target_index",
    "sdr_static_scope_is_inactive(file, scoped_line, current_module, table)",
)):
    raise SystemExit("static evaluation must use filtered static-function rows and skip inactive declarations")
if not all(fragment in assert_branch_activity for fragment in (
    "not file.static_assert_branch_rows_known[index]",
    "file.static_assert_branch_row_starts[index]",
    "file.static_assert_branch_row_counts[index]",
    "file.static_assert_branch_row_ids[start + row_offset]",
    "pma_static_if_row_selection(file, branch_row.usize(), current_module, table)",
        "return (true, false) if branch.known and not branch.selected",
        "return (false, true) if not branch.known",
        "row_count != file.static_assert_branch_row_counts[index]",
        "return (true, true)")) or not all(fragment in assert_entry for fragment in (
        "static_assert_branch_activity(file, index, current_module, table)",
        "activity.known and activity.active")):
    raise SystemExit("static assertions must evaluate only under proven-active enclosing branches")
if not all(fragment in error_branch_selection for fragment in (
    'marker.owner != "__static_if_branch"',
    'marker.name != "__function_static_branch"',
    "marker.module != current_module or marker.line != position.line or marker.offset != position.offset",
    "return (true, false) if branch.known and not branch.selected",
)) or not all(fragment in error_body for fragment in (
    "sdr_static_fn_declaration_index(static_fns, name, line, current_module) == target_index",
    "sdr_static_scope_is_inactive(file, scoped_line, current_module, table)",
    "module_name, static_fns, target_index, out_message, out_line, table",
)) or not all(fragment in error_candidate_count for fragment in (
    "static_error_function_branch_selection(file, name, current_module, line, table)",
    "current_module == target_module",
    "count <- count + 1 if not branch.known or branch.active",
)) or not all(fragment in error_scan for fragment in (
    "Expr.Ident(callee_name, _)",
    "sdr_static_fn_call_index(file, static_fns, name, current_module, table)",
    "file: Ast::File&",
    "table: SymbolTable&",
    "out: mutable darray[i64]",
)) or not all(fragment in error_entry for fragment in (
    "file.static_assert_modules[index]",
    "static_assert_branch_activity(file, index, current_module, table)",
    "activity.known and activity.active",
    "static_error_scan_calls(condition, file, static_fns, current_module, called, table)",
    "static_error_count_function_candidates(file, file.top_decls, \"\", current_module, name, candidates, table)",
    "candidates == 1 and static_def_body_error",
    "sdr_collect_static_fn_annotations(file, static_fns, table)",
)) or not all(fragment in eval_entry for fragment in (
    "file.static_assert_modules[index]",
    "static_assert_branch_activity(file, index, current_module, table)",
    "activity.known and activity.active",
    "static_eval_expr(file.top_decls, static_fns, condition, empty_names, empty_vals, counter, exceeded, unsupported, file, current_module, table)",
)):
    raise SystemExit("static error reporting must resolve visible static declarations only")
if not all(fragment in pma_function_filter for fragment in (
    'marker.name != "__function_static_branch"',
    "marker.module != symbol.module_owner or marker.line != symbol.line or marker.offset != symbol.offset",
    "return (true, false) if branch.known and not branch.selected",
)):
    raise SystemExit("shared function filter must keep exact declaration provenance")
if not all("static_assert_modules" in source and "static_assert_branch_row_starts" in source and "static_assert_branch_row_counts" in source and "static_assert_branch_row_ids" in source and "static_assert_branch_rows_known" in source for source in (
    PARSER_TOKENS, PARSER_CORE, PARSER_TABLES, PARSER_ENTRY, LOOP_VIEW
)) or not all(fragment in PARSER_DECL for fragment in (
    "parser.static_assert_modules <- parser.static_assert_modules.push(parser.current_module)",
    "parser.static_assert_branch_rows_known <- parser.static_assert_branch_rows_known.push(branch_rows_known)",
    "parser.static_if_branch_rows.count.u32() == parser.static_if_depth",
    "parser.static_assert_branch_row_starts <- parser.static_assert_branch_row_starts.push(parser.static_assert_branch_row_ids.count)",
    "parser.static_assert_branch_row_counts <- parser.static_assert_branch_row_counts.push(parser.static_if_branch_rows.count)",
    "parser.static_assert_branch_row_ids <- parser.static_assert_branch_row_ids.push(branch_row)",
)):
    raise SystemExit("static-assert module and branch provenance must survive parse and semantic loop views")
if not all(fragment in UNKNOWN_ASSERT_FIXTURE for fragment in (
        "static def branch_error() -> i32:",
        'error("unknown condition static error")',
        "static if ELISA_TARGET_OS_WASI:",
        'static assert 1 == 2, "unknown condition assert"',
        "static assert branch_error() == 0")) or not all(fragment in UNKNOWN_ASSERT_SMOKE for fragment in (
        "static_assert_unknown_branch.elisa",
        "ELISA_STAGE1_TRIPLE=wasm32-unknown-unknown",
        "unknown condition assert",
        "unknown condition static error")):
    raise SystemExit("unknown static-if conditions must defer assertions, static evaluation, and static-error reporting")
if not all(fragment in PARSER for fragment in (
    'record_static_if_branch_rows("__function_static_branch", function_name, token)',
)) or not all(fragment in FIXTURE for fragment in (
    "static if false:",
    "inactive_partial",
    "static if true:",
    "active_partial",
    "inactive_body_call",
    "module StaticIdentity:",
    "module RuntimeIdentity:",
    "static def duplicate(n: i32)",
    "def duplicate(n: i32)",
    "def branch_shadow(n: i32)",
    "static def branch_shadow(n: i32)",
    "def branch_error() -> i32:",
    "static def branch_error() -> i32:",
    'error("active branch")',
    "static assert branch_error() == 0",
    'module NestedErrorName:\n    static def branch_error() -> i32:\n        error("nested branch")\n\n    static assert branch_error() == 0',
    'static if false:\n    static assert branch_error() == 0\n\nstatic assert branch_error() == 0',
)) or not all(fragment in INTERP_FIXTURE for fragment in (
    "module RuntimeFirst:",
    "module StaticSecond:",
    "module StaticFirst:",
    "module RuntimeSecond:",
    "from RuntimeFirst import build",
    "from RuntimeSecond import build",
    "static generate:",
    "${build()}",
    "module LexicalStaticParent:",
    "module LexicalRuntimeParent:",
    "module Child:",
    "${local_build()}",
)) or not all(fragment in INTERP_SMOKE for fragment in (
    "stage0_count\" == 3",
    "stage1_count\" == \"$stage0_count\"",
    "static generate interpolation must evaluate at compile time",
)):
    raise SystemExit("parser provenance and active/inactive recursion fixture coverage are required")

print("Static function inactive-branch source binding passed")
