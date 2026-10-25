"""Bind zeroed module-alias selection to definite/possible import views."""
from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
SEMANTIC = (ROOT / "src/semantic/check_uninitialized_zeroed.elisa").read_text()
IMPORTS = (ROOT / "src/semantic/semantic_import_visibility.elisa").read_text()
TYPE_ALIASES = (ROOT / "src/semantic/check_uninitialized_zeroed/type_aliases.elisa").read_text()
CALLEE_OWNER = (ROOT / "src/semantic/check_zeroed_value_positions.elisa").read_text()
FIXTURE = (ROOT / "test/repro/zeroed_inactive_module_alias.elisa").read_text()
NESTED_FIXTURE = (ROOT / "test/repro/zeroed_nested_global_module_alias.elisa").read_text()
PRECEDENCE_FIXTURE = (ROOT / "test/repro/zeroed_nested_alias_precedence.elisa").read_text()
POSSIBLE_FIXTURE = (ROOT / "test/repro/zeroed_possible_module_alias_order.elisa").read_text()
SMOKE = (ROOT / "test/parity/zeroed_reference_safety_smoke.sh").read_text()


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return match.group(0)


resolver = function_source(SEMANTIC, "zeroed_expand_using_module_path")
alias_precedence = function_source(SEMANTIC, "zeroed_alias_registration_precedes")
shared_alias_precedence = function_source(IMPORTS, "semantic_possible_import_alias_precedes")
if "table.using_alias_rows" in resolver or not all(fragment in resolver for fragment in (
    "table.protocol_annotations.count",
    "table.definite_import_annotations",
    "table.possible_import_annotations",
    "zeroed_alias_registration_precedes(alias_index, selected_order_index, table)",
    "selected_ambiguous <- true if not order.known or order.precedes",
    "possible_can_shadow <- true if not order.known or order.precedes",
    "selected_order_index",
)):
    raise SystemExit("zeroed alias resolution must select the analyzer-wide Core registration winner and fail closed on a winning possible alias")
if not all(fragment in alias_precedence for fragment in (
    "left_index >= table.protocol_annotations.count",
    "left_alias: Ast::EnumAnnotation = table.protocol_annotations[left_index]",
    "right_alias: Ast::EnumAnnotation = table.protocol_annotations[right_index]",
    "semantic_possible_import_alias_precedes(left_alias, right_alias, table)",
    "-> (known: bool, precedes: bool)",
    "return (false, false)",
)) or not all(fragment in shared_alias_precedence for fragment in (
    "both_definite: bool",
    "semantic_possible_import_alias_is_definite(left, table)",
    "semantic_possible_import_alias_is_definite(right, table)",
    "branch_relation.shared_prefix",
    "if not right_is_branch:",
    "if not left_is_branch:",
    "left.offset < right.offset",
    "not both_definite",
)):
    raise SystemExit("zeroed alias ordering must delegate to the shared definite/possible registration comparator")

if "def zeroed_resolve_type_alias_chain" not in TYPE_ALIASES or \
        "zeroed_expand_using_module_path(module_path, resolution_module, table, path_invalid)" not in TYPE_ALIASES:
    raise SystemExit("qualified zeroed type aliases must use the branch-aware module resolver")
if "zeroed_expand_using_module_path(module_path, path_owner, table, path_invalid)" not in CALLEE_OWNER:
    raise SystemExit("qualified zeroed callees must use the branch-aware module resolver")
if not all(fragment in IMPORTS for fragment in (
    "def semantic_import_alias_is_static_branch",
    'marker.name == "__using_alias_static_branch"',
)):
    raise SystemExit("zeroed alias selection must share the static-branch identity policy")
if not all(fragment in FIXTURE for fragment in (
    "using Safe as Pick",
    "static if false:",
    "using Wrong as Pick",
    "type Plain = i64",
    "type Plain = sview",
    "Pick::Plain = zeroed",
    "using Safe as DirectBranchPick",
    "using Safe as BranchFirstPick",
    "using Safe as BranchRootPick",
    "static if true:\n    using Safe as BranchRootPick\n\nstatic if true:\n    using Wrong as BranchRootPick",
    "DirectBranchPick::Plain = zeroed",
    "BranchFirstPick::Plain = zeroed",
    "BranchRootPick::Plain = zeroed",
    "NestedBranchPick::Plain = zeroed",
    "static if true:\n    static if true:\n        using Wrong as NestedBranchPick\n    using Safe as NestedBranchPick",
)):
    raise SystemExit("inactive/active alias fixture must cover definite view selection and active duplicate registrations")
if "zeroed_inactive_module_alias.elisa" not in SMOKE:
    raise SystemExit("zeroed smoke must exercise the inactive competing module alias")
if not NESTED_FIXTURE.startswith("""# Stage0's analyzer-wide module alias map makes this alias usable from the root module.
module Outer:
    module Views:
        type BorrowedText = sview

    using Views as NestedAlias

def invalid_text() -> i64:
    text: NestedAlias::BorrowedText = zeroed
    return 0
"""):
    raise SystemExit("nested-alias fixture must keep the alias under Outer and consume it from the root module")
if "    zeroed_nested_global_module_alias.elisa \\\n" not in SMOKE:
    raise SystemExit("zeroed safety must cover the Stage0-global alias declared in a nested module")
if not all(fragment in PRECEDENCE_FIXTURE for fragment in (
    "module Outer:",
    "    using Wrong as Pick",
    "using Safe as Pick",
    "type Plain = i64",
    "type Plain = sview",
    "Pick::Plain = zeroed",
    "BranchScopePick::Plain = zeroed",
    "static if true:\n        module Inner:\n            module Wrong:\n                type Plain = sview\n\n            using Wrong as BranchScopePick\n        using Safe as BranchScopePick",
)) or "zeroed_nested_alias_precedence.elisa" not in SMOKE:
    raise SystemExit("zeroed smoke must cover the analyzer-wide ancestor-scope alias winner")
if not all(fragment in POSSIBLE_FIXTURE for fragment in (
    "ELISA_TARGET_OS_WASI",
    "using Wrong as PossibleFirst",
    "using Safe as PossibleFirst",
    "using Safe as PossibleLater",
    "using Wrong as PossibleLater",
    "PossibleFirst::Plain = zeroed",
    "PossibleLater::Plain = zeroed",
    "using Wrong as ParentPossibleFirst",
    "module Outer:",
    "using Safe as ParentPossibleFirst",
    "using Wrong as NestedPossibleLater",
    "using Safe as NestedPossibleLater",
    "ParentPossibleFirst::Plain = zeroed",
    "NestedPossibleLater::Plain = zeroed",
)) or "zeroed_possible_module_alias_order.elisa" not in SMOKE or "invalid_zeroed_count" not in SMOKE:
    raise SystemExit("zeroed possible-alias fixture must distinguish same-scope and cross-scope winners")
if 'invalid_zeroed_count" == "2"' not in SMOKE:
    raise SystemExit("zeroed possible-alias smoke must expect the earlier same-scope and unordered cross-scope diagnostics")
