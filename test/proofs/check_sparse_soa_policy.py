"""Admit source-linked proofs for sparse enum SoA layout requirements."""
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
POLICY = ROOT / "src/semantic/sparse_soa_policy.elisa"
CHECKER = ROOT / "src/semantic/check_sparse_requires_soa.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
POSITIVE = HERE / "sparse_soa_policy.elisa"
NEGATIVE = HERE / "sparse_soa_policy_rejected.elisa"

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


policy_shapes = {
    "is_named_sparse_enum": '''
def is_named_sparse_enum(annotation_name: sview, owner: sview) -> bool:
    ensure result == (annotation_name == "__layout_sparse" and owner != "")
    return annotation_name == "__layout_sparse" and owner != ""
''',
    "soa_marker_belongs_to_owner": '''
def soa_marker_belongs_to_owner(annotation_name: sview, annotation_owner: sview, owner: sview) -> bool:
    ensure result == (annotation_name == "__layout_soa" and annotation_owner == owner)
    return annotation_name == "__layout_soa" and annotation_owner == owner
''',
    "should_report_missing_soa": '''
def should_report_missing_soa(has_soa: bool) -> bool:
    ensure result == not has_soa
    return not has_soa
''',
}
policy_text = POLICY.read_text()
for name, expected in policy_shapes.items():
    if compact(expected) not in compact(function_section(policy_text, name)):
        raise SystemExit(f"production sparse-SoA policy {name} changed without updating its proof binding")

semantic_text = SEMANTIC.read_text()
if semantic_text.count('include "./sparse_soa_policy.elisa"') != 1:
    raise SystemExit("semantic facade must include the sparse-SoA policy exactly once")
if semantic_text.count('include "./check_sparse_requires_soa.elisa"') != 1:
    raise SystemExit("semantic facade must include the sparse layout checker exactly once")
if semantic_text.index('include "./sparse_soa_policy.elisa"') > semantic_text.index('include "./check_sparse_requires_soa.elisa"'):
    raise SystemExit("sparse-SoA policy must be included before its semantic consumer")

checker_text = CHECKER.read_text()
layout_search = compact(function_section(checker_text, "sparse_enum_has_soa"))
if "returnanyannotationinannotationswhereSparseSoaPolicy::soa_marker_belongs_to_owner(annotation.name,annotation.owner,name)" not in layout_search:
    raise SystemExit("SoA marker scan no longer delegates to the proved enum-owner classifier")
consumer = compact(function_section(checker_text, "check_sparse_requires_soa"))
consumer_steps = (
    "for annotation in file.enum_annotations |table| -> table:",
    "if SparseSoaPolicy::is_named_sparse_enum(annotation.name, annotation.owner) and SparseSoaPolicy::should_report_missing_soa(sparse_enum_has_soa(file.enum_annotations, annotation.owner)):",
    'table.diagnostics <- table.diagnostics.push(Diagnostic{kind: DiagnosticKind.SparseRequiresSoa, name: annotation.owner, line: annotation.line, expected: "", actual: ""})',
)
positions = [consumer.find(compact(step)) for step in consumer_steps]
if any(position < 0 for position in positions) or positions != sorted(positions):
    raise SystemExit("sparse layout checker no longer applies the proved gate before emitting its diagnostic")

positive_names = {
    "sparse_enum_eligibility_is_exact",
    "soa_marker_recognition_is_owner_scoped",
    "missing_soa_marker_is_reported",
    "present_soa_marker_is_accepted",
    "soa_marker_on_same_enum_is_recognized",
    "ordinary_layout_marker_is_not_sparse",
    "marker_for_another_enum_does_not_satisfy_the_requirement",
}
negative_names = {
    "an_aos_enum_is_sparse",
    "an_ownerless_sparse_annotation_is_eligible",
    "a_c_layout_marker_satisfies_the_soa_requirement",
    "a_marker_for_another_enum_satisfies_the_requirement",
    "a_present_soa_marker_should_be_reported_missing",
}
positive_shapes = {
    "sparse_enum_eligibility_is_exact": 'ensure result == (annotation_name == "__layout_sparse" and owner != "") return SparseSoaPolicy::is_named_sparse_enum(annotation_name, owner)',
    "soa_marker_recognition_is_owner_scoped": 'ensure result == (annotation_name == "__layout_soa" and annotation_owner == owner) return SparseSoaPolicy::soa_marker_belongs_to_owner(annotation_name, annotation_owner, owner)',
    "missing_soa_marker_is_reported": "ensure result == true return SparseSoaPolicy::should_report_missing_soa(false)",
    "present_soa_marker_is_accepted": "ensure result == true return not SparseSoaPolicy::should_report_missing_soa(true)",
    "soa_marker_on_same_enum_is_recognized": 'ensure result == true return SparseSoaPolicy::soa_marker_belongs_to_owner("__layout_soa", "Payload", "Payload")',
    "ordinary_layout_marker_is_not_sparse": 'ensure result == true return not SparseSoaPolicy::is_named_sparse_enum("__layout_aos", "Payload")',
    "marker_for_another_enum_does_not_satisfy_the_requirement": 'ensure result == true return not SparseSoaPolicy::soa_marker_belongs_to_owner("__layout_soa", "Other", "Payload")',
}
negative_shapes = {
    "an_aos_enum_is_sparse": 'ensure result == true return SparseSoaPolicy::is_named_sparse_enum("__layout_aos", "Payload")',
    "an_ownerless_sparse_annotation_is_eligible": 'ensure result == true return SparseSoaPolicy::is_named_sparse_enum("__layout_sparse", "")',
    "a_c_layout_marker_satisfies_the_soa_requirement": 'ensure result == true return SparseSoaPolicy::soa_marker_belongs_to_owner("__layout_c", "Payload", "Payload")',
    "a_marker_for_another_enum_satisfies_the_requirement": 'ensure result == true return SparseSoaPolicy::soa_marker_belongs_to_owner("__layout_soa", "Other", "Payload")',
    "a_present_soa_marker_should_be_reported_missing": "ensure result == true return SparseSoaPolicy::should_report_missing_soa(true)",
}
for path, expected_names, shapes in (
    (POSITIVE, positive_names, positive_shapes),
    (NEGATIVE, negative_names, negative_shapes),
):
    source = path.read_text()
    if declarations(path) != expected_names:
        raise SystemExit(f"{path.name} proof inventory changed")
    if 'include "../../src/semantic/sparse_soa_policy.elisa"' not in source:
        raise SystemExit(f"{path.name} no longer imports the production sparse-SoA policy")
    for name, shape in shapes.items():
        if compact(shape) not in compact(function_section(source, name)):
            raise SystemExit(f"{name} no longer proves its source-linked sparse layout law")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("sparse-SoA proof requires a strict proof build")
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
assert positive == run(POSITIVE)[1], "sparse-SoA proof report changed across identical runs"
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
    "scope": "sparse enum eligibility, owner-scoped SoA marker recognition, and missing-SoA rejection",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(negative_names),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": compiler.get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
