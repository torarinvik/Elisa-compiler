"""Replay boundary proofs for the production integer-literal decoder."""
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
POSITIVE = HERE / "parser_integer_literal_boundaries.elisa"
NEGATIVE = HERE / "parser_integer_literal_boundaries_rejected.elisa"
IMPLEMENTATION = ROOT / "src/parser/parser_integer_literal.elisa"
PARSER = ROOT / "src/parser/parser_expr.elisa"
COMPILER_PIN = PROVER / "ELISA_COMPILER_REV"

if not __debug__:
    raise SystemExit("run without Python -O")
if not MANIFEST.is_file():
    raise SystemExit(f"missing proof build manifest: {MANIFEST}")

source = IMPLEMENTATION.read_text()
parser_source = PARSER.read_text()
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()
if "def parse_int_literal_value(text: sview) -> i64:" not in source:
    raise AssertionError("production integer-literal decoder changed")
if 'include "../../src/parser/parser_integer_literal.elisa"' not in positive_text:
    raise AssertionError("positive proof no longer includes the production decoder")
if 'include "../../src/parser/parser_integer_literal.elisa"' not in negative_text:
    raise AssertionError("negative proof no longer includes the production decoder")
if "return parse_int_literal_value(text)" not in positive_text + negative_text:
    raise AssertionError("proof projection no longer delegates to the production decoder")
if 'include "./parser_integer_literal.elisa"' not in parser_source:
    raise AssertionError("production parser no longer includes the decoder")
if "result * base + digit.u64()" not in source or "maximum if result > (maximum - digit.u64()) / base" not in source:
    raise AssertionError("production decoder accumulation or overflow guard changed")

theorems = {
    "decimal_i64_max_is_preserved",
    "decimal_above_i64_max_reinterprets_as_i64_min",
    "hexadecimal_u64_max_reinterprets_as_i64_minus_one",
    "hexadecimal_u64_overflow_saturates_to_i64_minus_one",
    "hexadecimal_separators_preserve_the_value",
}
for name in theorems:
    if f"def {name}() -> bool:" not in positive_text:
        raise AssertionError(f"positive boundary proof missing: {name}")

try:
    product_manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if product_manifest.get("compile_mode") != "strict":
    raise SystemExit("integer-literal boundary proof requires a strict proof build")

stage1_product = Path(product_manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
INPUTS = [BIN, MANIFEST, MANIFEST_CHECKSUM, COMPILER_PIN, stage1_product,
          stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
          POSITIVE, NEGATIVE, IMPLEMENTATION, PARSER]
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
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert theorems <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert negative["summary"]["proven"] + 2 == negative["summary"]["obligations"]
assert [(finding["kind"], finding["name"]) for finding in negative["findings"]] == [
    ("ensure-unproven", "hexadecimal_u64_max_is_signed_i64_max"),
    ("ensure-unproven", "decimal_above_i64_max_remains_i64_max"),
]

assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in INPUTS}
assert require_current_product(BIN, PROVER) == product_manifest, "proof product provenance changed during replay"
print(json.dumps({"admitted": True, "scope": "integer-literal signed/unsigned boundaries and hexadecimal saturation",
                  "positive_obligations": positive["summary"]["proven"],
                  "false_claims_rejected": ["hexadecimal_u64_max_is_signed_i64_max",
                                            "decimal_above_i64_max_remains_i64_max"],
                  "proof_binary_sha256": hashlib.sha256(BIN.read_bytes()).hexdigest(),
                  "proof_revision": product_manifest["proof"].get("head"),
                  "compiler_revision": product_manifest["compiler"].get("source_revision"),
                  "sources_sha256": hashes_before}, sort_keys=True))
