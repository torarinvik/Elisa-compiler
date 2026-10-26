"""Bind ErrorSet alias resolution and imported-parameter lookup to source contracts."""
from __future__ import annotations

import argparse
from pathlib import Path
import re


parser = argparse.ArgumentParser()
parser.add_argument("--source-only", action="store_true")
parser.parse_args()

ROOT = Path(__file__).resolve().parents[2]
ESH = ROOT / "src/semantic/check_errorset_shadow.elisa"
TRY = ROOT / "src/semantic/check_try_fallible.elisa"
ERRORSET_PARAM = ROOT / "src/semantic/check_errorset_param_inference.elisa"
PARSER_IMPORTS = ROOT / "src/parser/parser_decl_module.elisa"
NESTED_EXPR_FIXTURE = ROOT / "test/repro/errorset_param_nested_expression.elisa"
NESTED_EXPR_SMOKE = ROOT / "test/parity/errorset_param_nested_expression_smoke.sh"


def function_source(name: str, path: Path = ESH) -> str:
    source = path.read_text()
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name} in {path.relative_to(ROOT)}")
    return match.group(0)


fallback = function_source("esh_alias_index_targets_error_set")
ordered_candidates = (
    "if esh_root_error_set_is_visible(annotations, target_name)",
    "elif not esh_local_nominal_type_shadows_family(annotations, target_name, declaration.module_owner, table, visited)",
    "if esh_local_alias_names_error_set(annotations, target_name, declaration.module_owner, table, visited)",
    "elif esh_local_error_set_is_visible(annotations, target_name, declaration.module_owner)",
    "esh_imported_name_candidate(annotations, target_name, declaration.module_owner, table)",
)
positions = [fallback.find(candidate) for candidate in ordered_candidates]
if min(positions) < 0 or positions != sorted(positions):
    raise SystemExit(
        "ErrorSet alias fallback must check root ErrorSets, ordered nominal types, "
        "local aliases, local ErrorSets, then imports"
    )
if "esh_local_type_name_exists(" in fallback:
    raise SystemExit("unordered any-scope type lookup must not decide alias target precedence")

visibility = function_source("esh_is_error_set_visible")
private_module_gate = "try_error_alias_module_visible(annotations, declaration.module, function_module)"
imported_fallback = "esh_error_set_imported(annotations, declaration, function_module)"
if private_module_gate not in visibility or imported_fallback not in visibility:
    raise SystemExit("ErrorSet import fallback must respect private module paths")
if visibility.find(private_module_gate) > visibility.find(imported_fallback):
    raise SystemExit("private module visibility must be checked before accepting an imported ErrorSet")

if "visited: mutable darray[u32]&" not in fallback:
    raise SystemExit("recursive alias target lookup must carry a declaration-ID visited stack")
cycle_guard = "return false if any prior_id in visited where prior_id == declaration.declaration_id.value"
push = "visited <- visited.push(declaration.declaration_id.value)"
pop = "_ = visited.pop()"
if not (cycle_guard in fallback and push in fallback and pop in fallback):
    raise SystemExit("recursive alias target lookup must guard and unwind declaration-ID cycles")

for import_path in (
    function_source("esh_import_path_matches"),
    function_source("try_error_set_import_path_matches", TRY),
):
    if "catch_module_qualifier_alias_target(" in import_path or \
            "catch_module_path_matches_relative(import_module, raw_module, declaration_module)" not in import_path:
        raise SystemExit("ErrorSet imports must use their raw path qualified by the importer namespace")
atom = (ROOT / "test/atoms/errorset_shadow_identity.elisa").read_text()
for probe in (
    'return 14 if esh_is_error_set_visible(alias_import_rows, "Fault", "Consumer", 900, path_table)',
    'return 52 if not esh_is_error_set_visible(raw_import_rows, "Fault", "Consumer", 900, path_table)',
):
    if probe not in atom:
        raise SystemExit(f"ErrorSet import atom is missing Core-compatible raw-path probe {probe}")

param_import_filter = function_source("errorset_active_import_annotations", ERRORSET_PARAM)
param_import_entrypoint = function_source("check_errorset_param_inference", ERRORSET_PARAM)
param_call_walk = function_source("errorset_walk_expression", ERRORSET_PARAM)
param_scope_lookup = function_source("errorset_param_for_scope", ERRORSET_PARAM)
param_identity = function_source("errorset_param_at", ERRORSET_PARAM)
param_candidate_collection = function_source("errorset_collect_candidates_from", ERRORSET_PARAM)
param_import_order = function_source("errorset_import_precedes_call", ERRORSET_PARAM)
param_identity_atom = (ROOT / "test/atoms/errorset_param_identity.elisa").read_text()
if not all(fragment in param_identity for fragment in (
        "function_offset: u32, function_module: sview",
        "annotation.line != function_line or annotation.module != function_module",
        "if annotation.offset == function_offset",
        "return exact_name if exact_count == 1.usize()")) or \
        "function_offset == 0" in param_identity or "function_offset != 0" in param_identity or \
        "errorset_param_at(annotations, line.line, line.offset, current_module)" not in param_candidate_collection or \
        not all(fragment in param_identity_atom for fragment in (
        'errorset_param_at(annotations, 50, 0, "") != "Legacy"',
        'errorset_param_at(annotations, 50, 500, "") != ""',
        'cpb_errorset_param(lines, offsets, names, modules, 50, 0, "") != "Legacy"',
        'cpb_errorset_param(lines, offsets, names, modules, 50, 500, "") != ""',
        'errorset_param_at(annotations, 44, 0, "ByteZeroModule") != "ByteZero"',
        'errorset_param_at(annotations, 44, 0, "OtherModule") != "OtherModuleByteZero"',
        'errorset_param_at(annotations, 44, 0, "AbsentModule") != ""')):
    raise SystemExit("ErrorSet parameter identity must match the candidate's exact offset within its declaring module, including byte zero")
if not all(fragment in param_import_filter for fragment in (
        "pma_import_annotation_branch_selection(annotation, file.enum_annotations, file, table)",
        "continue if branch.known and not branch.active",
        "active.push(annotation)")):
    raise SystemExit("ErrorSet parameter inference must drop known-inactive imports while retaining unresolved branch rows")
if not all(fragment in param_import_entrypoint for fragment in (
        "errorset_active_import_annotations(file, table)",
        "errorset_collect_candidates(file.top_decls, annotations, names, params, modules, file, table)",
        "errorset_walk_decls(file.top_decls, names, params, modules, annotations, \"\", file, table)")):
    raise SystemExit("ErrorSet parameter inference must use branch-filtered imports for candidate lookup and call walking")
parser_import_source = PARSER_IMPORTS.read_text()
if not all(fragment in param_import_order for fragment in (
        "annotation.pos.end_offset > annotation.pos.offset",
        "call_offset_present",
        "call_has_offset: bool = call_offset != 0 or call_offset_present",
        "return annotation.offset < call_offset if annotation_offset_present and call_has_offset",
        "return annotation.line < call_line")) or \
        "annotation.offset != 0 and call_offset != 0" in param_import_order:
    raise SystemExit("ErrorSet import ordering must compare exact offsets when source spans prove offset zero is real")
if not all(fragment in parser_import_source for fragment in (
        'owner: "__from_member", name: member, module: parser.current_module, line: token.line, offset: token.start, pos: Ast::pos_of_token(token)',
        'name: "__binding_wildcard_import", module: parser.current_module, line: target_token.line, offset: target_token.start, pos: Ast::pos_of_token(target_token)')):
    raise SystemExit("parser-backed ErrorSet import rows must retain a source-span presence marker for byte-zero offsets")
if not all(fragment in param_call_walk for fragment in (
        "line.line, line.offset, line.end_offset > line.offset",
        "errorset_param_for_scope(names, params, modules, annotations, target.name, target.module_path, current_module, line.line, line.offset, line.end_offset > line.offset")) or \
        "errorset_import_scope(annotations, modules[index], wanted, current_module, call_line, call_offset, call_offset_present)" not in param_scope_lookup:
    raise SystemExit("ErrorSet import ordering must receive the parser-backed call-offset presence bit")
if not all(fragment in param_identity_atom for fragment in (
        'offset: 0, pos: Ast::Pos{line: 0, column: 0, offset: 0, end_line: 0, end_column: 3, end_offset: 3}',
        'return 38 if errorset_param_for_scope(bytezero_names, bytezero_params, bytezero_modules, bytezero_import_rows, "remote", good_scope, 0, 12, true) != "ByteZeroR"',
        'return 39 if errorset_param_for_scope(bytezero_names, bytezero_params, bytezero_modules, call_bytezero_after_import_rows, "remote", good_scope, 0, 0, true) != ""',
        'return 40 if errorset_param_for_scope(bytezero_names, bytezero_params, bytezero_modules, legacy_import_rows, "remote", good_scope, 12, 12, true) != "ByteZeroR"',
        'return 41 if errorset_param_for_scope(bytezero_names, bytezero_params, bytezero_modules, legacy_same_line_rows, "remote", good_scope, 12, 12, true) != ""')):
    raise SystemExit("ErrorSet import atom must cover exact byte-zero ordering and conservative legacy same-line behavior")
static_import_fixture = (ROOT / "test/repro/errorset_param_static_import_branch.elisa").read_text()
static_import_smoke = (ROOT / "test/parity/errorset_param_static_import_branch_smoke.sh").read_text()
if not all(fragment in static_import_fixture for fragment in (
        "def wrap[errorset R]() -> i64 error[R]",
        "def wrap[errorset S]() -> i64 error[S]",
        "static if USE_INACTIVE_PROVIDER:",
        "from InactiveProvider import wrap",
        "static else:",
        "from ActiveProvider import wrap",
        "return wrap()")) or not all(fragment in static_import_smoke for fragment in (
        "errorset_param_static_import_branch.elisa",
        "cannot infer error-set parameter",
        'L22 cannot infer error-set parameter "S" for call to "wrap"')):
    raise SystemExit("ErrorSet parameter coverage must keep the active else-arm diagnostic despite an earlier inactive import")

param_static_scope = function_source("errorset_static_scope_is_inactive", ERRORSET_PARAM)
param_candidate_walk = function_source("errorset_collect_candidates_from", ERRORSET_PARAM)
param_diagnostic_walk = function_source("errorset_walk_decls", ERRORSET_PARAM)
param_statement_walk = function_source("errorset_walk_statements", ERRORSET_PARAM)
if not all(fragment in param_static_scope for fragment in (
        "position: Ast::Pos",
        "pma_static_if_row_for_position(file, position)",
        "pma_static_if_row_selection(file, branch_row, current_module, table)",
        "branch.known and not branch.selected")) or \
        not all(fragment in param_candidate_walk for fragment in (
        "errorset_static_scope_is_inactive(file, scoped_line, current_module, table)",
        "continue if errorset_static_scope_is_inactive")) or \
        not all(fragment in param_diagnostic_walk for fragment in (
        "errorset_static_scope_is_inactive(file, scoped_line, current_module, table)",
        "continue if errorset_static_scope_is_inactive")) or \
        not all(fragment in param_statement_walk for fragment in (
        'kind == "static" and errorset_static_scope_is_inactive(file, line, current_module, table)',
        "file, table")):
    raise SystemExit("ErrorSet candidate collection and diagnostic traversal must skip only proven-inactive declaration and statement branches")
static_scope_fixture = (ROOT / "test/repro/errorset_param_static_scope.elisa").read_text()
static_scope_smoke = (ROOT / "test/parity/errorset_param_static_scope_smoke.sh").read_text()
if not all(fragment in static_scope_fixture for fragment in (
        "static if false:",
        "def hidden_wrap[errorset H]()",
        "return hidden_wrap()",
        "def inactive_statement_call()",
        "active_wrap()",
        "def active_call()")) or not all(fragment in static_scope_smoke for fragment in (
        "errorset_param_static_scope.elisa",
        'L22 cannot infer error-set parameter "A" for call to "active_wrap"')):
    raise SystemExit("ErrorSet static-scope coverage must keep only its active call diagnostic")

param_expression_walk = function_source("errorset_walk_expression", ERRORSET_PARAM)
param_statement_walk = function_source("errorset_walk_statements", ERRORSET_PARAM)
param_declaration_walk = function_source("errorset_walk_decls", ERRORSET_PARAM)
param_call_target = function_source("errorset_call_target", ERRORSET_PARAM)
param_module_path = function_source("errorset_module_path", ERRORSET_PARAM)
param_module_symbol = function_source("errorset_module_symbol_exists", ERRORSET_PARAM)
param_alias_target = function_source("errorset_qualified_alias_target", ERRORSET_PARAM)
param_qualified_module = function_source("errorset_qualified_module_for_call", ERRORSET_PARAM)
type_path_alias_selection = function_source("type_path_alias_selection", ROOT / "src/semantic/check_type_path_separator.elisa")
nested_expression_fixture = NESTED_EXPR_FIXTURE.read_text()
nested_expression_smoke = NESTED_EXPR_SMOKE.read_text()
if not all(fragment in param_expression_walk for fragment in (
        "errorset_walk_expression(callee, names, params, modules, annotations, current_module, file, table)",
        "errorset_call_target(callee, table)",
        "target.module_path",
        "Expr.StaticEffectCall(_, operation, candidates, arguments, argument_names, line)",
        "Expr.If(condition, then_expression, else_expression, line)",
        "Expr.Array(elements, line) | Expr.Tuple(elements, line) | Expr.SetLit(elements, line)",
        "Expr.Match(scrutinee, arms, line) | Expr.Catch(scrutinee, arms, line)",
        "Expr.Comprehension(variable, iterable, condition, body, line, scope_id)",
        "Expr.Lambda(parameters, body, line)",
        "Expr.Construct(_, fields, line)",
        "Expr.Block(statements, value, captures, line)")) or not all(fragment in param_statement_walk for fragment in (
        "Stmt.Assign(target, operator, value, line)",
        "errorset_walk_expression(target, names, params, modules, annotations, current_module, file, table)",
        "Stmt.While(condition, body, line)",
        "Stmt.Contract(kind, expression, line)",
        'kind == "requires" or kind == "require" or kind == "assert" or kind == "ensure" or kind == "ensures"')) or not all(fragment in param_declaration_walk for fragment in (
        "parameter.default_value",
        "member.default_value")) or not all(fragment in nested_expression_fixture for fragment in (
        "def wrap[errorset R]() -> i64 error[R]",
        "def nested_conditional_call() -> i64 error[CallerFault]",
        "return 7 if try wrap() == 1 else 0",
        "def default_parameter_call(value: i64 = wrap()) -> i64:",
        "value: i64 = wrap()",
        "def qualified_call() -> i64:",
        "QualifiedProvider::Nested::wrap()",
        "using QualifiedProvider as QP",
        "def alias_qualified_call() -> i64:",
        "QP::Nested::wrap()")) or not all(fragment in nested_expression_smoke for fragment in (
        "errorset_param_nested_expression.elisa",
        'L8 cannot infer error-set parameter "R" for call to "wrap"',
        'L11 cannot infer error-set parameter "R" for call to "wrap"',
        'L15 cannot infer error-set parameter "R" for call to "wrap"',
        'L24 cannot infer error-set parameter "Q" for call to "wrap"',
        'L30 cannot infer error-set parameter "Q" for call to "wrap"')):
    raise SystemExit("ErrorSet inference must recursively visit nested expression and statement call sites")
if "errorset_walk_expression(effect_type" in param_expression_walk or "errorset_walk_expression(type_expression" in param_expression_walk:
    raise SystemExit("ErrorSet inference must only walk runtime-evaluated effect captures and constructor fields")
if not all(fragment in param_call_target for fragment in (
        "Expr.Ident(name, line)",
        "Expr.Scope(base, name, line)",
        "errorset_module_path(base, table)",
        "Expr.Paren(inner, line)")) or not all(fragment in param_module_path for fragment in (
        "Expr.Scope(base, name, line)",
        "prefix.len + 2.usize() + name.len",
        "intern_joined_text(bytes, table)")) or not all(fragment in param_module_symbol for fragment in (
        "symbol.kind != SymbolKind.Module",
        'alias.name == "__using_alias"',
        "symbol.offset")) or not all(fragment in param_alias_target for fragment in (
        "alias_row.name != \"__using_alias\"",
        "alias_class: (found: bool, branch: bool, offset: u32, order_index: usize) = type_path_alias_branch_at(alias_names[alias_index], alias_scopes[alias_index], alias_occurrence, table)",
        "type_path_canonical_alias_target(alias_raw_targets[alias_index], alias_names, alias_raw_targets, alias_scopes, alias_uncertain, table, alias_scopes[alias_index], alias_class.offset, alias_class.order_index, alias_class.branch, true)",
        "alias_uncertain[alias_index] <- true",
        "eligible_alias_rows.push(errorset_import_precedes_call(alias_row, call_line, call_offset, call_offset_present))",
        "eligible_possible_rows.push(errorset_import_precedes_call(possible_annotation, call_line, call_offset, call_offset_present))",
        "type_path_alias_selection(alias_name, alias_names, alias_targets, alias_scopes, alias_uncertain, table, \"\", 0, 0, false, false, eligible_alias_rows, eligible_possible_rows)",
        "not selected.known")) or not all(fragment in param_qualified_module for fragment in (
        "errorset_module_symbol_exists(candidate, table)",
        "errorset_qualified_alias_target(lookup_qualifier, call_line, call_offset, call_offset_present, table)",
        "alias.target",
        "errorset_module_symbol_exists(lookup_qualifier, table)")) or \
        "table.possible_import_annotations" not in type_path_alias_selection or \
        "eligible_alias_rows.count > 0 and not eligible_alias_rows[alias_index]" not in type_path_alias_selection or \
        "eligible_possible_rows.count > 0 and not eligible_possible_rows[possible_index]" not in type_path_alias_selection or \
        param_qualified_module.find("errorset_module_symbol_exists(candidate, table)") > param_qualified_module.find("errorset_qualified_alias_target(lookup_qualifier, call_line, call_offset, call_offset_present, table)") or \
        param_qualified_module.find("errorset_qualified_alias_target(lookup_qualifier, call_line, call_offset, call_offset_present, table)") > param_qualified_module.find("errorset_module_symbol_exists(lookup_qualifier, table)") or \
        "errorset_qualified_module_for_call(qualified_module, current_module, call_line, call_offset, call_offset_present, table)" not in param_scope_lookup or \
        "module_last_segment" in param_qualified_module:
    raise SystemExit("qualified ErrorSet calls must resolve an exact module identity after lexical, alias, and root lookup")

print(
    '{"source_bound": true, "candidate_order": 5, "declaration_id_cycle_guard": true, "raw_import_path": true, "static_import_branch": true, "nested_expression_walk": true, "declaration_defaults": true, "runtime_contracts_only": true, "runtime_value_children_only": true, "errorset_parameter_module_identity": true, "qualified_call_path": true, "alias_qualified_call_path": true, "qualified_alias_source_cutoff": true}'
)
