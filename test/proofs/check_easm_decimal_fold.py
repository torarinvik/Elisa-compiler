"""Replay sequence-level safety proofs for EASM signed decimal accumulation."""
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
POSITIVE = HERE / "easm_decimal_fold.elisa"
NEGATIVE = HERE / "easm_decimal_fold_rejected.elisa"
HELPER = ROOT / "src/backend/easm_checked_decimal.elisa"
PARSER = ROOT / "src/backend/easm_verify_function.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")

positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()
helper_text = HELPER.read_text()
parser_text = PARSER.read_text()
parser_body = parser_text.split("def easm_parse_i64(text: sview) -> i64:", 1)[1].split(
    "def easm_type_width(", 1
)[0]
if 'include "../../src/backend/easm_checked_decimal.elisa"' not in positive_text:
    raise SystemExit("sequence proof no longer includes the production checked-digit helper")
for helper in ("append_positive_digit", "append_negative_digit"):
    if f"def {helper}(" not in helper_text or f"EasmCheckedDecimal::{helper}(value, digit)" not in positive_text:
        raise SystemExit(f"sequence fold no longer uses the production {helper} helper")
loop_start = parser_body.find("while position < sview_len(text)")
loop_end = parser_body.find("return value", loop_start)
if loop_start < 0 or loop_end < 0:
    raise SystemExit("signed decimal parser no longer has a bounded digit loop")
loop_body = parser_body[loop_start:loop_end]
if "EasmCheckedDecimal::append_positive_digit(value, digit)" not in loop_body:
    raise SystemExit("positive parser path no longer uses the proved checked-digit helper")
if "EasmCheckedDecimal::append_negative_digit(value, digit)" not in loop_body:
    raise SystemExit("negative parser path no longer uses the proved checked-digit helper")
for fragment in (
    "byte: u8 = sview_at(text, position)",
    "return 0 if byte < EasmCheckedDecimal::ASCII_DIGIT_ZERO or byte > EasmCheckedDecimal::ASCII_DIGIT_NINE",
    "digit: i64 = (byte - EasmCheckedDecimal::ASCII_DIGIT_ZERO).i64()",
):
    if fragment not in loop_body:
        raise SystemExit(f"parser digit loop no longer matches the checked-fold model: {fragment}")
for helper in ("append_positive_digit", "append_negative_digit"):
    call = f"EasmCheckedDecimal::{helper}(value, digit)"
    call_at = loop_body.index(call)
    reject_at = loop_body.index("return 0 if not step.valid", call_at)
    update_at = loop_body.index("value <- step.value", reject_at)
    advance_at = loop_body.index("position <- position + 1", update_at)
    if not call_at < reject_at < update_at < advance_at:
        raise SystemExit(f"parser does not reject failed {helper} steps before updating its accumulator")

positive_names = {
    "fold_positive_decimal_digits",
    "fold_negative_decimal_digits",
    "positive_decimal_fold_accepts_exact_i64_max",
    "negative_decimal_fold_accepts_exact_i64_min",
    "positive_decimal_fold_rejects_one_past_i64_max",
    "negative_decimal_fold_rejects_one_below_i64_min",
}
for name in positive_names:
    if f"def {name}(" not in positive_text:
        raise SystemExit(f"positive theorem missing: {name}")
negative_names = {
    "positive_decimal_fold_accepts_one_past_i64_max",
    "negative_decimal_fold_accepts_one_below_i64_min",
}
for name in negative_names:
    if f"def {name}(" not in negative_text:
        raise SystemExit(f"negative control missing: {name}")

try:
    product_manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product_manifest.get("compile_mode") != "strict":
    raise SystemExit("decimal-fold proof requires a strict proof build")
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
    PARSER,
]
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
assert positive == run(POSITIVE)[1], "decimal-fold report changed across repeated runs"
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
    "scope": "arbitrary repeated decimal accumulation stays within exact signed i64 bounds",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(negative_names),
    "proof_revision": product_manifest["proof"].get("head"),
    "compiler_revision": product_manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
