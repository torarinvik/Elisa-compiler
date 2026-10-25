"""Bind qualified-module matching proofs to the semantic lookup implementation."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


from source_guard_compat import expand_return_if_blocks
ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve()
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
POLICY = ROOT / "src/semantic/module_symbol_path_matcher.elisa"
CONSUMER = ROOT / "src/semantic/check_type_path_separator.elisa"
IMPORT_VISIBILITY = ROOT / "src/semantic/semantic_import_visibility.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
RESOLVER = ROOT / "src/semantic/resolve_expr_walk.elisa"
BINDING_RESOLVER = ROOT / "src/semantic/resolve_binding_capabilities.elisa"
POSITIVE = HERE / "module_symbol_path_matcher.elisa"
NEGATIVE = HERE / "module_symbol_path_matcher_rejected.elisa"
ALIAS_BRANCH_FIXTURE = ROOT / "test/repro/type_path_alias_static_branch.elisa"
ALIAS_BRANCH_SMOKE = ROOT / "test/parity/type_path_alias_static_branch_smoke.sh"

parser = argparse.ArgumentParser()
parser.add_argument("--source-only", action="store_true",
                    help="check source and fixture bindings without invoking the proof product")
ARGS = parser.parse_args()

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(source: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in expand_return_if_blocks(source).splitlines())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def declarations(source: str) -> set[str]:
    return set(re.findall(r"(?m)^[ \t]*def ([A-Za-z_][A-Za-z0-9_]*)\(", source))


policy_text = POLICY.read_text()
consumer_text = CONSUMER.read_text()
import_visibility_text = IMPORT_VISIBILITY.read_text()
semantic_text = SEMANTIC.read_text()
resolver_text = RESOLVER.read_text()
binding_resolver_text = BINDING_RESOLVER.read_text()
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()

expected_absolute = '''
def absolute(candidate: sview, prefix: sview, names: darray[sview]&, from: usize, count: usize) -> bool:
    can Abort.Panic:
        return false if from > count or count > names.count
        cursor: mutable usize = 0
        candidate_length: usize = candidate.len
        prefix_length: usize = prefix.len
        if prefix_length > 0:
            for offset in 0..<prefix_length |cursor, candidate, candidate_length, prefix|:
                return false if cursor >= candidate_length or candidate[cursor] != prefix[offset]
                assert cursor < candidate_length
                cursor <- cursor + 1.usize()
                assert cursor <= candidate_length
            return false if cursor > candidate_length or candidate_length - cursor < 2 or candidate[cursor] != 58 or candidate[cursor + 1.usize()] != 58
            assert cursor <= candidate_length and candidate_length - cursor >= 2
            cursor <- cursor + 2.usize()
            assert cursor <= candidate_length
        for index in from..<count |cursor, candidate, candidate_length, names, from|:
            invariant from <= index
            invariant index <= count
            if index > from:
                return false if cursor > candidate_length or candidate_length - cursor < 2 or candidate[cursor] != 58 or candidate[cursor + 1.usize()] != 58
                assert cursor <= candidate_length and candidate_length - cursor >= 2
                cursor <- cursor + 2.usize()
                assert cursor <= candidate_length
            segment: sview = names[index]
            for offset in 0..<segment.len |cursor, candidate, candidate_length, segment|:
                return false if cursor >= candidate_length or candidate[cursor] != segment[offset]
                assert cursor < candidate_length
                cursor <- cursor + 1.usize()
                assert cursor <= candidate_length
        return cursor == candidate_length
'''
expected_relative = '''
def relative(candidate: sview, enclosing: sview, names: darray[sview]&, count: usize) -> bool:
    can Abort.Panic:
        return false if count == 0 or count > names.count
        path_length: mutable usize = 0
        candidate_length: usize = candidate.len
        return false if candidate_length < 3
        for index in 0..<count |path_length, names, candidate_length|:
            segment_length: usize = (names[index]).len
            return false if path_length > candidate_length or segment_length > candidate_length - path_length
            path_length <- path_length + segment_length
            if index + 1.usize() < count:
                return false if candidate_length - path_length < 2
                path_length <- path_length + 2.usize()
        return false if path_length > candidate_length - 3.usize()
        ancestor_length: usize = candidate_length - path_length - 2.usize()
        return false if candidate[ancestor_length] != 58 or candidate[ancestor_length + 1.usize()] != 58
        enclosing_length: usize = enclosing.len
        return false if enclosing_length < ancestor_length
        if enclosing_length > ancestor_length:
            false return if enclosing_length - ancestor_length < 2
            false return if enclosing[ancestor_length] != 58 or enclosing[ancestor_length + 1.usize()] != 58
        for offset in 0..<ancestor_length |candidate, enclosing|:
            invariant ancestor_length <= candidate_length
            invariant ancestor_length <= enclosing_length
            return false if candidate[offset] != enclosing[offset]
        cursor: mutable usize = ancestor_length + 2.usize()
                assert cursor <= candidate_length
        for index in 0..<count |cursor, candidate, candidate_length, names|:
            invariant index <= count
            if index > 0:
                return false if cursor > candidate_length or candidate_length - cursor < 2 or candidate[cursor] != 58 or candidate[cursor + 1.usize()] != 58
                        assert cursor <= candidate_length and candidate_length - cursor >= 2
                cursor <- cursor + 2.usize()
                        assert cursor <= candidate_length
            segment: sview = names[index]
            for offset in 0..<segment.len |cursor, candidate, candidate_length, segment|:
                return false if cursor >= candidate_length or candidate[cursor] != segment[offset]
                        assert cursor < candidate_length
                cursor <- cursor + 1.usize()
                        assert cursor <= candidate_length
        return cursor == candidate_length
'''
if "moduleSemanticModuleSymbolPathMatcher:" not in compact(policy_text):
    raise SystemExit("module-symbol path matcher module is missing")
if compact(function_section(policy_text, "absolute")) != compact(expected_absolute):
    raise SystemExit("absolute module matcher changed without updating its proof")
if compact(function_section(policy_text, "relative")) != compact(expected_relative):
    raise SystemExit("relative module matcher changed without updating its proof")

if consumer_text.count('include "./module_symbol_path_matcher.elisa"') != 1:
    raise SystemExit("semantic path consumer must include the proved module matcher exactly once")
for wrapper, expected in {
    "module_symbol_matches": '''
def module_symbol_matches(candidate: sview, prefix: sview, names: darray[sview]&, from: usize, count: usize) -> bool:
    can Abort.Panic:
        return SemanticModuleSymbolPathMatcher::absolute(candidate, prefix, names, from, count)
''',
    "module_symbol_matches_relative": '''
def module_symbol_matches_relative(candidate: sview, enclosing: sview, names: darray[sview]&, count: usize) -> bool:
    can Abort.Panic:
        return SemanticModuleSymbolPathMatcher::relative(candidate, enclosing, names, count)
''',
}.items():
    if compact(function_section(consumer_text, wrapper)) != compact(expected):
        raise SystemExit(f"semantic {wrapper} no longer delegates to its proved matcher")
if semantic_text.count('include "./check_type_path_separator.elisa"') != 1:
    raise SystemExit("semantic root must include the matcher wrappers exactly once")
alias_visibility = compact(function_section(consumer_text, "type_path_prefix_is_module"))
alias_canonicalization = compact(function_section(consumer_text, "type_path_canonical_alias_target"))
alias_selection = compact(function_section(consumer_text, "type_path_alias_selection"))
alias_order = compact(function_section(import_visibility_text, "semantic_possible_import_alias_precedes"))
alias_cutoff = compact(function_section(consumer_text, "type_path_possible_alias_precedes_cutoff"))
alias_unordered_cutoff = compact(function_section(consumer_text, "type_path_alias_name_has_unordered_cutoff_row"))
raw_module_target = compact(function_section(consumer_text, "type_path_raw_module_target"))
module_alias_row = compact(function_section(consumer_text, "type_path_module_symbol_is_using_alias"))
alias_branch = compact(function_section(consumer_text, "type_path_alias_branch_at"))
alias_setup = compact(function_section(consumer_text, "check_type_path_separator"))
alias_fixture = ALIAS_BRANCH_FIXTURE.read_text()
alias_smoke = ALIAS_BRANCH_SMOKE.read_text()
negative_alias_only_smoke = compact('''
if grep -Fq '"RawAliasOnlyTarget" is a namespace; write RawAliasOnlyTarget::' <<< "$report"; then
    fail "$label treated a later using-alias as a declared raw module for an earlier alias target: $report"
fi
''')
if negative_alias_only_smoke not in compact(alias_smoke):
    raise SystemExit("TypePath smoke must fail if a later alias-only name is accepted as a raw declared module")
if not all(fragment in alias_visibility for fragment in (
        "alias_uncertain:darray[bool]&",
        "type_path_alias_selection(names[0],alias_names,alias_targets,alias_scopes,alias_uncertain,table)",
        "module_symbol_matches(symbol_name,alias_targets[alias.row],names,1,count)")) or not all(fragment in alias_canonicalization for fragment in (
        "alias_raw_targets:darray[sview@source]&",
        "type_path_alias_selection(first,alias_names,alias_raw_targets,alias_scopes,alias_uncertain,table,declaration_scope,declaration_offset,declaration_index,declaration_branch,has_declaration)",
        "alias_raw_targets[alias_index]",
        "alias_scopes[alias_index],alias_class.offset,alias_class.order_index,alias_class.branch,true,depth+1",
        "return(path,false)ifalias.found",
        "ifhas_declaration",
        "type_path_raw_module_target(path,declaration_scope,table)",
        "return(raw_module.module,true)ifraw_module.found",
        "return(intern_joined_text(bytes,table),canonical_prefix.known)")) or not all(fragment in alias_selection for fragment in (
        "alias_names[alias_index]!=name",
        "alias_uncertain[alias_index]",
        "cutoff_scope:sview",
        "enforce_cutoff:bool",
        "type_path_alias_branch_at(name,alias_scopes[selected_row],selected_occurrence,table)",
        "semantic_possible_import_alias_precedes(table.definite_import_annotations[candidate_class.order_index],table.definite_import_annotations[selected_class.order_index],table)",
        "foralias_indexin0..<alias_names.count|ambiguous,name,alias_names,alias_scopes,selected_row,selected_class,table|",
        "ambiguous<-false",
        "ifcutoff_order.known",
        "notwinner_order.knownorwinner_order.precedes",
        "alias_index==selected_rowornotwinner_order.knownorwinner_order.precedes",
        "forannotationinttable.possible_import_annotations",
        'annotation.name!="__using_alias"orannotation.owner!=name',
        "type_path_possible_alias_precedes_cutoff(name,cutoff_scope,cutoff_offset,cutoff_index,cutoff_branch,enforce_cutoff,table)",
        "type_path_alias_name_has_unordered_cutoff_row(name,cutoff_index,table)",
        "return(true,false,alias_names.count)",
        "return(true,false,alias_names.count)ifambiguousoruncertain")) or not all(fragment in alias_setup for fragment in (
        "alias_raw_targets:mutabledarray[sview@source]=[]",
        "for alias_row in table.definite_import_annotations",
        'alias_row.name!="__using_alias"',
        'target_row.name=="__using_alias_target"',
        "alias_raw_targets.push(target_path)",
        "alias_uncertain.push(target_count!=1.usize())",
        "for alias_index in 0..<alias_names.count",
        "type_path_alias_branch_at(alias_names[alias_index],alias_scopes[alias_index],alias_occurrence,table)",
        "type_path_canonical_alias_target(alias_raw_targets[alias_index],alias_names,alias_raw_targets,alias_scopes,alias_uncertain,table,alias_scopes[alias_index],alias_class.offset,alias_class.order_index,alias_class.branch,alias_class.found)",
        "alias_uncertain[alias_index]<-alias_uncertain[alias_index]ornotalias_class.foundornotcanonical_target.known")):
    raise SystemExit("type-path namespace detection must preserve Stage0 global alias visibility and possible-target uncertainty")
if not all(fragment in alias_branch for fragment in (
        'alias.name!="__using_alias"oralias.owner!=nameoralias.module!=scope',
        'target.name=="__using_alias_target"',
        "target_count!=1.usize()",
        "semantic_import_alias_is_static_branch(alias,table)")):
    raise SystemExit("TypePath definite alias selection must retain same-scope direct-over-branch precedence")
if not all(fragment in alias_order for fragment in (
        "left.module==right.module",
        "branch_relation.shared_prefix",
        "both_definite:left_is_branchandright_is_branchandsemantic_possible_import_alias_is_definite(left,table)andsemantic_possible_import_alias_is_definite(right,table)",
        "semantic_possible_import_alias_branch_stack_relation(left,right,table)",
        "named_type_owner_is_lexical(left.module,right.module)",
        "named_type_owner_is_lexical(right.module,left.module)",
        "left.offset<right.offset")):
    raise SystemExit("TypePath alias selection must use Core ordering plus branch-context evidence")
if not all(fragment in alias_cutoff for fragment in (
        'annotation.name!="__using_alias"orannotation.owner!=name',
        "same_position:bool=annotation.module==cutoff_scopeandannotation.offset==cutoff_offsetandpossible_is_branch==cutoff_branch",
        "semantic_possible_import_alias_precedes(annotation,cutoff,table)",
        "cutoff_index>=table.definite_import_annotations.count")):
    raise SystemExit("TypePath alias-target chains must respect their Core registration cutoff")
if not all(fragment in alias_unordered_cutoff for fragment in (
        'candidate.name!="__using_alias"orcandidate.owner!=name',
        "semantic_possible_import_alias_precedes(candidate,cutoff,table)",
        "notorder.known")):
    raise SystemExit("TypePath alias targets must remain unresolved when a definite registration cutoff is unordered")
if not all(fragment in module_alias_row for fragment in (
        'annotation.name=="__using_alias"',
        "annotation.owner==symbol.name",
        "annotation.line==symbol.line",
        "annotation.offset==symbol.offset")) or raw_module_target.count("type_path_module_symbol_is_using_alias(symbol,table)") != 1 or not all(fragment in raw_module_target for fragment in (
        "candidate==pathorsemantic_import_module_path_matches(candidate,path,declaration_scope)",
        "semantic_import_module_path_matches(candidate,path,declaration_scope)",
        "candidate.len>selected.len",
        "candidate.len==selected.lenandcandidate!=selected")):
    raise SystemExit("TypePath raw alias-target fallback must exclude using-alias symbols and match only declared module paths")
if "foralias_indexin0..<alias_names.count" not in alias_selection or "continueifalias_names[alias_index]!=name" not in alias_selection:
    raise SystemExit("Stage0-global module aliases must scan every declaration scope before applying registration precedence")
if not all(fragment in alias_fixture for fragment in (
        "using TypePathAliasProvider as ActiveAlias",
        "using TypePathAliasProvider as InactiveAlias",
        "using TypePathAliasProvider as PossibleAlias",
        "static if false:",
        "static if ELISA_TARGET_OS_WASI:",
        "ActiveAlias.Item",
        "ActiveAlias::Nested.Item",
        "InactiveAlias.Item",
        "PossibleAlias.Item",
        "using PossibleAlias::Nested as ChainedAlias",
        "ChainedAlias.Item",
        "module AliasOwner:",
        "using AliasProvider as NestedGlobalAlias",
        "module LateAliasContainer:",
        "using LaterRootAlias::Nested as LateNestedAlias",
        "using TypePathAliasProvider as LaterRootAlias",
        "LateNestedAlias.Item",
        "NestedGlobalAlias.Item",
        "module EarlierNestedPossibleAlias:",
        "using TypePathAliasProvider as AncestorWins",
        "ancestor_alias_precedes_nested_possible",
        "module OtherTypePathAliasProvider:",
        "module RawFallbackModule:",
        "module Inner:",
        "module Inner:\n    struct RootItem:",
        "module Outer:",
        "module Outer:\n    module Inner:\n        module Nested:\n            struct Item:",
        "using Inner as ScopedAlias",
        "using Inner as ScopedAlias\n\ndef scoped_raw_module_alias_prefers_nearest_scope(value: ScopedAlias::Nested.Item)",
        "module RawFallbackAliasContainer:",
        "using RawFallbackModule::Nested as RawFallbackAlias",
        "using TypePathAliasProvider as RawFallbackModule",
        "later_alias_keeps_raw_module_target",
        "module RawAliasOnlyContainer:",
        "using RawAliasOnlyName as RawAliasOnlyTarget",
        "using TypePathAliasProvider as RawAliasOnlyName",
        "later_alias_does_not_create_raw_module",
        "using TypePathAliasProvider as DirectWins",
        "using OtherTypePathAliasProvider as DirectWins",
        "direct_alias_precedes_same_scope_possible",
        "module ParentBranchAfterChild:",
        "using FlatTypePathAliasProvider as BranchAfterChild",
        "using TypePathAliasProvider as BranchAfterChild",
        "later_parent_branch_does_not_win",
        "module ParentBranchBeforeChild:",
        "using TypePathAliasProvider as BranchBeforeChild",
        "using FlatTypePathAliasProvider as BranchBeforeChild",
        "earlier_parent_branch_wins",
        "module BranchBodyPrepass:",
        "using FlatTypePathAliasProvider as SharedBranchAlias",
        "using TypePathAliasProvider as SharedBranchAlias",
        "branch_body_direct_alias_wins",
        "using TypePathAliasProvider as BranchHeadBeforeChain",
        "using BranchHeadBeforeChain::Nested as BranchChainBeforeHead",
        "using BranchHeadAfterChain::Nested as BranchChainAfterHead",
        "using TypePathAliasProvider as BranchHeadAfterChain",
        "branch_alias_target_before_chain",
        "branch_alias_target_after_chain")) or not all(fragment in alias_smoke for fragment in (
        "type_path_alias_static_branch.elisa",
        "ELISA_STAGE1_TRIPLE=wasm32-unknown-unknown",
        '"ActiveAlias" is a namespace; write ActiveAlias::',
        '"ActiveAlias::Nested" is a namespace; write ActiveAlias::Nested::',
        '"InactiveAlias" is a namespace; write InactiveAlias::',
        '"PossibleAlias" is a namespace; write PossibleAlias::',
        '"ChainedAlias" is a namespace; write ChainedAlias::',
        '"NestedGlobalAlias" is a namespace; write NestedGlobalAlias::',
        '"LateNestedAlias" is a namespace; write LateNestedAlias::',
        '"AncestorWins::Nested" is a namespace; write AncestorWins::Nested::',
        '"DirectWins::Nested" is a namespace; write DirectWins::Nested::',
        '"RawFallbackAlias" is a namespace; write RawFallbackAlias::',
        '"ScopedAlias::Nested" is a namespace; write ScopedAlias::Nested::',
        '"RawAliasOnlyTarget" is a namespace; write RawAliasOnlyTarget::',
        '"BranchBeforeChild::Nested" is a namespace; write BranchBeforeChild::Nested::',
        '"BranchAfterChild::Nested" is a namespace; write BranchAfterChild::Nested::',
        '"SharedBranchAlias::Nested" is a namespace; write SharedBranchAlias::Nested::',
        '"BranchChainBeforeHead" is a namespace; write BranchChainBeforeHead::',
        '"BranchChainAfterHead" is a namespace; write BranchChainAfterHead::',
        'check_report native "$("$RPT" < "$FIXTURE")"',
        'check_report unknown-target "$(ELISA_STAGE1_TRIPLE=wasm32-unknown-unknown "$RPT" < "$FIXTURE")"')):
    raise SystemExit("type-path alias regression must retain Stage0-global aliases while ignoring inactive or uncertain alias targets")
qualified_candidate = compact(function_section(binding_resolver_text, "binding_nominal_qualified_candidate"))
nominal_lookup = compact(function_section(binding_resolver_text, "binding_nominal_declaration"))
if "module_symbol_matches(" not in qualified_candidate or "module_symbol_matches_relative(" not in qualified_candidate:
    raise SystemExit("qualified nominal candidate must retain both proven module-path matchers")
if "binding_nominal_qualified_candidate(" not in nominal_lookup:
    raise SystemExit("qualified nominal resolver must route through the proved candidate matcher")

positive_names = {
    "absolute_module_path_matches_all_segments",
    "prefixed_match_uses_only_the_selected_segment_range",
    "delimiter_and_full_length_are_both_required",
    "invalid_absolute_segment_ranges_fail_closed",
    "relative_child_matches_the_current_module",
    "relative_child_matches_an_enclosing_ancestor_boundary",
    "relative_multi_segment_suffix_matches_exactly",
    "short_candidate_and_empty_relative_paths_fail_closed",
}
negative_names = {
    "dotted_separator_is_an_absolute_module_path",
    "one_byte_enclosing_suffix_is_a_scope_boundary",
    "empty_relative_path_matches_a_module",
}
if 'include "../../src/semantic/module_symbol_path_matcher.elisa"' not in positive_text or \
        'include "./module_symbol_path_matcher.elisa"' not in negative_text:
    raise SystemExit("module matcher proof fixtures must import the production policy")
if declarations(positive_text) != positive_names or declarations(negative_text) != negative_names:
    raise SystemExit("module matcher proof declaration inventory changed")
for name in positive_names | negative_names:
    signature = compact(function_section(positive_text if name in positive_names else negative_text, name).splitlines()[0])
    if "can[Abort.Panic]" not in signature:
        raise SystemExit(f"module matcher theorem {name} must declare the lookup's panic effect")

positive_claims = {
    "absolute_module_path_matches_all_segments": 'SemanticModuleSymbolPathMatcher::absolute("Outer::Inner","",names,0,2)',
    "prefixed_match_uses_only_the_selected_segment_range": 'SemanticModuleSymbolPathMatcher::absolute("Alias::Inner::Type","Alias",names,1,3)',
    "delimiter_and_full_length_are_both_required": 'notSemanticModuleSymbolPathMatcher::absolute("Outer.Inner","",names,0,2)andnotSemanticModuleSymbolPathMatcher::absolute("Outer::Inner::Tail","",names,0,2)',
    "invalid_absolute_segment_ranges_fail_closed": 'notSemanticModuleSymbolPathMatcher::absolute("Only","",names,2,1)andnotSemanticModuleSymbolPathMatcher::absolute("Only::More","",names,0,2)',
    "relative_child_matches_the_current_module": 'SemanticModuleSymbolPathMatcher::relative("Outer::Inner::Type","Outer::Inner",names,1)',
    "relative_child_matches_an_enclosing_ancestor_boundary": 'SemanticModuleSymbolPathMatcher::relative("Outer::Inner::Type","Outer::Inner::Nested",names,1)',
    "relative_multi_segment_suffix_matches_exactly": 'SemanticModuleSymbolPathMatcher::relative("Outer::Inner::Type","Outer",names,2)',
    "short_candidate_and_empty_relative_paths_fail_closed": 'notSemanticModuleSymbolPathMatcher::relative("A::X","A",names,1)andnotSemanticModuleSymbolPathMatcher::relative("A::","A",empty,0)',
}
for name, claim in positive_claims.items():
    section = compact(function_section(positive_text, name))
    if "ensureresult==true" not in section or compact(claim) not in section:
        raise SystemExit(f"positive theorem {name} no longer establishes its source-bound claim")

negative_claims = {
    "dotted_separator_is_an_absolute_module_path": 'SemanticModuleSymbolPathMatcher::absolute("Outer.Inner","",names,0,2)',
    "one_byte_enclosing_suffix_is_a_scope_boundary": 'SemanticModuleSymbolPathMatcher::relative("A::Leaf","A:",names,1)',
    "empty_relative_path_matches_a_module": 'SemanticModuleSymbolPathMatcher::relative("A::","A",names,0)',
}
for name, claim in negative_claims.items():
    section = compact(function_section(negative_text, name))
    if "ensureresult==true" not in section or compact(claim) not in section:
        raise SystemExit(f"false-claim control {name} no longer asserts the rejected claim")

source_closure = source_include_closure([POSITIVE, NEGATIVE, ALIAS_BRANCH_FIXTURE])
if ARGS.source_only:
    print(json.dumps({"source_bound": True, "positive": len(positive_names),
                      "false_claim_controls": len(negative_names)}, sort_keys=True))
    raise SystemExit(0)

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("module path matcher proofs require a strict proof build")

stage1 = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
provenance = Path(str(stage1) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1, provenance, Path(__file__),
    HERE / "proof_product_gate.py", POLICY, CONSUMER, SEMANTIC, RESOLVER, BINDING_RESOLVER,
    POSITIVE, NEGATIVE, ALIAS_BRANCH_FIXTURE, ALIAS_BRANCH_SMOKE, *source_closure,
]))
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
assert positive["summary"]["declarations"] == len(positive_names)
assert positive["summary"]["obligations"] == positive["summary"]["proven"]
assert not positive["findings"]
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == positive_names

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert not negative_names & {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product

print(json.dumps({
    "admitted": True,
    "scope": "absolute and enclosing-relative module path matching",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
