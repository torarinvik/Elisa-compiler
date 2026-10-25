"""Bind raise error-family import resolution to active static-if imports."""
from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src/semantic/check_raise_without_error_set.elisa"
FIXTURE = ROOT / "test/repro/raise_static_import_branch.elisa"
SMOKE = ROOT / "test/parity/raise_static_import_branch_smoke.sh"


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


source = SOURCE.read_text()
entrypoint = function_source(source, "check_raise_without_error_set")
if "pma_active_import_annotations(file, table)" not in entrypoint:
    raise SystemExit("raise error-family lookup must receive branch-filtered import annotations")
if 'file.error_set_func_lines, annotations, file, "", table' not in entrypoint:
    raise SystemExit("raise checker must pass the filtered annotation view to its declaration walk")

fixture = FIXTURE.read_text()
smoke = SMOKE.read_text()
declarations = function_source(source, "check_raise_without_error_set_decls")
statements = function_source(source, "check_raise_statements")
inactive_scope = function_source(source, "raise_static_scope_is_inactive")
if not all(fragment in inactive_scope for fragment in (
        "pma_static_if_row_for_position(file, position)",
        "pma_static_if_row_selection(file, branch_row, current_module, table)",
        "branch.known and not branch.selected")):
    raise SystemExit("raise static-scope pruning must use exact Ast::Pos rows and skip only proven-inactive branches")
if 'continue if kind == "static" and raise_static_scope_is_inactive(file, line, current_module, table)' not in statements:
    raise SystemExit("raise statement walker must skip proven-inactive static blocks")
if "continue if raise_static_scope_is_inactive(file, line, current_module, table)" not in declarations:
    raise SystemExit("raise declaration walker must skip proven-inactive scoped declarations")
if "nested_module: sview @source = name" not in declarations:
    raise SystemExit("raise declaration walker must use the parser's canonical nested module path")
if not all(fragment in fixture for fragment in (
        "def active_statement_raise()",
        "def inactive_statement_raise()",
        "static if false:\n    def inactive_declaration_raise()",
        "raise Fault.Bad")):
    raise SystemExit("fixture must cover active and inactive static statement/declaration bodies")
if not all(fragment in fixture for fragment in (
        "static if false:",
        "from InactiveProvider import Fault",
        "static else:",
        "from ActiveProvider import Fault",
        "error[ActiveProvider::Fault]",
        "raise Fault.Bad")):
    raise SystemExit("fixture must raise an imported bare family against its qualified active provider")
if not all(fragment in smoke for fragment in (
        "raise_static_import_branch.elisa",
        "raise cannot propagate tag",
        "raise requires the current function to return an error union",
        'raise_without_set_count" != 1')):
    raise SystemExit("smoke must preserve active raise diagnostics, reject inactive-arm raises, and select the active import provider")

print('{"source_bound": true, "active_raise_error_imports": true, "inactive_raise_static_scopes": true}')
