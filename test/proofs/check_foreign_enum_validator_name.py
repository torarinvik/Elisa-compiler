"""Admit the proof of the sole foreign-enum validator naming exception."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
PROVER = ROOT.parent / "elisa-proof"
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
HELPER = ROOT / "src/semantic/foreign_enum_validator_name.elisa"
CHECK = ROOT / "src/semantic/check_extern_enum.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
POSITIVE = HERE / "foreign_enum_validator_name.elisa"
NEGATIVE = HERE / "foreign_enum_validator_name_rejected.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")

helper_text = HELPER.read_text()
check_text = CHECK.read_text()
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()
if 'include "../../src/semantic/foreign_enum_validator_name.elisa"' not in positive_text:
    raise SystemExit("positive proof no longer imports the production validator-name predicate")
if 'include "./foreign_enum_validator_name.elisa"' not in negative_text:
    raise SystemExit("negative controls no longer import the positive source-linked proof")
if 'include "./foreign_enum_validator_name.elisa"' not in check_text:
    raise SystemExit("foreign-enum check no longer imports the isolated production predicate")
if 'include "./check_extern_enum.elisa"' not in SEMANTIC.read_text():
    raise SystemExit("foreign-enum check is no longer included by the production semantic layer")
if "ForeignEnumName::is_validator_of(function_name, name)" not in check_text:
    raise SystemExit("foreign-enum check no longer uses the proved validator-name predicate")
if "ensure result == (" not in helper_text or "forall prefix_index in 0..<enum_name.len:" not in helper_text:
    raise SystemExit("production predicate no longer contracts exact prefix and suffix identity")
if "invariant forall prefix_index in 0..<index:" not in helper_text:
    raise SystemExit("production prefix loop is missing its byte-prefix invariant")
if "invariant forall suffix_probe in 0..<suffix_index:" not in helper_text:
    raise SystemExit("production suffix loop is missing its byte-prefix invariant")

positive_names = {
    "is_validator_of",
    "validator_name_predicate_matches_prefix_and_suffix_spec",
    "synthesized_validator_name_is_recognized",
    "validator_suffix_is_recognized_for_empty_prefix",
}
for name in positive_names:
    if f"def {name}(" not in positive_text and f"def {name}(" not in helper_text:
        raise SystemExit(f"positive theorem missing: {name}")
negative_names = {
    "capitalization_change_in_the_validator_suffix_is_accepted",
    "a_different_enum_prefix_is_accepted",
    "an_extra_suffix_byte_is_accepted",
}
for name in negative_names:
    if f"def {name}(" not in negative_text:
        raise SystemExit(f"negative control missing: {name}")

try:
    product_manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product_manifest.get("compile_mode") != "strict":
    raise SystemExit("foreign-enum validator proof requires a strict proof build")
compiler_head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                               check=True, capture_output=True, text=True).stdout.strip()
if compiler_head != product_manifest["compiler"]["source_revision"]:
    raise SystemExit("proof product was built from a different compiler revision")

stage1_product = Path(product_manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [
    BIN,
    MANIFEST,
    MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV",
    stage1_product,
    stage1_provenance,
    Path(__file__),
    HERE / "proof_product_gate.py",
    POSITIVE,
    NEGATIVE,
    HELPER,
    CHECK,
    SEMANTIC,
]
inputs.extend(source_include_closure([POSITIVE, NEGATIVE]))
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
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "foreign-enum validator proof changed across repeated runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert positive_names <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert negative["summary"]["proven"] + len(negative_names) == negative["summary"]["obligations"]
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert not negative_names & {row["name"] for row in negative["declaration_details"] if row.get("verified")}

assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product_manifest
print(json.dumps({
    "admitted": True,
    "scope": "the exact enum-name + __from_c validator exception",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(negative_names),
    "proof_revision": product_manifest["proof"].get("head"),
    "compiler_revision": product_manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
