"""Bind Core's global module-alias order to binding resolution and its regression."""
from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src/semantic/resolve_binding_capabilities.elisa"
IMPORTS = ROOT / "src/semantic/semantic_api/table_setup.elisa"
IMPORT_VISIBILITY = ROOT / "src/semantic/semantic_import_visibility.elisa"
REPRO = ROOT / "test/repro/pymodule_alias_direct_static_branch_precedence.elisa"
SMOKE = ROOT / "test/parity/pymodule_alias_direct_static_branch_precedence_smoke.sh"


def compact(source: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in source.splitlines())


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound resolver {name}")
    return compact(match.group(0))


source = SOURCE.read_text()
imports = IMPORTS.read_text()
visibility_source = IMPORT_VISIBILITY.read_text()
precedence = function_source(source, "binding_module_alias_precedes")
global_precedence = function_source(visibility_source, "semantic_possible_import_alias_precedes")
branch_marker_at = function_source(visibility_source, "semantic_possible_import_alias_branch_marker_at")
branch_marker_count = function_source(visibility_source, "semantic_possible_import_alias_branch_marker_count")
branch_stack = function_source(visibility_source, "semantic_possible_import_alias_branch_stack_relation")
definite_alias = function_source(visibility_source, "semantic_possible_import_alias_is_definite")
row = function_source(source, "binding_module_alias_row")
row_before = function_source(source, "binding_module_alias_row_before")
metadata = function_source(source, "binding_import_metadata")
target_resolver = function_source(source, "binding_resolve_module_alias_target")
if not all(rule in precedence for rule in (
    "semantic_possible_import_alias_precedes(left,right,table)",
)) or not all(rule in global_precedence for rule in (
    "left.module==right.module",
    "semantic_import_alias_is_static_branch(left,table)",
    "semantic_import_alias_is_static_branch(right,table)",
    "semantic_possible_import_alias_branch_stack_relation(left,right,table)",
    "both_definite",
    "branch_relation.shared_prefix",
    "named_type_owner_is_lexical(left.module,right.module)",
    "ifright_is_branchandbranch_relation.shared_prefix",
    "branch_relation.left_count<=branch_relation.right_count",
    "return(true,true)ifbranch_relation.left_count<=branch_relation.right_count",
    "ifnotright_is_branch",
    "named_type_owner_is_lexical(right.module,left.module)",
    "ifleft_is_branchandbranch_relation.shared_prefix",
    "branch_relation.right_count<=branch_relation.left_count",
    "return(true,false)ifbranch_relation.right_count<=branch_relation.left_count",
    "ifnotleft_is_branch",
    "return(false,false)ifnotboth_definiteorleft.offset==right.offset",
    "left.offset<right.offset",
)) or not all(rule in branch_marker_at for rule in (
    "marker.identity_id==4294967295",
    "seen==ordinal",
    "return(true,marker.identity_id)",
)) or not all(rule in branch_marker_count for rule in (
    "table.protocol_annotations",
    'marker.name!="__using_alias_static_branch"',
    "marker.identity_id==4294967295",
)) or not all(rule in branch_stack for rule in (
    "shared_count:usize=left_stack.countifleft_stack.count<right_stack.countelseright_stack.count",
    "left_marker.identity!=right_marker.identity",
    "shared_prefixandleft_stack.count==right_stack.count",
)) or not all(rule in definite_alias for rule in (
    "table.definite_import_annotations",
    "row.module==alias.module",
    "row.line==alias.line",
    "row.offset==alias.offset",
)) or not all(rule in row for rule in (
    "table.definite_import_annotations.count",
    "binding_module_alias_precedes(other,candidate,table)",
    "table.possible_import_annotations",
    "binding_module_alias_precedes(possible,selected,table)",
    "notorder.knownororder.precedes",
)) or not all(rule in row_before for rule in (
    "table.definite_import_annotations.count",
    "found_unordered_cutoff",
    "binding_module_alias_precedes(candidate,requester,table)",
    "binding_module_alias_precedes(other,candidate,table)",
    "other_before_requester.knownandnotother_before_requester.precedes",
    "candidate_before_requester.knownandnotcandidate_before_requester.precedes",
    "binding_module_alias_precedes(selected,candidate,table)",
    "notselected_before_candidate.knownornotselected_before_candidate.precedes",
    "binding_module_alias_precedes(possible,requester,table)",
    "before_requester.knownandnotbefore_requester.precedes",
    "binding_module_alias_precedes(possible,selected,table)",
)) or not all(rule in metadata for rule in (
    "requester_count==1.usize()",
    "binding_resolve_module_alias_target(annotation.owner,requester,table)",
)) or not all(rule in target_resolver for rule in (
    "binding_module_alias_row_before(alias_name,requester,table)",
    "table.definite_import_annotations",
    "binding_module_path_join(requester.module,target,table)",
    "binding_resolve_module_alias_target(alias_target,alias,table,depth+1)",
)):
    raise SystemExit(
        "binding alias lookup must use Core's global registration order and preserve "
        "the direct-alias prepass during target canonicalization"
    )
if "named_type_owner_is_lexical" in row or "named_type_owner_is_lexical" in row_before:
    raise SystemExit("module-alias selection must not filter Core's analyzer-wide map lexically")
if "returnBINDING_MODULE_ALIAS_ROW_AMBIGUOUSifnotcandidate_before_requester.known" in row_before or \
        "returnBINDING_MODULE_ALIAS_ROW_AMBIGUOUSifnotother_before_requester.known" in row_before or \
        "returnBINDING_MODULE_ALIAS_ROW_AMBIGUOUSifnotbefore_requester.known" in row_before:
    raise SystemExit("an unordered cutoff contender must be checked against the final winner before making lookup ambiguous")
if not all(fragment in imports for fragment in (
    "semantic_build_import_annotation_views(file, table)",
    "binding_import_metadata(table.definite_import_annotations, table)",
)):
    raise SystemExit("binding alias selection must consume the active import projection")

repro = REPRO.read_text()
smoke = SMOKE.read_text()
if not all(
    fragment in repro
    for fragment in (
        "using FirstProvider as Maybe",
        "static if UNKNOWN_ALIAS_CHOICE:",
        "using SecondProvider as Maybe",
        "static if true:\n    using SecondProvider as Maybe\n\nmodule CutoffChild:",
        "using Maybe::Nested as CutoffNested",
        "nested_branch_alias_cutoff_default",
        "CutoffNested::Mode.High",
        "using Maybe::Nested as SelectedNested",
        "Maybe::Nested::Mode.High",
        "SelectedNested::Mode.High",
        "module AliasContainer:",
        "using ParentAlias::Nested as NestedGlobal",
        "using Provider as ParentAlias",
        "module Child:",
        "NestedGlobal::Mode.High",
        "High = 41",
        "High = 52",
        "High = 73",
        "using NestedBranchProvider as BranchPick",
        "using OuterBranchProvider as BranchPick",
        "nested_branch_alias_default",
        "BranchPick::Mode::Value.High",
        "High = 84",
        "High = 85",
        "using FirstSiblingBranchProvider as SiblingBranchPick",
        "using SecondSiblingBranchProvider as SiblingBranchPick",
        "sibling_branch_alias_default",
        "SiblingBranchPick::Mode::Value.High",
        "High = 86",
        "High = 87",
    )
) or not all(
    fragment in smoke
    for fragment in (
        "pymodule_alias_direct_static_branch_precedence.elisa",
        '"direct_alias_default",',
        '"chained_alias_default",',
        '"nested_branch_alias_cutoff_default",',
        '"default": "41"',
        '"nested_global_alias_default"',
        '"default": "73"',
        '"nested_branch_alias_default"',
        '"default": "85"',
        '"sibling_branch_alias_default"',
        '"default": "86"',
    )
):
    raise SystemExit(
        "resolver regression must cover global direct/branch precedence, nested branch "
        "pre-registration, deferred cutoff ambiguity, and definite sibling-root source order"
    )

print("binding alias branch-precedence source binding passed")
