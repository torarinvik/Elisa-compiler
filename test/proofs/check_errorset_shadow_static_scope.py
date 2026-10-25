"""Bind ErrorSet shadow diagnostics to functions in active declaration scopes."""
from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src/semantic/check_errorset_shadow.elisa"
FIXTURE = ROOT / "test/repro/errorset_shadow_inactive_function_scope.elisa"
SMOKE = ROOT / "test/parity/errorset_shadow_inactive_function_scope_smoke.sh"


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


source = SOURCE.read_text()
scope = function_source(source, "esh_static_scope_is_inactive")
positions = function_source(source, "esh_function_position_counts")
metadata = function_source(source, "esh_func_metadata_at_position")
checker = function_source(source, "check_errorset_shadow")
if not all(fragment in scope for fragment in (
        "pma_static_if_row_for_position(file, position)",
        "pma_static_if_row_selection(file, branch_row, current_module, table)",
        "branch.known and not branch.selected")):
    raise SystemExit("ErrorSet declaration-scope pruning must skip only exact, proven-inactive static rows")
if not all(fragment in positions for fragment in (
        "file: Ast::File&",
        "Decl.Module(module_name, module_body, module_line)",
        "nested_module: sview = module_name",
        "continue if esh_static_scope_is_inactive(file, module_line, current_module, table)",
        "nested_module, file, table")):
    raise SystemExit("ErrorSet function position lookup must preserve file/module context and skip inactive scopes")
if "esh_function_position_counts(declarations, target_line, target_offset, \"\", file, table)" not in metadata:
    raise SystemExit("ErrorSet parameter metadata lookup must use the active-scope function index")
if not all(fragment in checker for fragment in (
        "pma_active_import_annotations(file, table)",
        "esh_func_metadata_at_position(file.top_decls, annotation.line, annotation.offset, file, table)")):
    raise SystemExit("ErrorSet shadow diagnostics must retain active-import filtering and locate parameters in active scopes")

fixture = FIXTURE.read_text()
smoke = SMOKE.read_text()
if not all(fragment in fixture for fragment in (
        "def active_forward[errorset Fault]",
        "static if false:",
        "def inactive_forward[errorset Fault]")) or not all(fragment in smoke for fragment in (
        "errorset_shadow_inactive_function_scope.elisa",
        "shadows the declared error set",
        'warning_count" != 1')):
    raise SystemExit("ErrorSet inactive-function regression must keep the active diagnostic and suppress the inactive one")

print('{"source_bound": true, "active_scope_functions": true}')
