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


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve()
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
POLICY = ROOT / "src/semantic/module_symbol_path_matcher.elisa"
CONSUMER = ROOT / "src/semantic/check_type_path_separator.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
RESOLVER = ROOT / "src/semantic/resolve_expr_walk.elisa"
BINDING_RESOLVER = ROOT / "src/semantic/resolve_binding_capabilities.elisa"
POSITIVE = HERE / "module_symbol_path_matcher.elisa"
NEGATIVE = HERE / "module_symbol_path_matcher_rejected.elisa"

parser = argparse.ArgumentParser()
parser.add_argument("--source-only", action="store_true",
                    help="check source and fixture bindings without invoking the proof product")
ARGS = parser.parse_args()

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(source: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in source.splitlines())


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
semantic_text = SEMANTIC.read_text()
resolver_text = RESOLVER.read_text()
binding_resolver_text = BINDING_RESOLVER.read_text()
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()

expected_absolute = '''
def absolute(candidate: sview, prefix: sview, names: darray[sview]&, from: usize, count: usize) -> bool:
    can Abort.Panic:
        false return if from > count or count > names.count
        cursor: mutable usize = 0
        candidate_length: usize = candidate.len
        prefix_length: usize = prefix.len
        if prefix_length > 0:
            for offset in 0..<prefix_length |cursor, candidate, candidate_length, prefix|:
                invariant cursor <= candidate_length
                false return if cursor >= candidate_length or candidate[cursor] != prefix[offset]
                cursor <- cursor + 1.usize()
            false return if cursor > candidate_length or candidate_length - cursor < 2 or candidate[cursor] != 58 or candidate[cursor + 1.usize()] != 58
            cursor <- cursor + 2.usize()
        for index in from..<count |cursor, candidate, candidate_length, names, from|:
            invariant from <= index
            invariant index <= count
            invariant cursor <= candidate_length
            if index > from:
                false return if cursor > candidate_length or candidate_length - cursor < 2 or candidate[cursor] != 58 or candidate[cursor + 1.usize()] != 58
                cursor <- cursor + 2.usize()
            segment: sview = names[index]
            for offset in 0..<segment.len |cursor, candidate, candidate_length, segment|:
                invariant cursor <= candidate_length
                false return if cursor >= candidate_length or candidate[cursor] != segment[offset]
                cursor <- cursor + 1.usize()
        return cursor == candidate_length
'''
expected_relative = '''
def relative(candidate: sview, enclosing: sview, names: darray[sview]&, count: usize) -> bool:
    can Abort.Panic:
        false return if count == 0 or count > names.count
        path_length: mutable usize = 0
        candidate_length: usize = candidate.len
        false return if candidate_length < 3
        for index in 0..<count |path_length, names, candidate_length|:
            invariant path_length <= candidate_length
            segment_length: usize = (names[index]).len
            false return if path_length > candidate_length or segment_length > candidate_length - path_length
            path_length <- path_length + segment_length
            if index + 1.usize() < count:
                false return if candidate_length - path_length < 2
                path_length <- path_length + 2.usize()
        false return if path_length > candidate_length - 3.usize()
        ancestor_length: usize = candidate_length - path_length - 2.usize()
        false return if candidate[ancestor_length] != 58 or candidate[ancestor_length + 1.usize()] != 58
        enclosing_length: usize = enclosing.len
        false return if enclosing_length < ancestor_length
        if enclosing_length > ancestor_length:
            false return if enclosing_length - ancestor_length < 2
            false return if enclosing[ancestor_length] != 58 or enclosing[ancestor_length + 1.usize()] != 58
        for offset in 0..<ancestor_length |candidate, enclosing|:
            invariant ancestor_length <= candidate_length
            invariant ancestor_length <= enclosing_length
            false return if candidate[offset] != enclosing[offset]
        cursor: mutable usize = ancestor_length + 2.usize()
        for index in 0..<count |cursor, candidate, candidate_length, names|:
            invariant cursor <= candidate_length
            invariant index <= count
            if index > 0:
                false return if cursor > candidate_length or candidate_length - cursor < 2 or candidate[cursor] != 58 or candidate[cursor + 1.usize()] != 58
                cursor <- cursor + 2.usize()
            segment: sview = names[index]
            for offset in 0..<segment.len |cursor, candidate, candidate_length, segment|:
                invariant cursor <= candidate_length
                false return if cursor >= candidate_length or candidate[cursor] != segment[offset]
                cursor <- cursor + 1.usize()
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
nominal_lookup = compact(function_section(binding_resolver_text, "binding_nominal_declaration"))
if "module_symbol_matches(" not in nominal_lookup or "module_symbol_matches_relative(" not in nominal_lookup:
    raise SystemExit("qualified nominal resolver must retain both proven module-path matchers")

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

source_closure = source_include_closure([POSITIVE, NEGATIVE])
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
    POSITIVE, NEGATIVE, *source_closure,
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
