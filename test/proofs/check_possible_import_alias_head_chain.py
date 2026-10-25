"""Bind chained possible-alias resolution to source and its zeroed regression."""
from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
IMPORTS = (ROOT / "src/semantic/semantic_import_visibility.elisa").read_text()
FIXTURE = (ROOT / "test/repro/zeroed_possible_alias_head_chain.elisa").read_text()
SMOKE = (ROOT / "test/parity/zeroed_reference_safety_smoke.sh").read_text()


def compact(source: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in source.splitlines())


def function_source(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^        def {re.escape(name)}\(.*?(?=^        def |^    public:|\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"missing source-bound helper {name}")
    return compact(match.group(0))


head_target = function_source(IMPORTS, "semantic_possible_import_alias_head_target")
target_prefix = function_source(IMPORTS, "semantic_possible_import_alias_target_prefix")
target_matches = function_source(IMPORTS, "semantic_possible_import_alias_target_matches")
alias_paths = function_source(IMPORTS, "semantic_possible_import_alias_module_path_matches")
alias_precedes = function_source(IMPORTS, "semantic_possible_import_alias_precedes")
alias_cutoff = function_source(IMPORTS, "semantic_possible_import_alias_precedes_position")
alias_can_win = function_source(IMPORTS, "semantic_possible_import_alias_can_win")
alias_branch_stack = function_source(IMPORTS, "semantic_possible_import_alias_branch_stack_relation")
alias_is_definite = function_source(IMPORTS, "semantic_possible_import_alias_is_definite")

if not all(fragment in head_target for fragment in (
    'alias.name!="__using_alias"',
    'target_row.name=="__using_alias_target"',
    "target_row.module==alias.module",
    "canonical_target_count!=1.usize()",
    "found_priorandnotselected_found",
    "semantic_possible_import_alias_precedes_position(alias,import_scope,before_offset,table)",
    "semantic_possible_import_alias_precedes(other,alias,table)",
    "semantic_possible_import_alias_precedes(alias,Ast::EnumAnnotation{owner:name,name:\"__using_alias\",module:selected_scope,line:selected_line,offset:selected_offset},table)",
)):
    raise SystemExit("alias-head selection must pair raw and canonical targets and fail closed on global conflicts")
if not all(fragment in head_target for fragment in (
    "candidate_wins:mutablebool=true",
    "ifselected_found:",
    "raw_target_count:mutableusize=0",
    "canonical_target_count:mutableusize=0",
)) or head_target.index("raw_target_count:mutableusize=0") < head_target.index("candidate_wins:mutablebool=true"):
    raise SystemExit("alias target metadata must be validated only after the global winner is selected")
if not all(fragment in alias_precedes for fragment in (
    "semantic_possible_import_alias_branch_stack_relation(left,right,table)",
    "branch_relation.left_count<branch_relation.right_count",
    "return(true,true)ifbranch_relation.left_count<=branch_relation.right_count",
    "return(true,false)ifbranch_relation.right_count<=branch_relation.left_count",
    "ifnotright_is_branch:return(false,false)ifleft.offset==right.offsetreturn(true,left.offset<right.offset)",
    "ifnotleft_is_branch:return(false,false)ifleft.offset==right.offsetreturn(true,left.offset<right.offset)",
    "both_definite:bool=left_is_branchandright_is_branch",
    "semantic_possible_import_alias_is_definite(left,table)",
    "semantic_possible_import_alias_is_definite(right,table)",
    "named_type_owner_is_lexical(left.module,right.module)",
    "return(false,false)",
)) or not all(fragment in alias_cutoff for fragment in (
    "requester.name==\"__using_alias\"",
    "semantic_possible_import_alias_precedes(alias,requester,table)",
    "named_type_owner_is_lexical(alias.module,scope)",
)):
    raise SystemExit("alias registration order must honor ancestor pre-registration and nested static-branch stacks")
if not all(fragment in alias_branch_stack for fragment in (
    "semantic_possible_import_alias_branch_marker_count(left,table)",
    "semantic_possible_import_alias_branch_marker_at(left,ordinal,table)",
    "left_marker.identity!=right_marker.identity",
    "shared_prefixandleft_stack.count==right_stack.count",
)):
    raise SystemExit("nested static aliases must compare their enclosing branch identity stacks")
if not all(fragment in alias_is_definite for fragment in (
    "table.definite_import_annotations",
    "row.name==alias.name",
    "row.owner==alias.owner",
    "row.module==alias.module",
    "row.line==alias.line",
    "row.offset==alias.offset",
)):
    raise SystemExit("source-order branch ties require both exact aliases to be definite")
if "named_type_owner_is_lexical(candidate.module,import_scope)" in alias_can_win or "best_rank" in alias_can_win or \
        "semantic_possible_import_alias_precedes_position(alias,import_scope,before_offset,table)" not in alias_can_win or \
        "semantic_possible_import_alias_precedes_position(candidate,import_scope,before_offset,table)" not in alias_can_win or \
        "semantic_possible_import_alias_precedes(alias,selected,table)" not in alias_can_win or \
        "returntrueifnotorder.knownororder.precedes" not in alias_can_win or \
        "returnfalseifcandidate_before.knownandnotcandidate_before.precedes" not in alias_can_win or \
        "returnnotcandidate_before.knownorcandidate_before.precedes" not in alias_can_win:
    raise SystemExit("possible aliases must compete in the analyzer-wide registration order, not lexical scope rank")
if not all(fragment in target_prefix for fragment in (
    "depth>=64",
    "semantic_possible_import_alias_head_target(alias_name,import_scope,before_offset,table)",
    "semantic_import_module_path_prefix_matches(candidate_owner,alias.target,alias.scope)",
    "semantic_possible_import_alias_target_prefix(candidate_owner,alias.raw_target,alias.scope,alias.offset,table,depth+1.u32())",
    "source_prefix.matches!=canonical_prefix.matches",
    "semantic_import_path_append_prefix_matches(candidate_owner,canonical_prefix.end,suffix)",
)):
    raise SystemExit("possible alias paths must expand chained heads with bounded, scope-aware resolution")
if "semantic_possible_import_alias_target_matches(candidate_owner,target_row.owner,suffix,target_row.module,target_row.offset,table)" not in alias_paths or \
        "semantic_possible_import_alias_target_matches(candidate_owner,raw_target_row.owner,suffix,raw_target_row.module,raw_target_row.offset,table)" not in alias_paths or \
        "target_prefix.known" not in target_matches or \
        "semantic_import_scope_visible(alias.module,import_scope)" in alias_paths or \
        "semantic_possible_import_alias_can_win(alias,import_scope,before_offset,table)" not in alias_paths:
    raise SystemExit("possible and definite alias paths must share the bounded chained-target matcher")
if not all(fragment in FIXTURE for fragment in (
    "module Nested:",
    "type Borrowed = sview",
    "using Outer as First",
    "module AliasInstaller:",
    "using First::Nested as Maybe",
    "text: Maybe::Borrowed = zeroed",
)) or FIXTURE.index("using Outer as First") > FIXTURE.index("module AliasInstaller:") or "zeroed_possible_alias_head_chain.elisa" not in SMOKE:
    raise SystemExit("zeroed regression must bind a nested possible alias chain to root sview resolution")

print("possible import alias-head chain source binding passed")
