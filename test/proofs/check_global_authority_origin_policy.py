"""Bind global-authority binder-origin and permission policies to the semantic pass."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
POLICY = ROOT / "src/semantic/global_authority_origin_policy.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
AUTHORITY = ROOT / "src/semantic/check_global_authority.elisa"
AUTHORITY_COVERAGE = ROOT / "src/semantic/check_global_authority_coverage.elisa"
AUTHORITY_ROWS = ROOT / "src/semantic/check_global_authority_rows.elisa"
AUTHORITY_SOURCES = [AUTHORITY, AUTHORITY_COVERAGE, AUTHORITY_ROWS, *sorted((AUTHORITY.parent / "check_global_authority").rglob("*.elisa"))]
AUTHORITY_TYPES = ROOT / "src/semantic/check_global_authority_types.elisa"
AUTHORITY_TYPE_SOURCES = [AUTHORITY_TYPES, AUTHORITY_TYPES.with_name("check_global_authority_types_references.elisa")]
FN_VALUE_SIGNATURES = ROOT / "src/semantic/check_fn_value_effect_row_signatures.elisa"
IMPL_CONFORMANCE = ROOT / "src/semantic/check_impl_conformance.elisa"
POSITIVE = HERE / "global_authority_origin_policy.elisa"
NEGATIVE = HERE / "global_authority_origin_policy_rejected.elisa"
SMOKE = ROOT / "test/parity/mutable_global_grants_smoke.py"
ALIAS_FIXTURE = ROOT / "test/fixtures/effects/qualified_permission_using_alias.elisa"
ALIAS_CONFLICT_FIXTURE = ROOT / "test/fixtures/effects/global_authority_nested_alias_conflict.elisa"
STATIC_BRANCH_ALIAS_FIXTURE = ROOT / "test/fixtures/effects/global_authority_static_branch_alias_conflict.elisa"
ACTIVE_STATIC_ALIAS_FIXTURE = ROOT / "test/fixtures/effects/global_authority_active_static_alias.elisa"
ALIAS_SMOKE = ROOT / "test/parity/effect_handler_stage1_smoke.sh"

parser = argparse.ArgumentParser()
parser.add_argument("--source-only", action="store_true",
                    help="check production and proof bindings without running Elisa-Proof")
ARGS = parser.parse_args()

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(source: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in source.splitlines())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)def {re.escape(name)}(?:\[[^\n]*\])?\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*(?:\[[^\n]*\])?\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def declarations(source: str) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", source))


policy_text = POLICY.read_text()
semantic_text = SEMANTIC.read_text()
authority_text = "\n".join(path.read_text() for path in AUTHORITY_SOURCES)
authority_types_text = "\n".join(path.read_text() for path in AUTHORITY_TYPE_SOURCES)
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()

for fragment in (
    "const NO_ORIGIN: usize = 4294967295",
    "const UNKNOWN_ALIAS: usize = 4294967294",
    "const LOCAL_ALIAS: usize = 4294967293",
):
    if compact(fragment) not in compact(policy_text):
        raise SystemExit(f"global-authority origin sentinel changed: {fragment}")
authority_origin_constants = (
    "const GLOBAL_AUTHORITY_NONE: usize = 4294967295",
    "const GLOBAL_AUTHORITY_UNKNOWN_ALIAS: usize = 4294967294",
    "const GLOBAL_AUTHORITY_LOCAL_ALIAS: usize = 4294967293",
)
if any(compact(fragment) not in compact(authority_text) for fragment in authority_origin_constants):
    raise SystemExit("origin policy sentinels no longer match the semantic pass")

alias_choice = compact(function_section(authority_text, "ga_module_alias_choice"))
alias_registration = compact(function_section(authority_text, "ga_module_alias_registration_precedes"))
if "left_scope==right_scope" not in alias_registration or \
        "current==left_scope" not in alias_registration or \
        "current==right_scope" not in alias_registration or \
        "left_offset<right_offset" not in alias_registration or \
        "ga_module_alias_is_static_branch(left_index,state)" not in alias_registration or \
        "ga_module_alias_is_static_branch(right_index,state)" not in alias_registration:
    raise SystemExit("GlobalAuthority alias precedence no longer models Core's scope prepass and source order")
if not all(fragment in alias_registration for fragment in (
        "returnfalseifleft_is_branchandnotright_is_branch",
        "returntrueifnotleft_is_branchandright_is_branch",
        "returnleft_offset<right_offsetor(left_offset==right_offsetandleft_index<right_index)")):
    raise SystemExit("direct aliases must keep Core's registration priority over static-branch aliases")
alias_static_branch = compact(function_section(authority_text, "ga_module_alias_is_static_branch"))
parser_decl_module = (ROOT / "src/parser/parser_decl_module.elisa").read_text()
alias_static_branch_parser = compact(function_section(parser_decl_module, "record_static_if_branch_rows"))
static_branch_marker_parser = compact(function_section(parser_decl_module, "record_static_if_branch_markers"))
using_alias_parser = compact(function_section(parser_decl_module, "using_alias"))
import_member_parser = compact(function_section(parser_decl_module, "record_from_import_member"))
wildcard_import_parser = compact(function_section(parser_decl_module, "consume_using_target"))
private_member_parser = compact(function_section(parser_decl_module, "record_private_member_if"))
bare_const_member_parser = compact(function_section(parser_decl_module, "bare_const_member"))
const_declaration_parser = compact(function_section((ROOT / "src/parser/parser_types_aggregate.elisa").read_text(), "const_declaration"))
declaration_static_if_parser = compact(function_section((ROOT / "src/parser/parser_decl_impl.elisa").read_text(), "static_if_declaration"))
statement_static_if_parser = compact(function_section((ROOT / "src/parser/parser_stmt.elisa").read_text(), "statement_inner"))
if 'marker.owner=="__static_if_branch"' not in alias_static_branch or \
        'marker.name=="__using_alias_static_branch"' not in alias_static_branch or \
        'marker.detail_name==alias.owner' not in alias_static_branch or \
        "parser.static_if_branch_rows.count.u32()!=parser.static_if_depth" not in static_branch_marker_parser or \
        "forbranch_identityinparser.static_if_branch_rows" not in static_branch_marker_parser or \
        'owner:"__static_if_branch"' not in static_branch_marker_parser or \
        "identity_id:branch_identity" not in static_branch_marker_parser or \
        "identity_id:4294967295" not in static_branch_marker_parser or \
        'parser.record_static_if_branch_markers(marker_name,detail_name,parser.current_module,token.line,token.start)' not in alias_static_branch_parser or \
        'parser.record_static_if_branch_rows("__using_alias_static_branch",alias_name,alias_token)' not in using_alias_parser or \
        'parser.record_static_if_branch_rows("__from_member_static_branch",member,token)' not in import_member_parser or \
        'parser.record_static_if_branch_rows("__binding_wildcard_import_static_branch",full_text,target_token)' not in wildcard_import_parser or \
        'parser.record_static_if_branch_markers("__private_member_static_branch",member_name,parser.current_module,section_line,member_position.offset)' not in private_member_parser or \
        'parser.record_static_if_branch_rows("__const_static_branch",Lexer::text_or_empty(name_token,parser.source,parser.source_length),token)' not in bare_const_member_parser or \
        'parser.record_static_if_branch_rows("__const_static_branch",Lexer::text_or_empty(name_token,parser.source,parser.source_length),token)' not in const_declaration_parser or \
        "branch_row:u32=parser.static_if_lines.count.u32()-1" not in declaration_static_if_parser or \
        "parser.static_if_branch_rows<-parser.static_if_branch_rows.push(branch_row)" not in declaration_static_if_parser or \
        "parser.static_if_branch_rows<-parser.static_if_branch_rows.truncate(parser.static_if_branch_rows.count-1.usize())" not in declaration_static_if_parser or \
        "parser.static_if_branch_rows<-parser.static_if_branch_rows.push(static_branch_row)" not in statement_static_if_parser or \
        "parser.static_if_branch_rows<-parser.static_if_branch_rows.truncate(parser.static_if_branch_rows.count-1.usize())" not in statement_static_if_parser:
    raise SystemExit("static-if alias origin is not carried from parsing into GlobalAuthority registration order")
static_row_selection = compact(function_section(authority_text, "ga_static_if_row_selection"))
static_condition_fold = compact(function_section(authority_text, "ga_static_if_condition_value"))
static_target_fold = compact(function_section(authority_text, "ga_static_if_target_constant"))
static_target_predicate = compact(function_section(authority_text, "ga_static_if_target_predicate"))
alias_branch_selection = compact(function_section(authority_text, "ga_module_alias_branch_selection"))
if not all(fragment in static_condition_fold for fragment in (
        "Expr.Unary(operator,operand,_)",
        "ga_static_if_named_constant_value(name,current_module,state,depth+1)",
        "BackendConstArithmetic::add_is_safe(left_value.value,right_value.value)",
        "BackendConstArithmetic::multiply_is_safe(left_value.value,right_value.value)",
        "BackendConstArithmetic::division_is_safe(left_value.value,right_value.value)",
        "operator==TokenKind.LShift",
        "operator==TokenKind.RShift",
        "Expr.Binary(left,operator,right,_)")):
    raise SystemExit("GlobalAuthority static-if fold no longer follows the backend's checked integer expression subset")
if not all(fragment in static_target_fold for fragment in (
        'getenv("ELISA_STAGE1_TRIPLE")istarget_triple',
        "return(false,0)ifexplicit_triple")) or \
        'name=="ELISA_TARGET_OS_LINUX"' not in static_target_predicate or \
        "return(false,0,true)ifga_static_if_target_predicate(name)" not in static_condition_fold:
    raise SystemExit("unresolved explicit-target predicates must stay backend-foldable and uncertain to GlobalAuthority")
if not all(fragment in static_row_selection for fragment in (
        "static_if_depths[row]!=branch_depth",
        "branch_kind==StaticIfBranch::Kind.Fallback",
        "ga_static_if_condition_value(state.static_if_conds[row],current_module,state,depth+1)",
        "condition.backend_folds",
        "return(false,false)ifcondition.backend_folds",
        "return(true,row==branch_row)",
        "return(true,false)ifrow==branch_row")) or not all(fragment in alias_branch_selection for fragment in (
        'marker.owner!="__static_if_branch"',
        'marker.name!="__using_alias_static_branch"',
        "marker.detail_name!=alias.owner",
        "ga_static_if_row_selection(marker.identity_id.usize(),alias.module,state)",
        "return(true,false)ifbranch.knownandnotbranch.selected",
        "unknown<-trueifnotbranch.known",
        "return(false,false)ifunknown")):
    raise SystemExit("GlobalAuthority must follow known static-if selection and fail closed on unknown branch ancestry")
import_branch_selection = compact(function_section(authority_text, "ga_import_annotation_branch_selection"))
import_index = compact(function_section((ROOT / "src/semantic/check_global_authority/annotation_index.elisa").read_text(), "ga_index_import_annotations"))
if not all(fragment in import_branch_selection for fragment in (
        'marker_owner:sview="__static_if_branch"',
        'marker_name:sview="__from_member_static_branch"ifimport_row.owner=="__from_member"else"__binding_wildcard_import_static_branch"',
        "marker.owner!=marker_owner",
        "marker.detail_name!=marker_detail",
        "ga_static_if_row_selection(marker.identity_id.usize(),import_row.module,state)",
        "return(false,false)ifunknown")) or \
        "ga_import_annotation_branch_selection(annotation,state)" not in import_index or \
        "ifnotbranch.known:state.static_import_uncertain<-true" not in import_index or \
        "continueifnotbranch.active" not in import_index:
    raise SystemExit("GlobalAuthority import indexing must exclude inactive imports and preserve uncertainty for possible imports")
import_uncertainty = compact((ROOT / "src/semantic/check_global_authority/incremental.elisa").read_text())
if "ga_mark_all_possible_global_effects(&state)ifstate.static_import_uncertain" not in import_uncertainty:
    raise SystemExit("uncertain static imports must conservatively retain possible global effects")
if not all(fragment in import_uncertainty for fragment in (
        "forconst_indexin0..<table.immutable_const_names.count",
        "state.static_const_names.push(table.immutable_const_names[const_index])",
        "state.static_const_values.push(table.immutable_const_values[const_index]ifconst_index<table.immutable_const_values.countelseAst::Expr.Absent)",
        "state.static_const_owners.push(table.symbols[const_row].module_ownerifconst_row<table.symbols.countelse\"\")")):
    raise SystemExit("GlobalAuthority must receive source-constant values and lexical owners for static-if folding")
alias_registration_index = compact(function_section(authority_text, "ga_module_alias_registration_index"))
if 'alias.name!="__using_alias"' not in alias_registration_index or \
        "alias.offset!=offset" not in alias_registration_index or \
        "ga_module_text(alias.module,state)!=scope" not in alias_registration_index:
    raise SystemExit("GlobalAuthority alias-target cutoffs are not bound to the declaration's registration position")
if "ga_module_alias_registration_precedes(alias_scope,alias.offset,alias_index,selected_scope,selected_alias.offset,selected_index,state)" not in alias_choice or \
        "ga_module_alias_registration_precedes(alias_scope,alias.offset,alias_index,lexical_scope,before_alias.offset,before_index,state)" not in alias_choice or \
        "before_index:usize=ga_module_alias_registration_index(lexical_scope,before_offset,state)" not in alias_choice:
    raise SystemExit("GlobalAuthority aliases do not select Core's first registered program-wide target")
parts_resolve = compact(function_section(authority_text, "ga_module_parts_resolve"))
parts_lexical = parts_resolve.find("ga_module_lexical_parts_path(parts,lexical_scope,state)")
parts_alias = parts_resolve.find("ga_module_alias_choice(parts[0],lexical_scope,state,depth)")
parts_root = parts_resolve.find("raw_root:usize=ga_child(state,0,parts[0])")
if min(parts_lexical, parts_alias, parts_root) < 0 or not parts_lexical < parts_alias < parts_root:
    raise SystemExit("GlobalAuthority expression/store paths must try complete lexical candidates, aliases, then root spelling")
alias_resolve = compact(function_section(authority_text, "ga_module_alias_resolve"))
if "before_offset:u32=GLOBAL_AUTHORITY_OFFSET_NONE" not in alias_resolve or \
        "ga_module_alias_choice(first,lexical_scope,state,depth)" not in alias_resolve or \
        "ga_module_alias_target_resolve(target.path,alias.scope,state,depth+1,alias_row.offset)" not in alias_resolve:
    raise SystemExit("qualified GlobalAuthority module resolution does not use registered aliases and declaration offsets for target recursion")
alias_lexical = alias_resolve.find("ga_module_lexical_path(path,first,start,lexical_scope,state)")
alias_choice_position = alias_resolve.find("ga_module_alias_choice(first,lexical_scope,state,depth)")
alias_suffix = alias_resolve.find("alias_path:usize=ga_module_path_suffix(path,start,resolved,state)")
alias_root = alias_resolve.find("raw_root:usize=ga_child(state,0,first)")
if min(alias_lexical, alias_choice_position, alias_suffix, alias_root) < 0 or not alias_lexical < alias_choice_position < alias_suffix < alias_root:
    raise SystemExit("GlobalAuthority text paths must try complete lexical candidates, alias suffixes, then root spelling")
alias_target = compact(function_section(authority_text, "ga_module_alias_target_resolve"))
if "ga_module_alias_choice(first,declaration_scope,state,depth,before_offset)" not in alias_target or \
        "ga_module_alias_target_resolve(target.path,alias.scope,state,depth+1,alias_row.offset)" not in alias_target:
    raise SystemExit("GlobalAuthority alias-target recursion drops its source registration cutoff")
if not all(fragment in alias_choice for fragment in (
        "branch_selection:(known:bool,active:bool)=ga_module_alias_branch_selection(alias_index,state)",
        "continueifbranch_selection.knownandnotbranch_selection.active",
        "ifnotbranch_selection.known:",
        "uncertain_index<-alias_index",
        "return(true,true,uncertain_index,uncertain_scope)")):
    raise SystemExit("alias choice must skip proven-inactive branches and preserve unknown branch precedence conservatively")
text_module = compact(function_section(authority_text, "ga_text_module"))
if "ga_module_alias_resolve(path,lexical_scope,state,0,true,before_offset)" not in text_module:
    raise SystemExit("GlobalAuthority text module lookup drops its source offset")
for helper_name in ("ga_module", "ga_module_readonly"):
    helper = compact(function_section(authority_text, helper_name))
    if "ga_module_parts_resolve(parts,resolved_scope,state,depth,Ast::expr_pos(expression).offset)" not in helper:
        raise SystemExit(f"{helper_name} drops the source offset while resolving qualified module expressions")
store_slot = compact(function_section(authority_text, "ga_store_slot"))
if "ga_module_parts_resolve(module_parts,state.module_scope,state,0,before_offset)" not in store_slot:
    raise SystemExit("global-store module lookup drops its source offset")
statement_walk = compact(function_section(authority_text, "ga_statements_inner"))
if "ga_store_slot(clause[0],state,at.offset)" not in statement_walk:
    raise SystemExit("global-store statement lookup does not forward the statement offset")
permission_slot = compact(function_section(authority_text, "ga_permission_slot"))
if "ga_text_module(head[0:last_scope],lexical_scope,state,before_offset)" not in permission_slot:
    raise SystemExit("qualified permission lookup drops its source offset")
coverage = compact(function_section(authority_text, "ga_ref_covers"))
if "ga_capability_slot(grant,grant_scope,state,grant_before_offset)" not in coverage or "ga_permission_slot(required,required_scope,state,required_before_offset)" not in coverage:
    raise SystemExit("authority coverage does not bind grant and required aliases to their source offsets")
row_add = compact(function_section(authority_text, "ga_row_add"))
if "before_offset:u32=GLOBAL_AUTHORITY_OFFSET_NONE" not in row_add or \
        "ga_capability_slot(ref,lexical_scope,state,before_offset)" not in row_add or \
        "ga_permission_slot(ref,lexical_scope,state,before_offset)" not in row_add or \
        "state.capability_offsets[row]" not in row_add:
    raise SystemExit("effect-row normalization drops the source offset while resolving capability and permission aliases")
row_leaf = compact(function_section(authority_text, "ga_row_add_leaf"))
if "state.effect_row_offsets.push(before_offset)" not in row_leaf:
    raise SystemExit("normalized effect rows do not retain the source offset used for alias resolution")
row_replay = compact(function_section(authority_text, "ga_resolve_initial_rows"))
if "state.effect_row_offsets[row]" not in row_replay:
    raise SystemExit("signature effect-row replay loses its original alias source offset")
row_close = compact(function_section(authority_text, "ga_close_rows"))
if "state.effect_row_offsets[row]" not in row_close:
    raise SystemExit("call-graph effect-row propagation loses the originating alias source offset")
row_publish = compact(function_section(authority_text, "ga_publish_rows"))
if "effect_row_offsets:darray[u32]&" not in row_publish or \
        "table.effect_canonical_row_offset" not in row_publish:
    raise SystemExit("canonical effect rows do not publish their source offsets")
generic_rows = compact(function_section(authority_text, "ga_generic_call_rows_at"))
if "table.effect_canonical_row_offset[row]" not in generic_rows:
    raise SystemExit("call-site effect coverage does not use each normalized row's source offset")
refs_at = compact(function_section(authority_text, "ga_refs_cover_at"))
if "offsets[index]" not in refs_at or "ga_ref_covers(grants[index],required" not in refs_at:
    raise SystemExit("stored authority grants are not resolved at their individual declaration offsets")
lambda_effects = compact(function_section(authority_types_text, "ga_declared_global_members"))
if 'ga_ref_covers(annotation.name,"Global.Read",ga_module_text(annotation.module,state),0,state,0,annotation.offset' not in lambda_effects or \
        'ga_ref_covers(annotation.name,"Global.Write",ga_module_text(annotation.module,state),0,state,0,annotation.offset' not in lambda_effects:
    raise SystemExit("lambda effect inference drops the annotation source offset")
fn_value_text = FN_VALUE_SIGNATURES.read_text()
fn_value_families = compact(function_section(fn_value_text, "fver_type_families"))
fn_value_rows = compact(function_section(fn_value_text, "fver_canonical_within"))
if "ga_capability_slot(ref,origin_scope,context,before_offset)" not in fn_value_families or \
        "context.capability_offsets[row]" not in fn_value_families or \
        "table.effect_canonical_row_offset[row]" not in fn_value_rows or \
        "ga_refs_cover_at(expected_refs,expected_scopes,expected_offsets" not in fn_value_rows:
    raise SystemExit("function-value effect comparison drops source offsets from actual or expected alias rows")
impl_text = IMPL_CONFORMANCE.read_text()
impl_effects = compact(function_section(impl_text, "imc_protocol_effects"))
impl_check = compact(function_section(impl_text, "imc_check_effects"))
if "offsets:mutabledarray[u32]&" not in impl_effects or "offsets.push(effect.offset)" not in impl_effects or \
        "ga_refs_cover_at(allowed,allowed_scopes,allowed_offsets" not in impl_check or \
        "table.effect_canonical_row_offset[row]" not in impl_check:
    raise SystemExit("protocol effect conformance drops source offsets while comparing aliases")
alias_atom = (ROOT / "test/atoms/authority_coverage.elisa").read_text()
for probe in (
    'ga_ref_covers("P::Cap.Read", "Old::Cap.Read", 0, 0, &permission_aliases, 0, 125, 125)',
    'ga_ref_covers("P::Cap.Read", "Old::Cap.Read", 0, 0, &permission_aliases, 0, 150, 150)',
    'ga_ref_covers("P::Cap.Read", "New::Cap.Read", 0, 0, &permission_aliases, 0, 150, 150)',
    'return 59 if ga_text_module("P::Leaf", 0, permission_aliases, 125) != old_permission_leaf',
    'return 60 if ga_text_module("P::Leaf", 0, permission_aliases, 150) != new_permission_leaf',
    'return 61 if ga_module_alias_resolve("P::Leaf", 0, permission_aliases, 0, true, 125) != old_permission_leaf',
    'return 62 if ga_module_alias_resolve("P::Leaf", 0, permission_aliases, 0, true, 150) != new_permission_leaf',
):
    if probe not in alias_atom:
        raise SystemExit(f"authority coverage atom is missing source-order alias probe {probe}")
for probe in (
    'return 21 if not conflicting_choice.found or conflicting_choice.ambiguous or conflicting_choice.index != 0',
    'return 36 if ga_module_alias_resolve("Alias", 0.usize(), conflicting_aliases) != conflicting_actual',
):
    if probe not in alias_atom:
        raise SystemExit(f"authority coverage atom has stale first-registration expectation {probe}")
for probe in (
    '_ = ga_row_add(0, "Choice", true, &permission_aliases, 0, 0, 150)',
    'return 42 if row_ref != "P::Cap.Read" or row_offset != 120',
    'ga_ref_covers(row_ref, "Old::Cap.Read", 0, 0, &permission_aliases, 0, row_offset, 125)',
    'ga_ref_covers(row_ref, "New::Cap.Read", 0, 0, &permission_aliases, 0, row_offset, 150)',
    'ga_edge_rows(0, 1, &edge_filters)',
    'ga_edge_ref_suppressed(0, "Old::Unsafe", 0, 150, edge_filters)',
    'edge_old_scope: usize = ga_collect_module(0, "Old", edge_filters)',
    'edge_new_scope: usize = ga_collect_module(0, "New", edge_filters)',
    'return 48 if ga_text_module("P", 0, edge_filters, 125) != edge_old_scope',
    'return 49 if ga_text_module("P", 0, edge_filters, 150) != edge_new_scope',
    'return 53 if not tied_conflict.found or tied_conflict.ambiguous or tied_conflict.index != 0',
    'return 54 if ga_module_alias_resolve("Tie::Leaf", 0.usize(), tied_aliases) != tied_actual_leaf',
    'return 55 if ga_text_module("Tie::Leaf", 0.usize(), tied_aliases) != tied_actual_leaf',
    'return 57 if not same_target_tie.found or same_target_tie.ambiguous or same_target_tie.index != 4',
    'return 58 if ga_module_alias_resolve("Same::Leaf", 0.usize(), tied_aliases) != tied_actual_leaf',
):
    if probe not in alias_atom:
        raise SystemExit(f"authority coverage atom is missing effect-row alias probe {probe}")
for probe in (
    'Ast::EnumAnnotation{owner: "__static_if_branch", name: "__using_alias_static_branch", detail_name: "Shared", line: 90, module: "", offset: 90, identity_id: 0}',
    'return 63 if not branch_choice.found or branch_choice.ambiguous or branch_choice.index != 3',
    'return 65 if ga_module_alias_resolve("Shared::Leaf", 0.usize(), branch_aliases) != direct_target_leaf',
    'Ast::EnumAnnotation{owner: "__static_if_branch", name: "__using_alias_static_branch", detail_name: "Shared", line: 91, module: "", offset: 100, identity_id: 1}',
    'static_if_conds: [Ast::Expr.BoolLit(false, alias_branch_at), Ast::Expr.Absent]',
    'static_if_kinds: [StaticIfBranch::Kind.ChainHead, StaticIfBranch::Kind.Fallback]',
    'return 66 if not selected_branch_choice.found or selected_branch_choice.ambiguous or selected_branch_choice.index != 3',
    'unknown_branch_condition: Ast::Expr = Ast::Expr.Scope(Ast::Expr.Ident("Feature", alias_branch_at), "Enabled", alias_branch_at)',
    'return 68 if not unknown_branch_choice.found or not unknown_branch_choice.ambiguous',
    'Ast::Expr.Ident("UNKNOWN_STATIC_CONDITION", alias_branch_at)',
    'return 74 if not unfoldable_fallback_choice.found or unfoldable_fallback_choice.ambiguous or unfoldable_fallback_choice.index != 0',
    'return 75 if not backend_unknown_fallback_choice.found or not backend_unknown_fallback_choice.ambiguous',
    'identity_id: 0},\n                        Ast::EnumAnnotation{owner: "__static_if_branch", name: "__using_alias_static_branch", detail_name: "Shared", line: 92, module: "", offset: 120, identity_id: 1}',
    'static_if_depths: [0, 1]',
    'return 69 if nested_branch_choice.found or nested_branch_choice.ambiguous',
):
    if probe not in alias_atom:
        raise SystemExit(f"authority coverage atom is missing static-branch registration probe {probe}")
for probe in (
    'Ast::EnumAnnotation{owner: "__static_if_branch", name: "__from_member_static_branch", detail_name: "hidden", line: 101, module: "", offset: 101, identity_id: 0}',
    'Ast::EnumAnnotation{owner: "__static_if_branch", name: "__binding_wildcard_import_static_branch", detail_name: "InactiveWildcard", line: 103, module: "", offset: 103, identity_id: 2}',
    'Ast::EnumAnnotation{owner: "__static_if_branch", name: "__binding_wildcard_import_static_branch", detail_name: "ActiveWildcard", line: 104, module: "", offset: 104, identity_id: 3}',
    'Ast::Expr.Ident("UNKNOWN_STATIC_CONDITION", alias_branch_at)',
    'ga_index_import_annotations(&branch_imports)',
    'return 70 if branch_imports.import_annotations.count != 2',
    'return 71 if branch_imports.import_annotations[0].owner != "__from_member" or branch_imports.import_annotations[0].name != "visible"',
    'return 72 if branch_imports.import_annotations[1].name != "__binding_wildcard_import" or branch_imports.import_annotations[1].owner != "ActiveWildcard"',
    'return 77 if not branch_imports.static_import_uncertain',
    'arithmetic_static_condition: Ast::Expr = Ast::Expr.Binary(Ast::Expr.Binary(Ast::Expr.IntLit(1, alias_branch_at), TokenKind.Plus, Ast::Expr.IntLit(1, alias_branch_at), alias_branch_at), TokenKind.EqEq, Ast::Expr.IntLit(2, alias_branch_at), alias_branch_at)',
    'return 73 if not folded_static_condition.known or folded_static_condition.value != 1 or not folded_static_condition.backend_folds',
    'static_const_names: ["SOURCE_FLAG"]',
    'return 76 if not source_const_condition.known or source_const_condition.value != 1 or not source_const_condition.backend_folds',
):
    if probe not in alias_atom:
        raise SystemExit(f"authority coverage atom is missing static-import branch-selection probe {probe}")
alias_fixture = ALIAS_FIXTURE.read_text()
alias_smoke = ALIAS_SMOKE.read_text()
if not (
    alias_fixture.index("using Backend::Parent as ParentAlias") <
    alias_fixture.index("using ParentAlias as CapabilityScope") <
    alias_fixture.index("def caller()") <
    alias_fixture.index("can CapabilityScope::Cap.Read") <
    alias_fixture.rindex("using Backend::Alternate as CapabilityScope")
):
    raise SystemExit("qualified permission alias fixture no longer shadows after the earlier grant")
if 'run_positive "qualified_permission_using_alias.elisa"' not in alias_smoke:
    raise SystemExit("qualified permission alias fixture is not bound to the Stage1 effect smoke")
if "run_negative \"global_authority_nested_alias_conflict.elisa\" 'conflicting alias: \"Shared\" already aliases module \"RootTarget\", cannot also alias \"Parent.NestedTarget\"'" not in alias_smoke:
    raise SystemExit("nested alias-conflict fixture is not bound to its expected negative diagnostic")
alias_conflict_fixture = ALIAS_CONFLICT_FIXTURE.read_text()
nested_conflict = alias_conflict_fixture.find("using NestedTarget as Shared")
root_conflict = alias_conflict_fixture.find("using RootTarget as Shared")
if nested_conflict < 0 or root_conflict < 0 or nested_conflict >= root_conflict or \
        "# Core registers direct aliases in the current block before descending into nested modules." not in alias_conflict_fixture or \
        "Shared::slot" not in alias_conflict_fixture:
    raise SystemExit("nested alias-conflict control no longer exercises Core's reversed textual/registration order")
static_branch_alias_fixture = STATIC_BRANCH_ALIAS_FIXTURE.read_text()
static_nested_alias = static_branch_alias_fixture.find("using NestedTarget as Shared")
static_direct_alias = static_branch_alias_fixture.find("using RootTarget as Shared")
if "static if true:" not in static_branch_alias_fixture or static_nested_alias < 0 or static_direct_alias < 0 or static_nested_alias >= static_direct_alias or "Shared::slot" not in static_branch_alias_fixture:
    raise SystemExit("static-branch alias fixture no longer covers Core's direct-registration-before-active-branch order")
if 'run_negative "global_authority_static_branch_alias_conflict.elisa" \'conflicting alias: "Shared" already aliases module "RootTarget", cannot also alias "NestedTarget"\'' not in alias_smoke:
    raise SystemExit("static-branch alias fixture is not bound to the Core first-registration diagnostic")
if not all(probe in alias_smoke for probe in (
        "grep -cF 'conflicting alias:' \"$static_alias_log\") == 1",
        "requires can[RootTarget::slot.Read]",
        'run_negative "global_authority_static_branch_alias_conflict.elisa"')):
    raise SystemExit("static-branch alias smoke must reject extra conflict or wrong-target authority diagnostics")
active_static_alias_fixture = ACTIVE_STATIC_ALIAS_FIXTURE.read_text()
if not all(fragment in active_static_alias_fixture for fragment in (
        "static if false:",
        "using InactiveTarget as Shared",
        "static else:",
        "using ActiveTarget as Shared",
        "can Shared::slot.Read:",
        "ActiveTarget::needs_read()")) or 'run_positive "global_authority_active_static_alias.elisa"' not in alias_smoke:
    raise SystemExit("active-static alias control must prove inactive arms do not shadow the selected permission target")

row_edges = compact(function_section((ROOT / "src/semantic/check_global_authority_rows.elisa").read_text(), "ga_edge_rows"))
row_filter_check = compact(function_section((ROOT / "src/semantic/check_global_authority_rows.elisa").read_text(), "ga_edge_ref_suppressed"))
if "row_edge_filter_offsets.push(state.firewall_offsets[index])" not in row_edges or \
        "state.row_edge_filter_offsets[filter]" not in row_filter_check:
    raise SystemExit("call-graph firewall snapshots drop their source offsets")

policy_body = compact(function_section(policy_text, "pattern_binding_origin"))
expected_policy = compact("""
def pattern_binding_origin(contains_reference: bool, source_origin: usize) -> usize:
    ensure result == (
        NO_ORIGIN if not contains_reference else
        (source_origin if source_origin != NO_ORIGIN else UNKNOWN_ALIAS)
    )
    return NO_ORIGIN if not contains_reference
    return source_origin if source_origin != NO_ORIGIN
    return UNKNOWN_ALIAS
""")
if policy_body != expected_policy:
    raise SystemExit("production binder-origin policy changed from its exact origin-preservation rule")
join_body = compact(function_section(policy_text, "join_reference_origins"))
expected_join = compact("""
def join_reference_origins(left: usize, right: usize) -> usize:
    ensure result == (
        right if left == NO_ORIGIN else
        (left if right == NO_ORIGIN else
            (left if left == right else UNKNOWN_ALIAS))
    )
    return right if left == NO_ORIGIN
    return left if:
        right == NO_ORIGIN
        left == right
    return UNKNOWN_ALIAS
""")
if join_body != expected_join:
    raise SystemExit("production reference-origin join changed from its exact conservative lattice rule")
opaque_body = compact(function_section(policy_text, "opaque_expression_origin"))
expected_opaque = compact("""
def opaque_expression_origin(type_known: bool, contains_reference: bool) -> usize:
    ensure result == (UNKNOWN_ALIAS if not type_known or contains_reference else NO_ORIGIN)
    return UNKNOWN_ALIAS if:
        not type_known
        contains_reference
    return NO_ORIGIN
""")
if opaque_body != expected_opaque:
    raise SystemExit("opaque-expression origin policy must preserve unknown or reference-bearing values")
constructor_body = compact(function_section(policy_text, "constructor_origin"))
expected_constructor = compact("""
def constructor_origin(summary: usize, reference_fields_complete: bool) -> usize:
    ensure result == (summary if reference_fields_complete else UNKNOWN_ALIAS)
    return summary if reference_fields_complete
    return UNKNOWN_ALIAS
""")
if constructor_body != expected_constructor:
    raise SystemExit("incomplete reference-bearing constructors must discard partial origin summaries")
permission_body = compact(function_section(policy_text, "unknown_alias_permission"))
expected_permission = compact('''
def unknown_alias_permission(write: bool) -> sview:
    ensure result == ("Global.Write" if write else "Global.Read")
    return "Global.Write" if write else "Global.Read"
''')
if permission_body != expected_permission:
    raise SystemExit("production unknown-alias permission mapping changed from its exact read/write rule")
conservative_origin_body = compact(function_section(policy_text, "requires_unknown_alias_permission"))
expected_conservative_origin = compact('''
def requires_unknown_alias_permission(origin: usize) -> bool:
    ensure result == (origin == NO_ORIGIN or origin == UNKNOWN_ALIAS)
    return origin == NO_ORIGIN or origin == UNKNOWN_ALIAS
''')
if conservative_origin_body != expected_conservative_origin:
    raise SystemExit("missing and unknown origins must use the exact fail-closed access classification")

policy_include = 'include "./global_authority_origin_policy.elisa"'
authority_include = 'include "./check_global_authority.elisa"'
if policy_include not in semantic_text or authority_include not in semantic_text or \
        semantic_text.index(policy_include) > semantic_text.index(authority_include):
    raise SystemExit("semantic facade must load the proved origin policy before global authority")

pattern_metadata = compact(function_section(authority_text, "ga_pattern_binding_metadata"))
metadata_steps = (
    "is_reference: bool = ga_type_id_is_reference(binding_type_id, table) or (binding_type_id == 0 and whole_value and ga_expression_is_reference(subject, state, 0))",
    "contains_reference: mutable bool = ga_type_id_contains_reference(binding_type_id, table) or is_reference",
    "source_origin: usize = ga_reference_origin(subject, state, 0) if contains_reference else GLOBAL_AUTHORITY_NONE",
    "global_origin: mutable usize = SemanticGlobalAuthorityOrigin::pattern_binding_origin(contains_reference, source_origin)",
    "global_origin <- GLOBAL_AUTHORITY_LOCAL_ALIAS if contains_reference and source_origin == GLOBAL_AUTHORITY_NONE",
    "return (type_expression, global_origin, type_scope)",
)
metadata_positions = [pattern_metadata.find(compact(fragment)) for fragment in metadata_steps]
if any(position < 0 for position in metadata_positions) or metadata_positions != sorted(metadata_positions):
    raise SystemExit("match-pattern binding no longer forwards its type and source origin through the proved policy")
if "iftype_expressionisbinding_type_expression:contains_reference<-contains_referenceorga_type_expression_contains_reference(binding_type_expression,state,0)" not in pattern_metadata:
    raise SystemExit("match binders must classify nested references in named aggregate types")
if "return(type_expression,GLOBAL_AUTHORITY_NONE)" in pattern_metadata or \
        "return(type_expression,GLOBAL_AUTHORITY_UNKNOWN_ALIAS)" in pattern_metadata:
    raise SystemExit("match-pattern origin bypasses the proved policy with an unconditional fallback")

expression_walk = compact(function_section(authority_text, "ga_expression_inner"))
statement_walk = compact(function_section(authority_text, "ga_statements_inner"))
if "ga_type_id_contains_reference(binding_type_id,table)" not in expression_walk or \
        "iterable_origin:usize=ga_reference_origin(iterable,state,0)" not in expression_walk or \
        "SemanticGlobalAuthorityOrigin::pattern_binding_origin(binding_has_references,iterable_origin)" not in expression_walk or \
        "SemanticGlobalAuthorityOrigin::pattern_binding_origin(extra_binding_has_references[extra_index],iterable_origin)" not in expression_walk or \
        "ga_iteration_binding_type_expression(iterable,binding_type_id" not in expression_walk:
    raise SystemExit("comprehension binders must preserve each item type and reference-origin summary")
if "ga_type_id_contains_reference(binding_type_id,table)" not in statement_walk or \
        "iterable_origin:usize=ga_reference_origin(iterable,state,0)" not in statement_walk or \
        "binding_reference_flags.push(binding_has_references)" not in statement_walk or \
        "SemanticGlobalAuthorityOrigin::pattern_binding_origin(binding_reference_flags[binding_index],iterable_origin)" not in statement_walk or \
        "ga_iteration_binding_type_expression(iterable,binding_type_id" not in statement_walk:
    raise SystemExit("loop binders must preserve each item type and reference-origin summary")
arms_body = compact(function_section(authority_text, "ga_arms_inner"))
if "state.local_global_origins.push(metadata.global_origin)" not in arms_body:
    raise SystemExit("match-arm binders no longer retain the proved origin metadata")

access_body = compact(function_section(authority_text, "ga_access"))
if "elifSemanticGlobalAuthorityOrigin::requires_unknown_alias_permission(alias_origin):table<-ga_access_unknown_alias(Ast::expr_pos(expression),write,state,table)canGlobal{Read,Write}" not in access_body:
    raise SystemExit("unknown binder origins no longer route accesses through conservative authority requirements")
if "ifga_expression_is_reference(expression,state,0):ifalias_origin<state.globals.count:" not in access_body:
    raise SystemExit("aggregate origin summaries must not be mistaken for direct global accesses")
rebind_body = compact(function_section(authority_text, "ga_statements_inner"))
if "origin:usize=ga_update_reference_origin(target,value,state)" not in rebind_body or \
        "iforigin<state.globals.count:table<-ga_access_slot(origin,Ast::expr_pos(value),true,false,state,table)canGlobal{Read,Write}" not in rebind_body:
    raise SystemExit("reference rebinds must retain their new origin and charge writes to exact global roots")
rebind_origin = compact(function_section(authority_text, "ga_update_reference_origin"))
if "source_origin:usize=ga_reference_rebind_origin(value,state,0)" not in rebind_origin or \
        "state.local_global_origins[local_index]<-GLOBAL_AUTHORITY_UNKNOWN_ALIAS" not in rebind_origin or \
        "returnstate.local_global_origins[local_index]" not in rebind_origin:
    raise SystemExit("reference rebinds must preserve unresolved aliases for conservative checks at later access")
write_place_body = compact(function_section(authority_text, "ga_write_place_inner"))
if "ifga_expression_is_reference(expression,state,0):table<-ga_access(expression,true,state,table)canGlobal{Read,Write}" not in write_place_body:
    raise SystemExit("writes through typed aggregate reference fields must consult their preserved origin")
origin_walk = compact(function_section(authority_text, "ga_reference_origin"))
for fragment in (
    "Expr.Array(elements,_)|Expr.Tuple(elements,_)|Expr.SetLit(elements,_) ",
    "ga_join_origins(state,origin,element_origin)",
    "ga_join_origins(state,origin,key_origin)",
    "ga_join_origins(state,origin,value_origin)",
):
    if compact(fragment) not in origin_walk:
        raise SystemExit("aggregate reference-origin summaries no longer join all contained value origins")
join_origins = compact(function_section(authority_text, "ga_join_origins"))
for fragment in (
    "joined:usize=SemanticGlobalAuthorityOrigin::join_reference_origins(left,right)",
    "returnjoinedifjoined!=GLOBAL_AUTHORITY_UNKNOWN_ALIAS",
    "returnGLOBAL_AUTHORITY_UNKNOWN_ALIASifleft==GLOBAL_AUTHORITY_UNKNOWN_ALIASorright==GLOBAL_AUTHORITY_UNKNOWN_ALIAS",
    "returnGLOBAL_AUTHORITY_UNKNOWN_ALIASifleft<state.globals.countorright<state.globals.count",
    "returnGLOBAL_AUTHORITY_LOCAL_ALIAS",
):
    if fragment not in join_origins:
        raise SystemExit("authority origin joins must keep known global and unknown aliases conservative")
local_address = compact(function_section(authority_text, "ga_local_address_origin"))
for fragment in (
    "returnga_local_origin(local_index,state)ifnotprojected",
    "returnga_local_origin(local_index,state)ifnotga_reference_type(root_type,state,0)",
):
    if fragment not in local_address:
        raise SystemExit("direct borrows of local storage must preserve the encoded local-root identity")
local_origin = compact(function_section(authority_text, "ga_local_origin"))
local_origin_guard = compact("""
return GLOBAL_AUTHORITY_UNKNOWN_ALIAS if:
    identity >= GLOBAL_AUTHORITY_LOCAL_ALIAS or state.globals.count >= GLOBAL_AUTHORITY_LOCAL_ALIAS
    identity >= GLOBAL_AUTHORITY_LOCAL_ALIAS - state.globals.count
""")
if "identity:usize=state.local_origin_ids[local_index]" not in local_origin or \
        local_origin_guard not in local_origin or \
        "returnstate.globals.count+identity" not in local_origin:
    raise SystemExit("encoded local roots must stay below the reserved alias ceiling and fail closed on overflow")
push_local_origin = compact(function_section(authority_text, "ga_push_local_origin_id"))
if "state.local_origin_ids.push(GLOBAL_AUTHORITY_LOCAL_ALIAS)" not in push_local_origin or \
        "state.next_local_origin_id<GLOBAL_AUTHORITY_LOCAL_ALIAS-state.globals.count" not in push_local_origin:
    raise SystemExit("local-origin allocation must reserve its ceiling for fail-closed overflow")
opaque_origin = compact(function_section(authority_text, "ga_expression_reference_origin"))
if "SemanticGlobalAuthorityOrigin::opaque_expression_origin(true,ga_type_expression_contains_reference(annotation,state,depth+1))" not in opaque_origin or \
        "SemanticGlobalAuthorityOrigin::opaque_expression_origin(false,false)" not in opaque_origin:
    raise SystemExit("opaque expression origins must use the proved fail-closed policy")
if "ga_expression_reference_origin(expression,state,depth+1)" not in origin_walk:
    raise SystemExit("opaque or reference-bearing values must not disappear from aggregate origin summaries")
if "SemanticGlobalAuthorityOrigin::constructor_origin(origin,false)" not in origin_walk or \
        "SemanticGlobalAuthorityOrigin::constructor_origin(origin,true)" not in origin_walk:
    raise SystemExit("struct constructor summaries must pass through the proved field-coverage rule")
constructor_coverage = compact(function_section(authority_text, "ga_construct_omits_reference_field"))
for fragment in (
    "returntrueifowner>=state.struct_names.count",
    "returntrueifstate.field_scopes[field_index]!=state.module_scope",
    'returntrueifinitializer.name==""andnotinitializer.is_copy_base',
    "found<-trueifinitializer.name==state.field_names[field_index]",
    "returntrueifnotfound",
):
    if fragment not in constructor_coverage:
        raise SystemExit("constructor completeness must fail closed on omitted or unresolved reference fields")
collection = compact(function_section(authority_text, "ga_collect"))
for fragment in (
    "Decl.Enum(name: name, variants: variants, _):",
    "state.enum_variant_owners.push(name)",
    "state.enum_variant_payload_starts.push(state.enum_variant_payload_types.count)",
    "state.enum_variant_payload_counts.push(variant.fields.count)",
    "state.enum_variant_payload_types.push(variant.fields[field_index])",
    "state.enum_variant_payload_names.push(variant.field_names[field_index]iffield_index<variant.field_names.countelsesview(\"\",0,0))",
):
    if compact(fragment) not in collection:
        raise SystemExit("enum constructor origin summaries must bind to declared lexical payload layouts")
variant_slot = compact(function_section(authority_text, "ga_enum_variant_slot"))
if "ga_resolve_indexed(ga_type_head(owner_expression),ga_type_scope(owner_expression,state),ga_type_qualified(owner_expression),state.enum_names,state.enum_scopes,state.enum_heads,state.enum_next,state)" not in variant_slot or \
        "state.enum_variant_owners[variant_slot]==state.enum_names[enum_slot]" not in variant_slot or \
        "state.enum_variant_scopes[variant_slot]==state.enum_scopes[enum_slot]" not in variant_slot or \
        "state.enum_variant_names[variant_slot]==variant_name" not in variant_slot or \
        "ga_local_slot(owner_name,state)<state.locals.count" not in variant_slot:
    raise SystemExit("enum constructor recognition must require its resolved owner and exact variant")
variant_origin = compact(function_section(authority_text, "ga_enum_constructor_origin"))
for fragment in (
    "arguments.count!=state.enum_variant_payload_counts[variant_slot]",
    "SemanticGlobalAuthorityOrigin::constructor_origin(GLOBAL_AUTHORITY_NONE,false)",
    "payload_count>state.enum_variant_payload_names.count-payload_start",
    "forargument_indexin0..<arguments.count:",
    "forpayload_indexinpayload_start..<payload_start+payload_count:",
    "found<-trueifstate.enum_variant_payload_names[payload_index]==label",
    "returnSemanticGlobalAuthorityOrigin::constructor_origin(GLOBAL_AUTHORITY_NONE,false)ifnotfound",
    "ga_reference_origin(argument,state,depth+1)",
    "ga_join_origins(state,origin,argument_origin)",
    "SemanticGlobalAuthorityOrigin::constructor_origin(origin,true)",
):
    if fragment not in variant_origin:
        raise SystemExit("enum payload origin summaries must join the exact constructor arguments and fail closed")
if "Expr.Call(callee,arguments,labels,_):variant_slot:usize=ga_enum_variant_slot(callee,state)" not in origin_walk or \
        "ga_enum_constructor_origin(variant_slot,arguments,labels,state,depth+1)" not in origin_walk:
    raise SystemExit("only resolved enum constructors may expose their payload origins")
type_expression_classifier = compact(function_section(authority_types_text, "ga_type_expression_contains_reference"))
if "returntrueifga_reference_type(resolved,state,depth+1)" not in type_expression_classifier or \
        "owner:usize=ga_known_struct(resolved,state.module_scope,state,depth+1)" not in type_expression_classifier or \
        "returntrueif:state.field_scopes[index]!=state.module_scopega_type_expression_contains_reference(state.field_types[index],state,depth+1)" not in type_expression_classifier or \
        "ga_type_expression_contains_reference(state.enum_variant_payload_types[payload_index],state,depth+1)" not in type_expression_classifier:
    raise SystemExit("reference classification must recurse through named aggregate and enum payload fields")
contains_refs = compact(function_section(authority_text, "ga_type_id_contains_reference"))
if "kind!=SemTypeKind.Optionalandkind!=SemTypeKind.Tupleandkind!=SemTypeKind.Container" not in contains_refs or \
        "ga_type_id_contains_reference(interned_elem(type_id,element_index,table),table,depth+1)" not in contains_refs:
    raise SystemExit("binder reference detection must recurse through tuples and container element types")
tuple_annotation = compact(function_section(authority_types_text, "ga_tuple_field_type"))
if 'annotation.owner=="__tuple_label"andannotation.name==field' not in tuple_annotation:
    raise SystemExit("named-tuple field annotations must be available to the global-authority type walk")
smoke_text = SMOKE.read_text()
required_regressions = (
    "local reference items stay local through tuple iteration",
    "local reference items stay local through tuple comprehension",
    "local reference payloads stay local through tuple matching",
    "named tuple reference binder follows a loaded reference freely",
    "named tuple reference binder accepts both grants",
    "local nominal reference items stay local through iteration",
    "nominal reference binder follows a loaded reference freely",
    "nominal reference binder accepts both grants",
    "local nominal reference binder stays local through match",
    "nominal match reference binder follows a loaded reference freely",
    "nominal match reference binder accepts both grants",
    "nominal reference origin does not taint scalar siblings",
    "omitted default reference field is followed freely",
    "local enum constructor payload keeps local origin",
    "external enum payload binder follows a loaded reference freely",
    "external enum payload binder accepts both grants",
    "mixed enum payload charges the global alias where it is created",
)
if any(smoke_text.count(f'("{name}",') != 1 for name in required_regressions):
    raise SystemExit("global-authority smoke suite lost a local-origin or named-tuple alias regression")
if "darray[(pointer: mutable i64&, step: usize)]&" not in smoke_text or \
        "set_one(item.pointer)" not in smoke_text:
    raise SystemExit("named-tuple loop regression no longer exercises a reference-bearing field access")
if "darray[GrantOriginHolder]&" not in smoke_text or \
        "GrantOriginHolder{pointer: &seed, step: 0.usize()}" not in smoke_text:
    raise SystemExit("nominal loop regressions must cover both local and external nested-reference origins")
if "pointer: mutable i64& = &hot" not in smoke_text or \
        "GrantOriginDefaultHolder{local: &seed}" not in smoke_text:
    raise SystemExit("constructor regression must cover an omitted reference-bearing default field")
if "GrantOriginMatchHolder{pointer: pointer}" not in smoke_text or \
        "return holder.step" not in smoke_text:
    raise SystemExit("nominal match regressions must preserve payload origins without tainting scalar siblings")
if "GrantOriginCarrier.Wrap(pointer: &seed)" not in smoke_text or \
        "GrantOriginPair.Wrap(left: &seed, right: &hot)" not in smoke_text:
    raise SystemExit("enum constructor regressions must cover named arguments and mixed local/global payload roots")
unknown_access_body = compact(function_section(authority_text, "ga_access_unknown_alias"))
unknown_access_fragments = (
    "required:sview=SemanticGlobalAuthorityOrigin::unknown_alias_permission(write)",
    "returnifga_refs_cover_at(state.firewalls,state.firewall_scopes,state.firewall_offsets,required,0,state,at.offset)",
    "ifnotstate.report:_=ga_row_add(state.function,required,true,state,GLOBAL_AUTHORITY_NONE,0,at.offset)canGlobal{Read,Write}",
    "ifwrite:state.writes[state.function]<-trueelse:state.reads[state.function]<-true",
    "elifnotga_granted(required,at,state):table.diagnostics<-table.diagnostics.push(Diagnostic{kind:DiagnosticKind.MutableGlobalPermissionUngranted",
)
if any(fragment not in unknown_access_body for fragment in unknown_access_fragments):
    raise SystemExit("unknown reference aliases no longer require the corresponding Global permission")

positive_names = {
    "pattern_binding_origin_matches_its_exact_spec",
    "values_without_references_have_no_origin",
    "known_global_origins_survive_binding_and_projection",
    "known_local_origins_survive_binding_and_projection",
    "unknown_reference_origins_fail_closed",
    "reference_origin_join_matches_its_exact_spec",
    "no_origin_is_a_left_join_identity",
    "no_origin_is_a_right_join_identity",
    "matching_local_origins_join_to_local",
    "conflicting_local_and_global_origins_join_to_unknown",
    "reference_origin_join_is_commutative",
    "reference_origin_join_is_associative",
    "reference_origin_join_is_idempotent",
    "unknown_origin_absorbs_every_joined_origin",
    "opaque_expression_origin_matches_its_exact_spec",
    "opaque_expression_without_type_fails_closed",
    "opaque_reference_bearing_expression_fails_closed",
    "known_reference_free_opaque_expression_has_no_origin",
    "constructor_origin_matches_reference_field_coverage",
    "incomplete_constructor_reference_fields_fail_closed",
    "complete_constructor_reference_fields_keep_summary",
    "unknown_alias_permission_matches_its_exact_spec",
    "writing_through_an_unknown_alias_requires_global_write",
    "reading_through_an_unknown_alias_requires_global_read",
    "conservative_alias_policy_matches_its_exact_spec",
    "missing_origin_requires_conservative_access",
    "unknown_origin_requires_conservative_access",
    "detached_storage_skips_conservative_access",
    "encoded_local_origins_bypass_unknown_alias_policy",
}
negative_names = {
    "value_without_references_can_be_an_unknown_alias",
    "unknown_reference_can_be_treated_as_origin_free",
    "known_local_reference_can_be_reclassified_as_unknown",
    "conflicting_local_and_global_origins_can_be_called_local",
    "distinct_global_origins_can_keep_the_first_root",
    "unknown_and_local_origins_can_join_to_local",
    "unknown_origin_can_be_erased_by_an_arbitrary_joined_origin",
    "opaque_expression_without_type_can_have_no_origin",
    "opaque_reference_bearing_expression_can_have_no_origin",
    "known_reference_free_expression_must_be_unknown",
    "incomplete_constructor_can_keep_a_known_local_summary",
    "complete_constructor_must_be_unknown",
    "unknown_alias_write_can_require_only_global_read",
    "unknown_alias_read_can_require_global_write",
    "unknown_alias_can_skip_conservative_access",
    "missing_origin_can_skip_conservative_access",
    "detached_storage_can_require_conservative_access",
    "encoded_local_origin_can_require_unknown_alias_access",
}
if declarations(positive_text) != positive_names or declarations(negative_text) != negative_names:
    raise SystemExit("global-authority origin proof declaration inventory changed")
if 'include "../../src/semantic/global_authority_origin_policy.elisa"' not in positive_text:
    raise SystemExit("positive proof no longer imports the production origin policy")
if 'include "./global_authority_origin_policy.elisa"' not in negative_text:
    raise SystemExit("false controls no longer inherit the production-linked positive proof")

positive_claims = {
    "pattern_binding_origin_matches_its_exact_spec": "SemanticGlobalAuthorityOrigin::pattern_binding_origin(contains_reference, source_origin) == (SemanticGlobalAuthorityOrigin::NO_ORIGIN if not contains_reference else (source_origin if source_origin != SemanticGlobalAuthorityOrigin::NO_ORIGIN else SemanticGlobalAuthorityOrigin::UNKNOWN_ALIAS))",
    "values_without_references_have_no_origin": "SemanticGlobalAuthorityOrigin::pattern_binding_origin(false, 17.usize()) == SemanticGlobalAuthorityOrigin::NO_ORIGIN",
    "known_global_origins_survive_binding_and_projection": "SemanticGlobalAuthorityOrigin::pattern_binding_origin(true, 17.usize()) == 17.usize()",
    "known_local_origins_survive_binding_and_projection": "SemanticGlobalAuthorityOrigin::pattern_binding_origin(true, SemanticGlobalAuthorityOrigin::LOCAL_ALIAS) == SemanticGlobalAuthorityOrigin::LOCAL_ALIAS",
    "unknown_reference_origins_fail_closed": "SemanticGlobalAuthorityOrigin::pattern_binding_origin(true, SemanticGlobalAuthorityOrigin::NO_ORIGIN) == SemanticGlobalAuthorityOrigin::UNKNOWN_ALIAS",
    "reference_origin_join_matches_its_exact_spec": "SemanticGlobalAuthorityOrigin::join_reference_origins(left, right) == (right if left == SemanticGlobalAuthorityOrigin::NO_ORIGIN else (left if right == SemanticGlobalAuthorityOrigin::NO_ORIGIN else (left if left == right else SemanticGlobalAuthorityOrigin::UNKNOWN_ALIAS)))",
    "no_origin_is_a_left_join_identity": "SemanticGlobalAuthorityOrigin::join_reference_origins(SemanticGlobalAuthorityOrigin::NO_ORIGIN, 17.usize()) == 17.usize()",
    "no_origin_is_a_right_join_identity": "SemanticGlobalAuthorityOrigin::join_reference_origins(17.usize(), SemanticGlobalAuthorityOrigin::NO_ORIGIN) == 17.usize()",
    "matching_local_origins_join_to_local": "SemanticGlobalAuthorityOrigin::join_reference_origins(SemanticGlobalAuthorityOrigin::LOCAL_ALIAS, SemanticGlobalAuthorityOrigin::LOCAL_ALIAS) == SemanticGlobalAuthorityOrigin::LOCAL_ALIAS",
    "conflicting_local_and_global_origins_join_to_unknown": "SemanticGlobalAuthorityOrigin::join_reference_origins(SemanticGlobalAuthorityOrigin::LOCAL_ALIAS, 17.usize()) == SemanticGlobalAuthorityOrigin::UNKNOWN_ALIAS",
    "reference_origin_join_is_commutative": "SemanticGlobalAuthorityOrigin::join_reference_origins(left, right) == SemanticGlobalAuthorityOrigin::join_reference_origins(right, left)",
    "reference_origin_join_is_associative": "SemanticGlobalAuthorityOrigin::join_reference_origins(SemanticGlobalAuthorityOrigin::join_reference_origins(first, second), third) == SemanticGlobalAuthorityOrigin::join_reference_origins(first, SemanticGlobalAuthorityOrigin::join_reference_origins(second, third))",
    "reference_origin_join_is_idempotent": "SemanticGlobalAuthorityOrigin::join_reference_origins(origin, origin) == origin",
    "unknown_origin_absorbs_every_joined_origin": "(SemanticGlobalAuthorityOrigin::join_reference_origins(SemanticGlobalAuthorityOrigin::UNKNOWN_ALIAS, origin) == SemanticGlobalAuthorityOrigin::UNKNOWN_ALIAS and SemanticGlobalAuthorityOrigin::join_reference_origins(origin, SemanticGlobalAuthorityOrigin::UNKNOWN_ALIAS) == SemanticGlobalAuthorityOrigin::UNKNOWN_ALIAS)",
    "opaque_expression_origin_matches_its_exact_spec": "SemanticGlobalAuthorityOrigin::opaque_expression_origin(type_known, contains_reference) == (SemanticGlobalAuthorityOrigin::UNKNOWN_ALIAS if not type_known or contains_reference else SemanticGlobalAuthorityOrigin::NO_ORIGIN)",
    "opaque_expression_without_type_fails_closed": "SemanticGlobalAuthorityOrigin::opaque_expression_origin(false, false) == SemanticGlobalAuthorityOrigin::UNKNOWN_ALIAS",
    "opaque_reference_bearing_expression_fails_closed": "SemanticGlobalAuthorityOrigin::opaque_expression_origin(true, true) == SemanticGlobalAuthorityOrigin::UNKNOWN_ALIAS",
    "known_reference_free_opaque_expression_has_no_origin": "SemanticGlobalAuthorityOrigin::opaque_expression_origin(true, false) == SemanticGlobalAuthorityOrigin::NO_ORIGIN",
    "constructor_origin_matches_reference_field_coverage": "SemanticGlobalAuthorityOrigin::constructor_origin(summary, reference_fields_complete) == (summary if reference_fields_complete else SemanticGlobalAuthorityOrigin::UNKNOWN_ALIAS)",
    "incomplete_constructor_reference_fields_fail_closed": "SemanticGlobalAuthorityOrigin::constructor_origin(SemanticGlobalAuthorityOrigin::LOCAL_ALIAS, false) == SemanticGlobalAuthorityOrigin::UNKNOWN_ALIAS",
    "complete_constructor_reference_fields_keep_summary": "SemanticGlobalAuthorityOrigin::constructor_origin(SemanticGlobalAuthorityOrigin::LOCAL_ALIAS, true) == SemanticGlobalAuthorityOrigin::LOCAL_ALIAS",
    "unknown_alias_permission_matches_its_exact_spec": "SemanticGlobalAuthorityOrigin::unknown_alias_permission(write) == (\"Global.Write\" if write else \"Global.Read\")",
    "writing_through_an_unknown_alias_requires_global_write": 'SemanticGlobalAuthorityOrigin::unknown_alias_permission(true) == "Global.Write"',
    "reading_through_an_unknown_alias_requires_global_read": 'SemanticGlobalAuthorityOrigin::unknown_alias_permission(false) == "Global.Read"',
    "conservative_alias_policy_matches_its_exact_spec": "SemanticGlobalAuthorityOrigin::requires_unknown_alias_permission(origin) == (origin == SemanticGlobalAuthorityOrigin::NO_ORIGIN or origin == SemanticGlobalAuthorityOrigin::UNKNOWN_ALIAS)",
    "missing_origin_requires_conservative_access": "SemanticGlobalAuthorityOrigin::requires_unknown_alias_permission(SemanticGlobalAuthorityOrigin::NO_ORIGIN)",
    "unknown_origin_requires_conservative_access": "SemanticGlobalAuthorityOrigin::requires_unknown_alias_permission(SemanticGlobalAuthorityOrigin::UNKNOWN_ALIAS)",
    "detached_storage_skips_conservative_access": "not SemanticGlobalAuthorityOrigin::requires_unknown_alias_permission(SemanticGlobalAuthorityOrigin::LOCAL_ALIAS)",
    "encoded_local_origins_bypass_unknown_alias_policy": "not SemanticGlobalAuthorityOrigin::requires_unknown_alias_permission(global_count + identity)",
}
negative_claims = {
    "value_without_references_can_be_an_unknown_alias": "SemanticGlobalAuthorityOrigin::pattern_binding_origin(false, 17.usize()) == SemanticGlobalAuthorityOrigin::UNKNOWN_ALIAS",
    "unknown_reference_can_be_treated_as_origin_free": "SemanticGlobalAuthorityOrigin::pattern_binding_origin(true, SemanticGlobalAuthorityOrigin::NO_ORIGIN) == SemanticGlobalAuthorityOrigin::NO_ORIGIN",
    "known_local_reference_can_be_reclassified_as_unknown": "SemanticGlobalAuthorityOrigin::pattern_binding_origin(true, SemanticGlobalAuthorityOrigin::LOCAL_ALIAS) == SemanticGlobalAuthorityOrigin::UNKNOWN_ALIAS",
    "conflicting_local_and_global_origins_can_be_called_local": "SemanticGlobalAuthorityOrigin::join_reference_origins(SemanticGlobalAuthorityOrigin::LOCAL_ALIAS, 17.usize()) == SemanticGlobalAuthorityOrigin::LOCAL_ALIAS",
    "distinct_global_origins_can_keep_the_first_root": "SemanticGlobalAuthorityOrigin::join_reference_origins(17.usize(), 19.usize()) == 17.usize()",
    "unknown_and_local_origins_can_join_to_local": "SemanticGlobalAuthorityOrigin::join_reference_origins(SemanticGlobalAuthorityOrigin::UNKNOWN_ALIAS, SemanticGlobalAuthorityOrigin::LOCAL_ALIAS) == SemanticGlobalAuthorityOrigin::LOCAL_ALIAS",
    "unknown_origin_can_be_erased_by_an_arbitrary_joined_origin": "SemanticGlobalAuthorityOrigin::join_reference_origins(SemanticGlobalAuthorityOrigin::UNKNOWN_ALIAS, origin) == origin",
    "opaque_expression_without_type_can_have_no_origin": "SemanticGlobalAuthorityOrigin::opaque_expression_origin(false, false) == SemanticGlobalAuthorityOrigin::NO_ORIGIN",
    "opaque_reference_bearing_expression_can_have_no_origin": "SemanticGlobalAuthorityOrigin::opaque_expression_origin(true, true) == SemanticGlobalAuthorityOrigin::NO_ORIGIN",
    "known_reference_free_expression_must_be_unknown": "SemanticGlobalAuthorityOrigin::opaque_expression_origin(true, false) == SemanticGlobalAuthorityOrigin::UNKNOWN_ALIAS",
    "incomplete_constructor_can_keep_a_known_local_summary": "SemanticGlobalAuthorityOrigin::constructor_origin(SemanticGlobalAuthorityOrigin::LOCAL_ALIAS, false) == SemanticGlobalAuthorityOrigin::LOCAL_ALIAS",
    "complete_constructor_must_be_unknown": "SemanticGlobalAuthorityOrigin::constructor_origin(SemanticGlobalAuthorityOrigin::LOCAL_ALIAS, true) == SemanticGlobalAuthorityOrigin::UNKNOWN_ALIAS",
    "unknown_alias_write_can_require_only_global_read": 'SemanticGlobalAuthorityOrigin::unknown_alias_permission(true) == "Global.Read"',
    "unknown_alias_read_can_require_global_write": 'SemanticGlobalAuthorityOrigin::unknown_alias_permission(false) == "Global.Write"',
    "unknown_alias_can_skip_conservative_access": "not SemanticGlobalAuthorityOrigin::requires_unknown_alias_permission(SemanticGlobalAuthorityOrigin::UNKNOWN_ALIAS)",
    "missing_origin_can_skip_conservative_access": "not SemanticGlobalAuthorityOrigin::requires_unknown_alias_permission(SemanticGlobalAuthorityOrigin::NO_ORIGIN)",
    "detached_storage_can_require_conservative_access": "SemanticGlobalAuthorityOrigin::requires_unknown_alias_permission(SemanticGlobalAuthorityOrigin::LOCAL_ALIAS)",
    "encoded_local_origin_can_require_unknown_alias_access": "SemanticGlobalAuthorityOrigin::requires_unknown_alias_permission(global_count + identity)",
}
for source_text, claims, label in (
    (positive_text, positive_claims, "positive"),
    (negative_text, negative_claims, "negative"),
):
    for name, claim in claims.items():
        section = compact(function_section(source_text, name))
        if "ensureresult==true" not in section or f"return{compact(claim)}" not in section:
            raise SystemExit(f"{label} origin theorem changed its exact claim: {name}")

source_closure = source_include_closure([POSITIVE, NEGATIVE])
if ARGS.source_only:
    print(json.dumps({
        "source_bound": True,
        "positive_declarations": len(positive_names),
        "false_control_declarations": len(negative_names),
        "source_closure_files": len(source_closure),
    }, sort_keys=True))
    raise SystemExit(0)

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("global-authority origin proof requires a strict proof build")

stage1 = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1) + ".provenance.json").resolve(strict=True)
inputs = [
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"), PROVER / "ELISA_COMPILER_REV",
    stage1, stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
    POLICY, SEMANTIC, *AUTHORITY_SOURCES, *AUTHORITY_TYPE_SOURCES, FN_VALUE_SIGNATURES, IMPL_CONFORMANCE, SMOKE, ALIAS_FIXTURE, ALIAS_CONFLICT_FIXTURE, STATIC_BRANCH_ALIAS_FIXTURE, ACTIVE_STATIC_ALIAS_FIXTURE, ALIAS_SMOKE,
    ROOT / "test/atoms/authority_coverage.elisa", POSITIVE, NEGATIVE, *source_closure,
]
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=120)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == positive_names

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert not negative_names & {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert require_current_product(BIN, PROVER) == manifest
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
print(json.dumps({
    "admitted": True,
    "scope": "whole-value reference binders retain known global roots; other references fail closed as unknown aliases",
    "positive_theorems": sorted(positive_names),
    "false_claims_rejected": sorted(negative_names),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
}, sort_keys=True))
