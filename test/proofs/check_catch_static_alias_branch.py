"""Bind Catch alias family lookup to static-branch filtering source."""
from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src/semantic/check_catch_exhaustive.elisa"
PROOF = SOURCE.read_text()
FIXTURE = (ROOT / "test/repro/catch_static_alias_branch.elisa").read_text()
SMOKE = (ROOT / "test/parity/catch_static_alias_branch_smoke.sh").read_text()


def function_source(name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        PROOF,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


filtering = function_source("catch_active_alias_annotations")
alias_lookup = function_source("catch_module_alias_target")
entry = function_source("check_catch_exhaustive")
if not all(fragment in filtering for fragment in (
    'annotation.name == "__using_alias"',
    "ewr_static_import_annotation_selection(annotation, file.enum_annotations, file, table)",
    "continue if branch.known and not branch.active",
    'owner: "__catch_unknown_static_alias"',
)):
    raise SystemExit("Catch alias preprocessing must remove inactive aliases and mark unresolved branches")
if not all(fragment in alias_lookup for fragment in (
    'alias.owner == "__catch_unknown_static_alias"',
    "selected_unknown <- true",
    "selected_unknown <- false",
    "alias.offset > selected_offset",
    "alias.module.len > selected_scope_length",
    "return (false, alias_name, \"\", 0, 0) if ambiguous or selected_unknown",
)) or "catch_active_alias_annotations(file, table)" not in entry:
    raise SystemExit("Catch alias resolution must rank unresolved and known static aliases by scope and source order")
if not all(fragment in FIXTURE for fragment in (
    "const USE_ACTIVE_PROVIDER: bool = true",
    "static if USE_ACTIVE_PROVIDER:",
    "using ActiveProvider as Selected",
    "static else:",
    "using InactiveProvider as Selected",
    "static if UNKNOWN_PROVIDER_CHOICE:",
    "using InactiveProvider as Later",
    "using ActiveProvider as Later",
    "WrongOnly",
    "catch Selected::load()",
    "catch Later::load()",
    "ActiveProvider::Fault.Expected",
)) or not all(fragment in SMOKE for fragment in (
    "catch_static_alias_branch.elisa",
    "Fault.Missing",
    "diagnostic_count\" != 2",
    "WrongOnly",
)):
    raise SystemExit("Catch static-alias regression must select active aliases and let later direct aliases shadow unknown branches")

print("Catch static-alias source binding passed")
