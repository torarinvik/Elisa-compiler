"""Source-bind exact-name membership used by both associated-index safety gates."""
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
SOURCE = ROOT / "src/semantic/assoc_index_name_membership.elisa"
CONSUMER = ROOT / "src/semantic/check_assoc_index_bounds.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
POSITIVE = HERE / "assoc_index_name_membership.elisa"
NEGATIVE = HERE / "assoc_index_name_membership_rejected.elisa"
POSITIVE_NAMES = {
    "production_scan_matches_recursive_name_specification",
    "later_exact_name_is_found",
    "distinct_spelling_is_not_found",
    "empty_name_set_has_no_member",
    "production_checker_uses_the_proved_scan_at_both_gates",
}
NEGATIVE_NAMES = {"absent_name_is_reported_as_a_member"}

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
ghost def name_in_from(names: darray[sview]&, candidate: sview, index: usize) -> bool:
    requires index <= names.count
    decreases names.count - index
    return false if index == names.count
    return true if names[index] == candidate
    return name_in_from(names, candidate, index + 1)
'''
expected_scan = '''
def name_in(names: darray[sview]&, candidate: sview) -> bool:
    ensure result == name_in_from(names, candidate, 0)
    for index in 0..<names.count |index|:
        invariant index <= names.count
        invariant name_in_from(names, candidate, index) == name_in_from(names, candidate, 0)
        return true if names[index] == candidate
    return false
'''
if compact(function_section(source_text, "name_in_from")) != compact(expected_model):
    raise SystemExit("recursive exact-name model changed without updating its proof")
if compact(function_section(source_text, "name_in")) != compact(expected_scan):
    raise SystemExit("production exact-name scan no longer refines its recursive model")
if consumer_text.count('include "./assoc_index_name_membership.elisa"') != 1:
    raise SystemExit("associated-index checker must include the source-proved exact-name scan exactly once")
if "def aib_name_in(" in consumer_text:
    raise SystemExit("unproved inlined generic-name scan must not remain")
array_call = "SemanticAssocIndexNames::name_in(array_params, receiver)"
generic_call = "SemanticAssocIndexNames::name_in(generic_params, receiver_name)"
if consumer_text.count(array_call) != 1 or consumer_text.count(generic_call) != 1:
    raise SystemExit("both array-root and generic-receiver membership gates must use the proved scan exactly once")
if array_call not in function_section(consumer_text, "aib_walk_expr"):
    raise SystemExit("array-root recognition must use the proved membership scan")
if generic_call not in function_section(consumer_text, "aib_index_is_unproven_assoc"):
    raise SystemExit("generic-receiver recognition must use the proved membership scan")
if semantic_text.count('include "./check_assoc_index_bounds.elisa"') != 1:
    raise SystemExit("semantic root must include the associated-index checker exactly once")
if 'include "../../src/semantic/assoc_index_name_membership.elisa"' not in positive_text or \
        'include "./assoc_index_name_membership.elisa"' not in negative_text:
    raise SystemExit("proof candidates must import the production exact-name scan")
if declarations(positive_text) != POSITIVE_NAMES or declarations(negative_text) != NEGATIVE_NAMES:
    raise SystemExit("exact-name membership proof declaration inventory changed")

expected_positive = {
    "production_scan_matches_recursive_name_specification": '''
def production_scan_matches_recursive_name_specification(names: darray[sview]&, candidate: sview) -> bool:
    ensure result == true
    return SemanticAssocIndexNames::name_in(names, candidate) == SemanticAssocIndexNames::name_in_from(names, candidate, 0)
''',
    "later_exact_name_is_found": '''
def later_exact_name_is_found() -> bool:
    ensure result == true
    names: darray[sview] = ["array", "decoder", "decoder"]
    return SemanticAssocIndexNames::name_in(names, "decoder")
''',
    "distinct_spelling_is_not_found": '''
def distinct_spelling_is_not_found() -> bool:
    ensure result == true
    names: darray[sview] = ["Decoder", "decoder_2"]
    return not SemanticAssocIndexNames::name_in(names, "decoder")
''',
    "empty_name_set_has_no_member": '''
def empty_name_set_has_no_member() -> bool:
    ensure result == true
    names: darray[sview] = []
    return not SemanticAssocIndexNames::name_in(names, "decoder")
''',
    "production_checker_uses_the_proved_scan_at_both_gates": '''
def production_checker_uses_the_proved_scan_at_both_gates() -> bool:
    ensure result == true
    names: darray[sview] = ["array", "decoder"]
    return SemanticAssocIndexNames::name_in(names, "array") and SemanticAssocIndexNames::name_in(names, "decoder")
''',
}
for name, expected in expected_positive.items():
    if compact(function_section(positive_text, name)) != compact(expected):
        raise SystemExit(f"positive theorem {name} changed without updating its source-bound proof gate")

expected_negative = '''
def absent_name_is_reported_as_a_member() -> bool:
    ensure result == true
    names: darray[sview] = ["array", "decoder"]
    return SemanticAssocIndexNames::name_in(names, "missing")
'''
if compact(function_section(negative_text, "absent_name_is_reported_as_a_member")) != compact(expected_negative):
    raise SystemExit("rejected control must claim an absent exact name is present")

source_closure = source_include_closure([POSITIVE, NEGATIVE])
try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("exact-name membership proof requires a strict proof build")

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
assert POSITIVE_NAMES | {"name_in", "name_in_from"} <= verified_positive

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert {(row["kind"], row["name"]) for row in negative["findings"]} == {
    ("ensure-unproven", name) for name in NEGATIVE_NAMES
}
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product

print(json.dumps({
    "admitted": True,
    "scope": "exact membership for array-root and generic-receiver gates",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(NEGATIVE_NAMES),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
