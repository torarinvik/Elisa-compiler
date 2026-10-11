"""Replay source-linked arithmetic cases for the integer-literal parser."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

from proof_product_gate import require_current_product

root = Path(__file__).resolve().parents[2]
prover = root.parent / "elisa-proof"
binary = Path(os.environ.get("ELISA_PROOF_BIN", str(prover / "build/elisa-proof"))).resolve(strict=True)
if not __debug__:
    raise SystemExit("run without Python -O")
try:
    product_manifest = require_current_product(binary, prover)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
compiler_head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                               check=True, capture_output=True, text=True).stdout.strip()
if compiler_head != product_manifest["compiler"]["source_revision"]:
    raise SystemExit("proof product was built from a different compiler revision")

here = Path(__file__).resolve().parent
manifest = binary.with_name(binary.name + ".manifest.json")
manifest_checksum = manifest.with_name(manifest.name + ".sha256")
inputs = [binary, manifest, manifest_checksum, prover / "ELISA_COMPILER_REV",
          here / "proof_product_gate.py", Path(__file__),
          root / "src/parser/parser_integer_literal.elisa",
          here / "parser_integer_literal.elisa",
          here / "parser_integer_literal_rejected.elisa"]
hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
source_text = (root / "src/parser/parser_integer_literal.elisa").read_text()
proof_text = (here / "parser_integer_literal.elisa").read_text()
rejected_text = (here / "parser_integer_literal_rejected.elisa").read_text()
assert "def parse_int_literal_value(text: sview) -> i64:" in source_text
assert 'include "../../src/parser/parser_integer_literal.elisa"' in proof_text
assert 'include "../../src/parser/parser_integer_literal.elisa"' in rejected_text
assert "return parse_int_literal_value(text)" in proof_text
assert "return parse_int_literal_value(text)" in rejected_text
assert "result * base + digit.u64()" in source_text and "maximum if result > (maximum - digit.u64()) / base" in source_text


def run(name):
    process = subprocess.run([str(binary), "--json", str(here / name)],
                             capture_output=True, text=True, timeout=30)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


code, report = run("parser_integer_literal.elisa")
assert code == 0 and report["status"] == report["verification_state"] == "proved"
assert report["summary"]["proven"] == report["summary"]["obligations"] > 0
assert not report["findings"]
assert report == run("parser_integer_literal.elisa")[1], "replay report changed across identical runs"
theorems = {
    "decimal_digits_decode",
    "decimal_separators_are_ignored",
    "lowercase_hex_decodes",
    "uppercase_hex_prefix_and_digits_decode",
    "full_width_u64_is_reinterpreted_as_i64",
    "overflow_saturates_instead_of_wrapping",
    "malformed_decimal_resets_to_zero",
    "malformed_hex_resets_to_zero",
}
verified = {item["name"] for item in report["declaration_details"] if item.get("verified")}
assert theorems <= verified

code, rejected = run("parser_integer_literal_rejected.elisa")
assert code == 1 and rejected["status"] == rejected["verification_state"] == "failed"
assert {finding["name"] for finding in rejected["findings"]} == {"hex_is_not_decimal"}
assert all(finding["kind"] == "ensure-unproven" for finding in rejected["findings"])
assert "hex_is_not_decimal" not in {item["name"] for item in rejected["declaration_details"] if item.get("verified")}

assert hashes == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(binary, prover) == product_manifest, "proof product or pinned source tree changed during replay"
assert subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                      check=True, capture_output=True, text=True).stdout.strip() == compiler_head
print(json.dumps({"admitted": True, "scope": "production integer-literal decoding examples",
                  "producer_proven": report["summary"]["proven"],
                  "independently_replayed": report["replay"]["replayed"],
                  "false_claim_rejected": "hex_is_not_decimal", "sources_sha256": hashes}))
