"""Bind global-authority binder-origin and permission policies to the semantic pass."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from parity_smoke_source import read_parity_smoke_source, parity_smoke_inputs
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure
from global_authority_source_checks import check_global_authority_source


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
GLOBAL_AUTHORITY_SMOKE = ROOT / "test/parity/mutable_global_authority_smoke.sh"
ALIAS_FIXTURE = ROOT / "test/fixtures/effects/qualified_permission_using_alias.elisa"
ALIAS_LATE_CONFLICT_FIXTURE = ROOT / "test/fixtures/effects/qualified_permission_late_alias_conflict.neg.elisa"
NESTED_ALIAS_SCOPE_FIXTURE = ROOT / "test/fixtures/effects/global_authority_nested_alias_scope.elisa"
STATIC_BRANCH_ALIAS_FIXTURE = ROOT / "test/fixtures/effects/global_authority_static_branch_alias_conflict.elisa"
ACTIVE_STATIC_ALIAS_FIXTURE = ROOT / "test/fixtures/effects/global_authority_active_static_alias.elisa"
SAME_TARGET_ALIAS_FIXTURE = ROOT / "test/fixtures/effects/global_authority_same_target_aliases.elisa"
ALIAS_CONFLICT_CHECKER = ROOT / "src/semantic/check_import_conflict.elisa"
ALIAS_CONFLICT_DIAGNOSTICS = ROOT / "src/semantic/diagnostic_messages/proofs.elisa"
DIAGNOSTIC_KINDS = ROOT / "src/semantic/semantic_types_diagnostic_kind.elisa"
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
parser_decl_module = (ROOT / "src/parser/parser_decl_module.elisa").read_text() + (ROOT / "src/parser/parser_decl_imports.elisa").read_text()
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
if 'ga_static_branch_marker_exists("__using_alias_static_branch",alias.owner,alias.module,alias.line,alias.offset,state)' not in alias_static_branch or \
        "parser.static_if_branch_rows.count.u32()!=parser.static_if_depth" not in static_branch_marker_parser or \
        "forbranch_identityinparser.static_if_branch_rows" not in static_branch_marker_parser or \
        'owner:"__static_if_branch"' not in static_branch_marker_parser or \
        "identity_id:branch_identity" not in static_branch_marker_parser or \
        "identity_id:4294967295" not in static_branch_marker_parser or \
        'parser.record_static_if_branch_markers(marker_name,detail_name,token.line,token.start)' not in alias_static_branch_parser or \
        'parser.record_static_if_branch_rows("__using_alias_static_branch",alias_name,alias_token)' not in using_alias_parser or \
        'parser.record_static_if_branch_rows("__from_member_static_branch",member,token)' not in import_member_parser or \
        'parser.record_static_if_branch_rows("__binding_wildcard_import_static_branch",full_text,target_token)' not in wildcard_import_parser or \
        'parser.record_static_if_branch_markers("__private_member_static_branch",member_name,section_line,member_position.offset)' not in private_member_parser or \
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
explicit_target_fold = compact(function_section((ROOT / "src/semantic/static_target_predicates.elisa").read_text(), "semantic_explicit_target_constant"))
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
        "returnsemantic_explicit_target_constant(name,target_text)ifsemantic_target_has_text(target_text)")) or \
        "return(false,0)" not in explicit_target_fold or \
        'name=="ELISA_TARGET_OS_LINUX"' not in static_target_predicate or \
        "return(false,0,true)ifga_static_if_target_predicate(name)" not in static_condition_fold:
    raise SystemExit("explicit target predicates must use the shared target resolver and retain an unknown fallback")
if not all(fragment in static_row_selection for fragment in (
        "static_if_depths[row]!=branch_depth",
        "branch_kind==StaticIfBranch::Kind.Fallback",
        "row>=state.static_if_modules.count",
        "condition_module:sview=state.static_if_modules[row]",
        "ga_static_if_condition_value(state.static_if_conds[row],condition_module,state,depth+1)",
        "condition.backend_folds",
        "return(false,false)ifcondition.backend_folds",
        "return(true,row==branch_row)",
        "return(true,false)ifrow==branch_row")) or not all(fragment in alias_branch_selection for fragment in (
        'ga_static_branch_marker_selection("__using_alias_static_branch",alias.owner,alias.module,alias.line,alias.offset,alias.module,state)',
        "return(true,false)ifmarkers.inactive",
        "return(true,true)ifnotmarkers.found",
        "return(false,false)ifmarkers.unknown")):
    raise SystemExit("GlobalAuthority must follow known static-if selection and fail closed on unknown branch ancestry")
import_branch_selection = compact(function_section(authority_text, "ga_import_annotation_branch_selection"))
import_index = compact(function_section((ROOT / "src/semantic/check_global_authority/annotation_index.elisa").read_text(), "ga_index_import_annotations"))
if not all(fragment in import_branch_selection for fragment in (
        'marker_name:sview="__from_member_static_branch"ifimport_row.owner=="__from_member"else"__binding_wildcard_import_static_branch"',
        "ga_static_branch_marker_selection(marker_name,marker_detail,import_row.module,import_row.line,import_row.offset,import_row.module,state)",
        "return(true,false)ifmarkers.inactive",
        "return(false,false)ifmarkers.unknown")) or \
        "ga_import_annotation_branch_selection(annotation,state)" not in import_index or \
        "ifnotbranch.known:state.static_import_uncertain<-true" not in import_index or \
        "continueifnotbranch.active" not in import_index:
    raise SystemExit("GlobalAuthority import indexing must exclude inactive imports and preserve uncertainty for possible imports")
for relative_path, state_name in (
        ("src/semantic/check_global_authority/incremental.elisa", "state"),
        ("src/semantic/check_fn_value_effect_row_signatures.elisa", "context"),
        ("src/semantic/check_global_permissions/axis_projection.elisa", "authority"),
        ("src/semantic/check_strict_unsafe_ops_views.elisa", "authority")):
    if f"ga_index_import_annotations(&{state_name})" not in (ROOT / relative_path).read_text():
        raise SystemExit(f"production GlobalAuthority constructor bypasses shared alias-index preparation: {relative_path}")
import_uncertainty = compact((ROOT / "src/semantic/check_global_authority/incremental.elisa").read_text())
if "ga_mark_all_possible_global_effects(&state)ifstate.static_import_uncertain" not in import_uncertainty:
    raise SystemExit("uncertain static imports must conservatively retain possible global effects")
if "static_if_modules:file.static_if_modules" not in import_uncertainty:
    raise SystemExit("GlobalAuthority must receive per-row lexical modules for static-if folding")
if not all(fragment in import_uncertainty for fragment in (
        "forconst_indexin0..<table.immutable_const_names.count",
        "state.static_const_names.push(table.immutable_const_names[const_index])",
        "state.static_const_values.push(table.immutable_const_values[const_index]ifconst_index<table.immutable_const_values.countelseAst::Expr.Absent)",
        "state.static_const_owners.push(table.symbols[const_row].module_ownerifconst_row<table.symbols.countelse\"\")",
        "state.static_const_lines.push(table.symbols[const_row].lineifconst_row<table.symbols.countelse0)",
        "state.static_const_offsets.push(table.symbols[const_row].offsetifconst_row<table.symbols.countelse4294967295)")):
    raise SystemExit("GlobalAuthority must receive source-constant values and lexical owners for static-if folding")
const_branch_selection = compact(function_section(authority_text, "ga_static_if_const_branch_selection"))
named_const_fold = compact(function_section(authority_text, "ga_static_if_named_constant_value"))
if not all(fragment in const_branch_selection for fragment in (
        'ga_static_branch_marker_selection("__const_static_branch",state.static_const_names[const_index],state.static_const_owners[const_index],state.static_const_lines[const_index],state.static_const_offsets[const_index],state.static_const_owners[const_index],state,depth+1)',
        "return(true,false)ifmarkers.inactive",
        "return(false,false)ifmarkers.unknown")) or not all(fragment in named_const_fold for fragment in (
        "ga_static_if_const_branch_selection(index,state,depth+1)",
        "continueifnotbranch.active",
        "exact_unknown",
        "top_unknown",
        "any_unknown")):
    raise SystemExit("GlobalAuthority source-constant folding must select only the active static-branch declaration")
alias_registration_index = compact(function_section(authority_text, "ga_module_alias_registration_index"))
if "state.module_alias_rows.count" not in alias_registration_index or \
        'alias.name=="__using_alias"' not in alias_registration_index or \
        "alias.offset==offset" not in alias_registration_index or \
        "ga_module_text(alias.module,state)==scope" not in alias_registration_index or \
        "foralias_indexin0..<state.annotations.count" not in alias_registration_index:
    raise SystemExit("GlobalAuthority alias-target cutoffs are not bound to the declaration's registration position")
alias_choice_consider = compact(function_section(authority_text, "ga_module_alias_choice_consider"))
if "state.module_alias_rows.count" not in alias_choice or \
        "foralias_indexin0..<state.annotations.count" not in alias_choice:
    raise SystemExit("GlobalAuthority alias selection must use the prepared source-ordered alias rows with a safe fallback")
if "source_positioned:bool=before_offset!=GLOBAL_AUTHORITY_OFFSET_NONE" not in alias_choice or \
        "ga_module_alias_registration_precedes(alias_scope,alias.offset,alias_index,selected_scope,selected_alias.offset,selected_index,state)" not in alias_choice_consider or \
        "ga_module_alias_registration_precedes(selected_scope,selected_alias.offset,selected_index,alias_scope,alias.offset,alias_index,state)" not in alias_choice_consider or \
        "ga_module_alias_registration_precedes(alias_scope,alias.offset,alias_index,lexical_scope,before_alias.offset,before_index,state)" not in alias_choice_consider or \
        "before_index:usize=ga_module_alias_registration_index(lexical_scope,before_offset,state)" not in alias_choice:
    raise SystemExit("GlobalAuthority alias lookup must keep first registration without a cutoff and the latest eligible registration with one")
parts_resolve = compact(function_section(authority_text, "ga_module_parts_resolve"))
parts_lexical = parts_resolve.find("ga_module_lexical_parts_path(parts,lexical_scope,state)")
parts_alias = parts_resolve.find("ga_module_alias_choice(parts[0],lexical_scope,state,depth,before_offset)")
parts_root = parts_resolve.find("raw_root:usize=ga_child(state,0,parts[0])")
if min(parts_lexical, parts_alias, parts_root) < 0 or not parts_lexical < parts_alias < parts_root:
    raise SystemExit("GlobalAuthority expression/store paths must try complete lexical candidates, aliases, then root spelling")
alias_resolve = compact(function_section(authority_text, "ga_module_alias_resolve"))
if "before_offset:u32=GLOBAL_AUTHORITY_OFFSET_NONE" not in alias_resolve or \
        "ga_module_alias_choice(first,lexical_scope,state,depth,before_offset)" not in alias_resolve or \
        "ga_module_alias_target_resolve(target.path,alias.scope,state,depth+1,alias_row.offset)" not in alias_resolve:
    raise SystemExit("qualified GlobalAuthority module resolution does not use registered aliases and declaration offsets for target recursion")
alias_lexical = alias_resolve.find("ga_module_lexical_path(path,first,start,lexical_scope,state)")
alias_choice_position = alias_resolve.find("ga_module_alias_choice(first,lexical_scope,state,depth,before_offset)")
alias_suffix = alias_resolve.find("alias_path:usize=ga_module_path_suffix(path,start,resolved,state)")
alias_root = alias_resolve.find("raw_root:usize=ga_child(state,0,first)")
if min(alias_lexical, alias_choice_position, alias_suffix, alias_root) < 0 or not alias_lexical < alias_choice_position < alias_suffix < alias_root:
    raise SystemExit("GlobalAuthority text paths must try complete lexical candidates, alias suffixes, then root spelling")
alias_target = compact(function_section(authority_text, "ga_module_alias_target_resolve"))
exact_target_path = alias_target.find("exact_path:usize=ga_module_path_exact(path,declaration_scope,state)")
alias_target_choice = alias_target.find("ga_module_alias_choice(first,declaration_scope,state,depth,before_offset)")
if exact_target_path < 0 or alias_target_choice < 0 or exact_target_path >= alias_target_choice:
    raise SystemExit("GlobalAuthority alias targets must prefer a complete concrete path in their declaration module")
if "ga_module_alias_choice(first,declaration_scope,state,depth,before_offset)" not in alias_target or \
        "ga_module_alias_target_resolve(target.path,alias.scope,state,depth+1,alias_row.offset)" not in alias_target:
    raise SystemExit("GlobalAuthority alias-target recursion drops its source registration cutoff")
if not all(fragment in alias_choice_consider for fragment in (
        "branch_selection:(known:bool,active:bool)=ga_module_alias_branch_selection(alias_index,state)",
        "returnifbranch_selection.knownandnotbranch_selection.active",
        "ifnotbranch_selection.known:",
        "uncertain_index<-alias_index")) or "return(true,true,uncertain_index,uncertain_scope)" not in alias_choice:
    raise SystemExit("alias choice must skip proven-inactive branches and preserve unknown branch precedence conservatively")
marker_selection = compact(function_section(authority_text, "ga_static_branch_marker_selection"))
marker_exists = compact(function_section(authority_text, "ga_static_branch_marker_exists"))
annotation_index_text = (ROOT / "src/semantic/check_global_authority/annotation_index.elisa").read_text()
alias_index_builder = compact(function_section(annotation_index_text, "ga_index_module_alias_annotations"))
import_index_builder = compact(function_section(annotation_index_text, "ga_index_import_annotations"))
if not all(fragment in alias_index_builder for fragment in (
        "state.module_alias_rows.clear()",
        "state.static_branch_marker_rows.clear()",
        'annotation.name=="__using_alias"',
        "state.module_alias_rows.push(annotation_index)",
        'annotation.owner=="__static_if_branch"',
        'annotation.name=="__using_alias_static_branch"',
        'annotation.name=="__from_member_static_branch"',
        'annotation.name=="__binding_wildcard_import_static_branch"',
        'annotation.name=="__const_static_branch"',
        "state.static_branch_marker_rows.push(annotation_index)",
        "state.module_alias_index_annotation_count<-state.annotations.count",
        "state.module_alias_index_ready<-true")) or \
        "ga_index_module_alias_annotations(state)" not in import_index_builder or \
        import_index_builder.find("ga_index_module_alias_annotations(state)") >= import_index_builder.find("forannotationinstate.annotations") or \
        not all(fragment in marker_selection for fragment in (
            "state.static_branch_marker_rows.count",
            "ga_static_branch_marker_consider(marker_index,marker_name,detail_name,module,line,offset,current_module,state,selection_depth,found_marker,unknown)",
            "formarker_indexin0..<state.annotations.count")) or \
        "state.static_branch_marker_rows.count" not in marker_exists or \
        "formarkerinstate.annotations" not in marker_exists:
    raise SystemExit("GlobalAuthority alias and static-branch lookups must use source-ordered row views with exact checks and a fallback")
text_module = compact(function_section(authority_text, "ga_text_module"))
if "ga_module_alias_resolve(path,lexical_scope,state,0,true,before_offset)" not in text_module:
    raise SystemExit("GlobalAuthority text module lookup drops its source offset")
global_authority_smoke = read_parity_smoke_source(GLOBAL_AUTHORITY_SMOKE)
if 'run_case alias_target_concrete_before_alias ' not in global_authority_smoke or \
        "using Other as A" not in global_authority_smoke or \
        "using A::Foo as F" not in global_authority_smoke or \
        "return F::Bar::hot" not in global_authority_smoke:
    raise SystemExit("GlobalAuthority alias-target precedence regression must exercise a concrete path shadowed by an alias")
check_global_authority_source(
    ACTIVE_STATIC_ALIAS_FIXTURE=ACTIVE_STATIC_ALIAS_FIXTURE,
    ALIAS_CONFLICT_CHECKER=ALIAS_CONFLICT_CHECKER,
    ALIAS_CONFLICT_DIAGNOSTICS=ALIAS_CONFLICT_DIAGNOSTICS,
    NESTED_ALIAS_SCOPE_FIXTURE=NESTED_ALIAS_SCOPE_FIXTURE,
    ALIAS_FIXTURE=ALIAS_FIXTURE,
    ALIAS_LATE_CONFLICT_FIXTURE=ALIAS_LATE_CONFLICT_FIXTURE,
    ALIAS_SMOKE=ALIAS_SMOKE,
    FN_VALUE_SIGNATURES=FN_VALUE_SIGNATURES,
    IMPL_CONFORMANCE=IMPL_CONFORMANCE,
    ROOT=ROOT,
    SAME_TARGET_ALIAS_FIXTURE=SAME_TARGET_ALIAS_FIXTURE,
    STATIC_BRANCH_ALIAS_FIXTURE=STATIC_BRANCH_ALIAS_FIXTURE,
    authority_text=authority_text,
    authority_types_text=authority_types_text,
    compact=compact,
    function_section=function_section,
    policy_text=policy_text,
    semantic_text=semantic_text,
)
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
    HERE / "global_authority_source_checks.py", HERE / "parity_smoke_source.py", *parity_smoke_inputs(GLOBAL_AUTHORITY_SMOKE),
    POLICY, SEMANTIC, *AUTHORITY_SOURCES, *AUTHORITY_TYPE_SOURCES, FN_VALUE_SIGNATURES, IMPL_CONFORMANCE, SMOKE, ALIAS_FIXTURE, ALIAS_LATE_CONFLICT_FIXTURE, NESTED_ALIAS_SCOPE_FIXTURE, STATIC_BRANCH_ALIAS_FIXTURE, ACTIVE_STATIC_ALIAS_FIXTURE, SAME_TARGET_ALIAS_FIXTURE, ALIAS_SMOKE,
    ALIAS_CONFLICT_CHECKER, ALIAS_CONFLICT_DIAGNOSTICS, DIAGNOSTIC_KINDS,
    *source_include_closure([DIAGNOSTIC_KINDS]),
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
