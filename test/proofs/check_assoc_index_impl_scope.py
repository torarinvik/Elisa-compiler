"""Source-bind impl-scope annotation recognition and adversarial controls."""
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
SOURCE = ROOT / "src/semantic/assoc_index_impl_scope.elisa"
CONSUMER = ROOT / "src/semantic/check_assoc_index_bounds.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
POSITIVE = HERE / "assoc_index_impl_scope.elisa"
NEGATIVE = HERE / "assoc_index_impl_scope_rejected.elisa"
POSITIVE_NAMES = {
    "production_scan_matches_recursive_scope_specification",
    "exact_impl_scope_marker_is_recognized",
    "another_annotation_at_same_line_is_ignored",
    "impl_marker_on_another_line_is_ignored",
    "no_annotations_means_no_impl_scope",
}
NEGATIVE_NAMES = {"ordinary_annotation_marks_an_impl_scope"}

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
ghost def line_is_impl_scope_from(annotations: darray[Ast::EnumAnnotation]&, line: u32, index: usize) -> bool:
    requires index <= annotations.count
    decreases annotations.count - index
    return false if index == annotations.count
    annotation: Ast::EnumAnnotation = annotations[index]
    return true if annotation.owner == "__impl_scope" and annotation.line == line
    return line_is_impl_scope_from(annotations, line, index + 1)
'''
expected_scan = '''
def line_is_impl_scope(annotations: darray[Ast::EnumAnnotation]&, line: u32) -> bool:
    ensure result == line_is_impl_scope_from(annotations, line, 0)
    for index in 0..<annotations.count |index|:
        invariant index <= annotations.count
        invariant line_is_impl_scope_from(annotations, line, index) == line_is_impl_scope_from(annotations, line, 0)
        annotation: Ast::EnumAnnotation = annotations[index]
        return true if annotation.owner == "__impl_scope" and annotation.line == line
    return false
'''
if compact(function_section(source_text, "line_is_impl_scope_from")) != compact(expected_model):
    raise SystemExit("recursive impl-scope model changed without updating its proof")
if compact(function_section(source_text, "line_is_impl_scope")) != compact(expected_scan):
    raise SystemExit("production impl-scope scan no longer refines its recursive model")
if consumer_text.count('include "./assoc_index_impl_scope.elisa"') != 1:
    raise SystemExit("associated-index checker must include the isolated impl-scope scan exactly once")
production_call = "SemanticAssocIndexScope::line_is_impl_scope(annotations, scoped_line.line)"
if consumer_text.count(production_call) != 1:
    raise SystemExit("impl method collection must use the source-proved scope marker scan")
if production_call not in function_section(consumer_text, "aib_collect_impl_methods"):
    raise SystemExit("impl method collection must classify scoped declarations with the proved scan")
if semantic_text.count('include "./check_assoc_index_bounds.elisa"') != 1:
    raise SystemExit("semantic root must include the associated-index checker exactly once")
if 'include "../../src/semantic/assoc_index_impl_scope.elisa"' not in positive_text or \
        'include "./assoc_index_impl_scope.elisa"' not in negative_text:
    raise SystemExit("proof candidates must import the production impl-scope scan")
if declarations(positive_text) != POSITIVE_NAMES or declarations(negative_text) != NEGATIVE_NAMES:
    raise SystemExit("impl-scope proof declaration inventory changed")

expected_positive = {
    "production_scan_matches_recursive_scope_specification": '''
def production_scan_matches_recursive_scope_specification(annotations: darray[Ast::EnumAnnotation]&, line: u32) -> bool:
    ensure result == true
    return SemanticAssocIndexScope::line_is_impl_scope(annotations, line) == SemanticAssocIndexScope::line_is_impl_scope_from(annotations, line, 0)
''',
    "exact_impl_scope_marker_is_recognized": '''
def exact_impl_scope_marker_is_recognized() -> bool:
    ensure result == true
    annotations: darray[Ast::EnumAnnotation] = [
        Ast::EnumAnnotation{owner: "__impl_scope", name: "FieldDecoder", line: 17}
    ]
    return SemanticAssocIndexScope::line_is_impl_scope(annotations, 17)
''',
    "another_annotation_at_same_line_is_ignored": '''
def another_annotation_at_same_line_is_ignored() -> bool:
    ensure result == true
    annotations: darray[Ast::EnumAnnotation] = [
        Ast::EnumAnnotation{owner: "__other", name: "FieldDecoder", line: 17}
    ]
    return not SemanticAssocIndexScope::line_is_impl_scope(annotations, 17)
''',
    "impl_marker_on_another_line_is_ignored": '''
def impl_marker_on_another_line_is_ignored() -> bool:
    ensure result == true
    annotations: darray[Ast::EnumAnnotation] = [
        Ast::EnumAnnotation{owner: "__impl_scope", name: "FieldDecoder", line: 17}
    ]
    return not SemanticAssocIndexScope::line_is_impl_scope(annotations, 18)
''',
    "no_annotations_means_no_impl_scope": '''
def no_annotations_means_no_impl_scope() -> bool:
    ensure result == true
    annotations: darray[Ast::EnumAnnotation] = []
    return not SemanticAssocIndexScope::line_is_impl_scope(annotations, 17)
''',
}
for name, expected in expected_positive.items():
    if compact(function_section(positive_text, name)) != compact(expected):
        raise SystemExit(f"positive theorem {name} changed without updating its source-bound proof gate")

expected_negative = '''
def ordinary_annotation_marks_an_impl_scope() -> bool:
    ensure result == true
    annotations: darray[Ast::EnumAnnotation] = [
        Ast::EnumAnnotation{owner: "__other", name: "FieldDecoder", line: 17}
    ]
    return SemanticAssocIndexScope::line_is_impl_scope(annotations, 17)
'''
if compact(function_section(negative_text, "ordinary_annotation_marks_an_impl_scope")) != compact(expected_negative):
    raise SystemExit("rejected control must claim an ordinary annotation is an impl scope")

source_closure = source_include_closure([POSITIVE, NEGATIVE])
try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("impl-scope proof requires a strict proof build")

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
assert POSITIVE_NAMES | {"line_is_impl_scope", "line_is_impl_scope_from"} <= verified_positive

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert {(row["kind"], row["name"]) for row in negative["findings"]} == {
    ("ensure-unproven", name) for name in NEGATIVE_NAMES
}
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product

print(json.dumps({
    "admitted": True,
    "scope": "exact __impl_scope owner and source-line recognition",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(NEGATIVE_NAMES),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
