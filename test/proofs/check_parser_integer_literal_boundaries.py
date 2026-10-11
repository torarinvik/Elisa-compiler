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
if ("result * base + digit.u64()" not in source or
        "maximum if result > (maximum - digit.u64()) / base" not in source or
        "base: u64 = 16 if is_hex else 10" not in source):
    raise AssertionError("production decoder accumulation or overflow guard changed")
for fragment in (
    "(is_hex and sview_at(text, index) >= 97 and sview_at(text, index) <= 102)",
    "(is_hex and sview_at(text, index) >= 65 and sview_at(text, index) <= 70)",
    "(sview_at(text, index) - 97 + 10).i64()",
    "(sview_at(text, index) - 65 + 10).i64()",
):
    if fragment not in source:
        raise AssertionError(f"production hexadecimal decoder lost a digit class or mapping: {fragment}")

theorems = {
    "decimal_i64_max_is_preserved",
    "decimal_above_i64_max_reinterprets_as_i64_min",
    "hexadecimal_u64_max_reinterprets_as_i64_minus_one",
    "hexadecimal_u64_overflow_saturates_to_i64_minus_one",
    "hexadecimal_separators_preserve_the_value",
    "every_single_ascii_decimal_digit_decodes_exactly",
    "every_two_ascii_decimal_digits_decode_exactly",
    "every_two_ascii_hex_digits_decode_exactly",
    "every_hex_decimal_digit_decodes_exactly",
    "every_lowercase_hex_letter_decodes_exactly",
    "every_uppercase_hex_letter_decodes_exactly",
}
for name in theorems:
    if f"def {name}(" not in positive_text:
        raise AssertionError(f"positive boundary proof missing: {name}")
hex_digit_spec = positive_text.split("def proof_hex_digit_value(", 1)[1].split("\ndef ", 1)[0]
for fragment in ("byte - 48", "byte - 87", "byte - 55"):
    if fragment not in hex_digit_spec:
        raise AssertionError(f"independent hexadecimal digit specification lost mapping: {fragment}")
if "ensure result == ((byte - 48).i64() if byte >= 48 and byte <= 57 else (byte - 87).i64() if byte >= 97 and byte <= 102 else (byte - 55).i64())" not in hex_digit_spec:
    raise AssertionError("independent hexadecimal digit mapping no longer has its exact contract")
hex_pair = positive_text.split("def every_two_ascii_hex_digits_decode_exactly(", 1)[1].split("\ndef ", 1)[0]
for fragment in ("sview_at(text, 2)", "sview_at(text, 3)", "* 16", "proof_hex_digit_value"):
    if fragment not in hex_pair:
        raise AssertionError(f"universal two-digit hex proof lost a byte or radix case: {fragment}")
hex_pair_requires = hex_pair.split("requires ", 1)[1].split("\n", 1)[0]
for fragment in (
    "sview_len(text) == 4",
    "sview_at(text, 0) == 48",
    "sview_at(text, 1) == 120 or sview_at(text, 1) == 88",
):
    if fragment not in hex_pair_requires:
        raise AssertionError(f"universal two-digit hex precondition omits its literal prefix: {fragment}")
for index in (2, 3):
    for fragment in (
        f"sview_at(text, {index}) >= 48 and sview_at(text, {index}) <= 57",
        f"sview_at(text, {index}) >= 97 and sview_at(text, {index}) <= 102",
        f"sview_at(text, {index}) >= 65 and sview_at(text, {index}) <= 70",
    ):
        if fragment not in hex_pair_requires:
            raise AssertionError(f"universal two-digit hex precondition omits a digit class: {fragment}")
if "ensure Parser::proof_decode_integer_literal_boundary(text) == (proof_hex_digit_value(sview_at(text, 2)) * 16 + proof_hex_digit_value(sview_at(text, 3)))" not in hex_pair:
    raise AssertionError("universal two-digit hex theorem no longer states the exact radix-16 result")

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
assert negative["summary"]["proven"] + 6 == negative["summary"]["obligations"]
assert [(finding["kind"], finding["name"]) for finding in negative["findings"]] == [
    ("ensure-unproven", "hexadecimal_u64_max_is_signed_i64_max"),
    ("ensure-unproven", "decimal_above_i64_max_remains_i64_max"),
    ("ensure-unproven", "ascii_zero_decodes_as_one"),
    ("ensure-unproven", "hexadecimal_lowercase_a_decodes_as_eleven"),
    ("ensure-unproven", "decimal_zero_pair_decodes_as_one"),
    ("ensure-unproven", "hexadecimal_zero_pair_decodes_as_one"),
]
hex_false_claim = negative_text.split("def hexadecimal_zero_pair_decodes_as_one(", 1)[1].split("\ndef ", 1)[0]
if "ensure Parser::proof_decode_integer_literal_boundary(text) == 1" not in hex_false_claim:
    raise AssertionError("hexadecimal two-digit negative control no longer claims the known false result")

assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in INPUTS}
assert require_current_product(BIN, PROVER) == product_manifest, "proof product provenance changed during replay"
print(json.dumps({"admitted": True, "scope": "universal one- and two-digit decimal and hexadecimal decoding, signed boundaries, and saturation",
                  "positive_obligations": positive["summary"]["proven"],
                  "false_claims_rejected": ["hexadecimal_u64_max_is_signed_i64_max",
                                            "decimal_above_i64_max_remains_i64_max",
                                            "ascii_zero_decodes_as_one",
                                            "hexadecimal_lowercase_a_decodes_as_eleven",
                                            "decimal_zero_pair_decodes_as_one",
                                            "hexadecimal_zero_pair_decodes_as_one"],
                  "proof_binary_sha256": hashlib.sha256(BIN.read_bytes()).hexdigest(),
                  "proof_revision": product_manifest["proof"].get("head"),
                  "compiler_revision": product_manifest["compiler"].get("source_revision"),
                  "sources_sha256": hashes_before}, sort_keys=True))
