"""Source-bind the associated-index refinement membership scan and controls."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve(strict=True)
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
SOURCE = ROOT / "src/semantic/assoc_index_membership.elisa"
CONSUMER = ROOT / "src/semantic/check_assoc_index_bounds.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
POSITIVE = HERE / "assoc_index_membership.elisa"
NEGATIVE = HERE / "assoc_index_membership_rejected.elisa"
POSITIVE_NAMES = {
    "production_scan_matches_the_recursive_specification",
    "later_unrefined_duplicate_makes_method_unproven",
    "all_matching_implementations_refined_are_proven",
    "unrelated_unrefined_method_does_not_match",
    "missing_refinement_row_fails_closed",
    "extra_refinement_rows_do_not_create_a_method",
}
NEGATIVE_NAMES = {"missing_refinement_row_is_considered_refined"}

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(source: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in source.splitlines())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)(?:ghost )?def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}(?:ghost )?def [A-Za-z_][A-Za-z0-9_]*\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def declarations(source: str) -> set[str]:
    return set(re.findall(r"(?m)^[ \t]*(?:ghost )?def ([A-Za-z_][A-Za-z0-9_]*)\(", source))


source_text = SOURCE.read_text()
consumer_text = CONSUMER.read_text()
semantic_text = SEMANTIC.read_text()
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()

expected_model = '''
ghost def method_unproven_from(method_names: darray[sview]&, method_refined: darray[bool]&, method: sview, remaining: usize) -> bool:
    decreases remaining
    return false if:
        remaining == 0
        remaining > method_names.count
    return (
        method_names[method_names.count - remaining] == method
        and not (method_names.count - remaining < method_refined.count and method_refined[method_names.count - remaining])
    ) or method_unproven_from(method_names, method_refined, method, remaining - 1)
'''
expected_scan = '''
def method_unproven(method_names: darray[sview]&, method_refined: darray[bool]&, method: sview) -> bool:
    ensure result == method_unproven_from(method_names, method_refined, method, method_names.count)
    found: mutable bool = false
    remaining: mutable usize = method_names.count
    while remaining > 0 |found, remaining, method_names, method_refined, method|:
        invariant remaining <= method_names.count
        invariant method_unproven_from(method_names, method_refined, method, method_names.count) == (found or method_unproven_from(method_names, method_refined, method, remaining))
        index: usize = method_names.count - remaining
        refined: bool = index < method_refined.count and method_refined[index]
        found <- found or (method_names[index] == method and not refined)
        remaining <- remaining - 1
    return found
'''
if compact(function_section(source_text, "method_unproven_from")) != compact(expected_model):
    raise SystemExit("recursive membership model changed without updating its proof")
if compact(function_section(source_text, "method_unproven")) != compact(expected_scan):
    raise SystemExit("production membership scan no longer refines its recursive model")
if consumer_text.count('include "./assoc_index_membership.elisa"') != 1:
    raise SystemExit("associated-index checker must include the isolated production membership scan exactly once")
production_call = "SemanticAssocIndex::method_unproven(method_names, method_refined, method)"
if consumer_text.count(production_call) != 1:
    raise SystemExit("associated-index safety decision must use the source-proved membership scan")
if "def aib_method_unproven(" in consumer_text:
    raise SystemExit("unproved inlined method-membership scan must not remain in the semantic checker")
if production_call not in function_section(consumer_text, "aib_index_is_unproven_assoc"):
    raise SystemExit("the generic associated-index decision must call the proved membership scan")
collector = compact(function_section(consumer_text, "aib_collect_impl_methods"))
collector_invariants = "invariantmethod_names.count==method_refined.count"
if ("requiresmethod_names.count==method_refined.count" not in collector or
        "ensuremethod_names.count==method_refined.count" not in collector or
        collector.count(collector_invariants) != 2 or
        collector.count("assertmethod_names.count==method_refined.count") < 4):
    raise SystemExit("impl-method collection must preserve the parallel method/refinement table invariant")
name_push = collector.find("method_names.push(name)")
refinement_push = collector.find("method_refined.push(refined)")
if name_push < 0 or refinement_push <= name_push:
    raise SystemExit("each impl method must append its name and refinement together in aligned order")
if (collector.count("aib_collect_impl_methods(body,annotations,method_names,method_refined)") != 1 or
        collector.count("aib_collect_impl_methods(module_body,annotations,method_names,method_refined)") != 1):
    raise SystemExit("recursive impl collectors must preserve the same paired side tables")
entry = compact(function_section(consumer_text, "check_assoc_index_bounds"))
if ("method_names:mutabledarray[sview]=[]" not in entry or
        "method_refined:mutabledarray[bool]=[]" not in entry or
        "assertmethod_names.count==method_refined.count" not in entry or
        "aib_collect_impl_methods(file.top_decls,file.enum_annotations,method_names,method_refined)" not in entry or
        entry.count("assertmethod_names.count==method_refined.count") != 2):
    raise SystemExit("top-level impl collection must establish equal empty vectors before recursive scanning")
if semantic_text.count('include "./check_assoc_index_bounds.elisa"') != 1:
    raise SystemExit("semantic root must include the associated-index checker exactly once")
if 'include "../../src/semantic/assoc_index_membership.elisa"' not in positive_text or \
        'include "./assoc_index_membership.elisa"' not in negative_text:
    raise SystemExit("proof candidates must import the production membership implementation")
if declarations(positive_text) != POSITIVE_NAMES or declarations(negative_text) != NEGATIVE_NAMES:
    raise SystemExit("associated-index proof declaration inventory changed")

expected_positive = {
    "production_scan_matches_the_recursive_specification": '''
def production_scan_matches_the_recursive_specification(method_names: darray[sview]&, method_refined: darray[bool]&, method: sview) -> bool:
    ensure result == true
    return SemanticAssocIndex::method_unproven(method_names, method_refined, method) == SemanticAssocIndex::method_unproven_from(method_names, method_refined, method, method_names.count)
''',
    "later_unrefined_duplicate_makes_method_unproven": '''
def later_unrefined_duplicate_makes_method_unproven() -> bool:
    ensure result == true
    method_names: darray[sview] = ["decode", "other", "decode"]
    method_refined: darray[bool] = [true, false, false]
    return SemanticAssocIndex::method_unproven(method_names, method_refined, "decode")
''',
    "all_matching_implementations_refined_are_proven": '''
def all_matching_implementations_refined_are_proven() -> bool:
    ensure result == true
    method_names: darray[sview] = ["decode", "decode"]
    method_refined: darray[bool] = [true, true]
    return not SemanticAssocIndex::method_unproven(method_names, method_refined, "decode")
''',
    "unrelated_unrefined_method_does_not_match": '''
def unrelated_unrefined_method_does_not_match() -> bool:
    ensure result == true
    method_names: darray[sview] = ["other", "third"]
    method_refined: darray[bool] = [false, false]
    return not SemanticAssocIndex::method_unproven(method_names, method_refined, "decode")
''',
    "missing_refinement_row_fails_closed": '''
def missing_refinement_row_fails_closed() -> bool:
    ensure result == true
    method_names: darray[sview] = ["decode"]
    method_refined: darray[bool] = []
    return SemanticAssocIndex::method_unproven(method_names, method_refined, "decode")
''',
    "extra_refinement_rows_do_not_create_a_method": '''
def extra_refinement_rows_do_not_create_a_method() -> bool:
    ensure result == true
    method_names: darray[sview] = []
    method_refined: darray[bool] = [false]
    return not SemanticAssocIndex::method_unproven(method_names, method_refined, "decode")
''',
}
for name, expected in expected_positive.items():
    if compact(function_section(positive_text, name)) != compact(expected):
        raise SystemExit(f"positive theorem {name} changed without updating its source-bound proof gate")

expected_negative = '''
def missing_refinement_row_is_considered_refined() -> bool:
    ensure result == true
    method_names: darray[sview] = ["decode"]
    method_refined: darray[bool] = []
    return not SemanticAssocIndex::method_unproven(method_names, method_refined, "decode")
'''
if compact(function_section(negative_text, "missing_refinement_row_is_considered_refined")) != compact(expected_negative):
    raise SystemExit("rejected control must assert the opposite missing-refinement behavior")

source_closure = source_include_closure([POSITIVE, NEGATIVE])
try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("associated-index membership proof requires a strict proof build")

stage1_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN,
    BIN.with_name(BIN.name + ".manifest.json"),
    BIN.with_name(BIN.name + ".manifest.json.sha256"),
    PROVER / "ELISA_COMPILER_REV",
    stage1_product,
    stage1_provenance,
    Path(__file__),
    HERE / "proof_product_gate.py",
    SOURCE,
    CONSUMER,
    SEMANTIC,
    POSITIVE,
    NEGATIVE,
    *source_closure,
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
    assert report["trust"]["kernel_replayed_certificates"] == report["replay"]["replayed"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["obligations"] == positive["summary"]["proven"]
assert not positive["findings"]
verified_positive = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert POSITIVE_NAMES | {"method_unproven", "method_unproven_from"} <= verified_positive

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert {(row["kind"], row["name"]) for row in negative["findings"]} == {
    ("ensure-unproven", name) for name in NEGATIVE_NAMES
}
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product

print(json.dumps({
    "admitted": True,
    "scope": "any matching implementation with a dropped or missing associated-index refinement",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(NEGATIVE_NAMES),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
