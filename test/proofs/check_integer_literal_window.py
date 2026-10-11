"""Replay the signed integer type-window proof against the production helper."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

from proof_product_gate import require_current_product


ROOT = Path(__file__).resolve().parents[2]
PROVER = ROOT.parent / "elisa-proof"
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
POSITIVE = HERE / "integer_literal_window.elisa"
NEGATIVE = HERE / "integer_literal_window_rejected.elisa"
HELPER = ROOT / "src/semantic/integer_literal_window.elisa"
CHECKER = ROOT / "src/semantic/check_literal_type_overflow.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
COMPILER_PIN = PROVER / "ELISA_COMPILER_REV"

if not __debug__:
    raise SystemExit("run without Python -O")
if not MANIFEST.is_file():
    raise SystemExit(f"missing proof build manifest: {MANIFEST}")

helper_text = HELPER.read_text()
checker_text = CHECKER.read_text()
if 'include "../../src/semantic/integer_literal_window.elisa"' not in POSITIVE.read_text():
    raise AssertionError("positive proof no longer includes the production helper")
if 'include "../../src/semantic/integer_literal_window.elisa"' not in NEGATIVE.read_text():
    raise AssertionError("negative proof no longer includes the production helper")
if "ensure result == (value >= low and value <= high)" not in helper_text:
    raise AssertionError("inclusive-window postcondition changed")
if "return value >= low and value <= high" not in helper_text:
    raise AssertionError("inclusive-window implementation changed")
if 'include "./integer_literal_window.elisa"' not in checker_text:
    raise AssertionError("semantic overflow checker no longer imports the proved helper")
if "not SemanticIntegerLiteral::value_fits_signed_window(value_literal.value, window.low, window.high)" not in checker_text:
    raise AssertionError("semantic overflow decision no longer uses the proved predicate")
if 'include "./check_literal_type_overflow.elisa"' not in SEMANTIC.read_text():
    raise AssertionError("semantic pass no longer includes the overflow checker")

positive_names = {
    "signed_value_fits_exactly_the_inclusive_window",
    "lower_endpoint_is_included",
    "upper_endpoint_is_included",
    "every_interior_value_is_included",
    "every_value_below_the_window_is_rejected",
    "every_value_above_the_window_is_rejected",
}
for name in positive_names:
    if f"def {name}(" not in POSITIVE.read_text():
        raise AssertionError(f"positive theorem missing: {name}")

try:
    product_manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if product_manifest.get("compile_mode") != "strict":
    raise SystemExit("integer-window proof requires a strict proof build")

stage1_product = Path(product_manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
INPUTS = [BIN, MANIFEST, MANIFEST_CHECKSUM, COMPILER_PIN, stage1_product,
          stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
          POSITIVE, NEGATIVE, HELPER, CHECKER, SEMANTIC]
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in INPUTS}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=60)
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
assert positive == run(POSITIVE)[1], "proof report changed across identical runs"
verified = {item["name"] for item in positive["declaration_details"] if item.get("verified")}
assert positive_names <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert negative["summary"]["proven"] + 4 == negative["summary"]["obligations"]
assert [(finding["kind"], finding["name"]) for finding in negative["findings"]] == [
    ("ensure-unproven", "lower_endpoint_is_excluded"),
    ("ensure-unproven", "upper_endpoint_is_excluded"),
    ("ensure-unproven", "a_value_below_the_window_fits"),
    ("ensure-unproven", "a_value_above_the_window_fits"),
]

assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in INPUTS}
assert require_current_product(BIN, PROVER) == product_manifest, "proof product provenance changed during replay"
print(json.dumps({"admitted": True, "scope": "inclusive signed integer range semantics and semantic overflow decision",
                  "positive_obligations": positive["summary"]["proven"],
                  "false_claims_rejected": [finding["name"] for finding in negative["findings"]],
                  "proof_binary_sha256": hashlib.sha256(BIN.read_bytes()).hexdigest(),
                  "proof_revision": product_manifest["proof"].get("head"),
                  "compiler_revision": product_manifest["compiler"].get("source_revision"),
                  "sources_sha256": hashes_before}, sort_keys=True))
