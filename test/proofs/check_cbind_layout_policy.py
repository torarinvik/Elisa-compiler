"""Admit source-linked proofs for C binding and layout marker eligibility."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve(strict=True)
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
POLICY = ROOT / "src/semantic/cbind_layout_policy.elisa"
CHECKER = ROOT / "src/semantic/check_cbind_requires_c_layout.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
POSITIVE = HERE / "cbind_layout_policy.elisa"
NEGATIVE = HERE / "cbind_layout_policy_rejected.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    return "".join("".join(line.split()) for line in text.splitlines()
                   if not line.lstrip().startswith("#"))


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"^[ \t]*def {re.escape(name)}\(", source, re.MULTILINE))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    start = matches[0].start()
    following = re.search(r"^[ \t]*def [A-Za-z_][A-Za-z0-9_]*\(", source[matches[0].end():], re.MULTILINE)
    end = matches[0].end() + following.start() if following else len(source)
    return "\n".join(line for line in source[start:end].splitlines()
                      if not line.lstrip().startswith("#"))


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


policy_text = POLICY.read_text()
policy_shapes = {
    "is_named_c_bind": '''
def is_named_c_bind(annotation_name: sview, owner: sview) -> bool:
    ensure result == (annotation_name == "c_bind" and owner != "")
    return annotation_name == "c_bind" and owner != ""
''',
    "marker_belongs_to_owner": '''
def marker_belongs_to_owner(annotation_name: sview, annotation_owner: sview, owner: sview) -> bool:
    ensure result == (annotation_name == "__layout_c" and annotation_owner == owner)
    return annotation_name == "__layout_c" and annotation_owner == owner
''',
    "should_report_missing_layout": '''
def should_report_missing_layout(has_c_layout: bool) -> bool:
    ensure result == not has_c_layout
    return not has_c_layout
''',
}
for name, expected in policy_shapes.items():
    if compact(expected) not in compact(function_section(policy_text, name)):
        raise SystemExit(f"production C-layout policy {name} changed without updating its proof binding")

semantic_text = SEMANTIC.read_text()
if semantic_text.count('include "./cbind_layout_policy.elisa"') != 1:
    raise SystemExit("semantic facade must include the C-layout policy exactly once")
if semantic_text.count('include "./check_cbind_requires_c_layout.elisa"') != 1:
    raise SystemExit("semantic facade must include the C-bind checker exactly once")
if semantic_text.index('include "./cbind_layout_policy.elisa"') > semantic_text.index('include "./check_cbind_requires_c_layout.elisa"'):
    raise SystemExit("C-layout policy must be included before its semantic consumer")

checker_text = CHECKER.read_text()
layout_search = compact(function_section(checker_text, "cbind_struct_has_c_layout"))
if "returnanyannotationinannotationswhereCBindLayoutPolicy::marker_belongs_to_owner(annotation.name,annotation.owner,name)" not in layout_search:
    raise SystemExit("C-layout marker scan no longer delegates to the proved owner/name classifier")
consumer = compact(function_section(checker_text, "check_cbind_requires_c_layout"))
consumer_steps = (
    "for annotation in file.enum_annotations |table| -> table:",
    "if CBindLayoutPolicy::is_named_c_bind(annotation.name, annotation.owner) and CBindLayoutPolicy::should_report_missing_layout(cbind_struct_has_c_layout(file.enum_annotations, annotation.owner)):",
    'table.diagnostics <- table.diagnostics.push(Diagnostic{kind: DiagnosticKind.CBindRequiresCLayout, name: annotation.owner, line: annotation.line, expected: "", actual: ""})',
)
positions = [consumer.find(compact(step)) for step in consumer_steps]
if any(position < 0 for position in positions) or positions != sorted(positions):
    raise SystemExit("C-bind checker no longer applies the proved gate before emitting its layout diagnostic")

positive_names = {
    "c_bind_requires_a_named_owner",
    "c_layout_marker_requires_exact_name_and_owner",
    "missing_c_layout_is_reported",
    "present_c_layout_is_accepted",
    "c_layout_marker_on_same_owner_is_recognized",
    "different_layout_marker_is_not_c_layout",
    "marker_for_another_owner_is_not_a_match",
}
negative_names = {
    "an_unrelated_decorator_is_a_c_bind",
    "an_ownerless_c_bind_is_eligible",
    "an_soa_marker_is_a_c_layout_marker",
    "a_layout_marker_for_another_owner_matches",
    "a_present_c_layout_still_needs_a_diagnostic",
}
positive_shapes = {
    "c_bind_requires_a_named_owner": 'ensure result == (annotation_name == "c_bind" and owner != "") return CBindLayoutPolicy::is_named_c_bind(annotation_name, owner)',
    "c_layout_marker_requires_exact_name_and_owner": 'ensure result == (annotation_name == "__layout_c" and annotation_owner == owner) return CBindLayoutPolicy::marker_belongs_to_owner(annotation_name, annotation_owner, owner)',
    "missing_c_layout_is_reported": "ensure result == true return CBindLayoutPolicy::should_report_missing_layout(false)",
    "present_c_layout_is_accepted": "ensure result == true return not CBindLayoutPolicy::should_report_missing_layout(true)",
    "c_layout_marker_on_same_owner_is_recognized": 'ensure result == true return CBindLayoutPolicy::marker_belongs_to_owner("__layout_c", "Point", "Point")',
    "different_layout_marker_is_not_c_layout": 'ensure result == true return not CBindLayoutPolicy::marker_belongs_to_owner("__layout_soa", "Point", "Point")',
    "marker_for_another_owner_is_not_a_match": 'ensure result == true return not CBindLayoutPolicy::marker_belongs_to_owner("__layout_c", "Other", "Point")',
}
negative_shapes = {
    "an_unrelated_decorator_is_a_c_bind": 'ensure result == true return CBindLayoutPolicy::is_named_c_bind("align", "Point")',
    "an_ownerless_c_bind_is_eligible": 'ensure result == true return CBindLayoutPolicy::is_named_c_bind("c_bind", "")',
    "an_soa_marker_is_a_c_layout_marker": 'ensure result == true return CBindLayoutPolicy::marker_belongs_to_owner("__layout_soa", "Point", "Point")',
    "a_layout_marker_for_another_owner_matches": 'ensure result == true return CBindLayoutPolicy::marker_belongs_to_owner("__layout_c", "Other", "Point")',
    "a_present_c_layout_still_needs_a_diagnostic": "ensure result == true return CBindLayoutPolicy::should_report_missing_layout(true)",
}
for path, expected_names, shapes in (
    (POSITIVE, positive_names, positive_shapes),
    (NEGATIVE, negative_names, negative_shapes),
):
    source = path.read_text()
    if declarations(path) != expected_names:
        raise SystemExit(f"{path.name} proof inventory changed")
    if 'include "../../src/semantic/cbind_layout_policy.elisa"' not in source:
        raise SystemExit(f"{path.name} no longer imports the production C-layout policy")
    for name, shape in shapes.items():
        if compact(shape) not in compact(function_section(source, name)):
            raise SystemExit(f"{name} no longer proves its source-linked C-layout law")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("C-layout proof requires a strict proof build")
compiler = manifest["compiler"]
stage1_product = Path(compiler["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV",
    stage1_product, stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
    POLICY, CHECKER, SEMANTIC, POSITIVE, NEGATIVE,
    *source_include_closure([POSITIVE, NEGATIVE, SEMANTIC]),
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=60)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    assert report["trust"]["kernel_replayed_certificates"] == report["replay"]["replayed"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "C-layout proof report changed across identical runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert positive_names <= verified
assert set(policy_shapes) <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert {(row["kind"], row["name"]) for row in negative["findings"]} == {
    ("ensure-unproven", name) for name in negative_names
}
assert all(row["status"] == "disproved" and row["counterexample_found"]
           for row in negative["findings"])
assert require_current_product(BIN, PROVER) == manifest
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
print(json.dumps({
    "admitted": True,
    "scope": "named C-bind eligibility, owner-scoped layout(c) recognition, and missing-layout rejection",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(negative_names),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": compiler.get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
