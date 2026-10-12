"""Admit source-linked proofs for default-parameter reference diagnostics."""
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
POLICY = ROOT / "src/semantic/default_param_ref_policy.elisa"
CHECKER = ROOT / "src/semantic/check_default_param_ref.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
POSITIVE = HERE / "default_param_ref_policy.elisa"
NEGATIVE = HERE / "default_param_ref_policy_rejected.elisa"

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


policy_body = compact(function_section(POLICY.read_text(), "should_report"))
expected_policy = compact('''
def should_report(owner: sview, name: sview, name_is_indexed: bool) -> bool:
    ensure result == (owner == "__default_param_ref" and name != "" and not name_is_indexed)
    return owner == "__default_param_ref" and name != "" and not name_is_indexed
''')
if policy_body != expected_policy:
    raise SystemExit("default-parameter report policy changed without updating its proof binding")

semantic_text = SEMANTIC.read_text()
policy_include = 'include "./default_param_ref_policy.elisa"'
checker_include = 'include "./check_default_param_ref.elisa"'
if semantic_text.count(policy_include) != 1 or semantic_text.count(checker_include) != 1:
    raise SystemExit("semantic facade must include the policy and its consumer exactly once")
if semantic_text.index(policy_include) > semantic_text.index(checker_include):
    raise SystemExit("default-parameter report policy must precede its semantic consumer")

checker_body = compact(function_section(CHECKER.read_text(), "check_default_param_ref"))
consumer_steps = (
    "for annotation in file.enum_annotations |table| -> table:",
    "if DefaultParamRefPolicy::should_report(annotation.owner, annotation.name, name_indexed(table, annotation.name)):",
    'table.diagnostics <- table.diagnostics.push(Diagnostic{kind: DiagnosticKind.UndefinedName, name: annotation.name, line: annotation.line, expected: "", actual: ""})',
)
consumer_positions = [checker_body.find(compact(step)) for step in consumer_steps]
if any(position < 0 for position in consumer_positions) or consumer_positions != sorted(consumer_positions):
    raise SystemExit("default-parameter checker no longer reports only the proved policy's unresolved references")

positive_names = {
    "default_param_ref_report_predicate_is_exact",
    "unresolved_default_parameter_name_is_reported",
    "globally_indexed_name_is_not_reported",
    "empty_reference_name_is_not_reported",
    "other_annotation_owner_is_not_reported",
}
negative_names = {
    "a_globally_indexed_default_reference_is_reported",
    "an_ordinary_annotation_owner_is_reported",
    "an_empty_default_reference_name_is_reported",
}
positive_shapes = {
    "default_param_ref_report_predicate_is_exact": 'ensure result == (owner == "__default_param_ref" and name != "" and not name_is_indexed) return DefaultParamRefPolicy::should_report(owner, name, name_is_indexed)',
    "unresolved_default_parameter_name_is_reported": 'ensure result == true return DefaultParamRefPolicy::should_report("__default_param_ref", "x", false)',
    "globally_indexed_name_is_not_reported": 'ensure result == true return not DefaultParamRefPolicy::should_report("__default_param_ref", "global_value", true)',
    "empty_reference_name_is_not_reported": 'ensure result == true return not DefaultParamRefPolicy::should_report("__default_param_ref", "", false)',
    "other_annotation_owner_is_not_reported": 'ensure result == true return not DefaultParamRefPolicy::should_report("ordinary_annotation", "x", false)',
}
negative_shapes = {
    "a_globally_indexed_default_reference_is_reported": 'ensure result == true return DefaultParamRefPolicy::should_report("__default_param_ref", "global_value", true)',
    "an_ordinary_annotation_owner_is_reported": 'ensure result == true return DefaultParamRefPolicy::should_report("ordinary_annotation", "x", false)',
    "an_empty_default_reference_name_is_reported": 'ensure result == true return DefaultParamRefPolicy::should_report("__default_param_ref", "", false)',
}
for path, expected, shapes in (
    (POSITIVE, positive_names, positive_shapes),
    (NEGATIVE, negative_names, negative_shapes),
):
    source = path.read_text()
    if declarations(path) != expected:
        raise SystemExit(f"{path.name} theorem inventory changed")
    if 'include "../../src/semantic/default_param_ref_policy.elisa"' not in source:
        raise SystemExit(f"{path.name} must import the production report predicate")
    for name, expected_shape in shapes.items():
        if compact(expected_shape) not in compact(function_section(source, name)):
            raise SystemExit(f"{name} no longer states its exact source-linked law")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("default-parameter reference proof requires a strict proof build")
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
assert positive == run(POSITIVE)[1], "default-parameter proof report changed across identical runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert positive_names <= verified
assert "should_report" in verified

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
    "scope": "default-parameter marker, nonempty name, global-name exemption, and UndefinedName dispatch",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(negative_names),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": compiler.get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
