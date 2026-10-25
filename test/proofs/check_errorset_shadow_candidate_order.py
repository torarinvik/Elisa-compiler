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
            "catch_module_alias_path_matches(import_module, raw_module, declaration_module)" not in import_path:
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

print(
    '{"source_bound": true, "candidate_order": 5, "declaration_id_cycle_guard": true, "raw_import_path": true, "static_import_branch": true}'
)
