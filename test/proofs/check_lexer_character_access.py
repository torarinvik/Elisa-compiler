"""Replay the source-linked proof for the lexer's bounded character accessor."""
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
POSITIVE = HERE / "lexer_character_access.elisa"
NEGATIVE = HERE / "lexer_character_access_rejected.elisa"
HELPER = ROOT / "src/lexer/lexer_character_access.elisa"
STRINGS = ROOT / "src/lexer/lexer_strings.elisa"
FACADE = ROOT / "src/lexer/lexer.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")

helper_text = HELPER.read_text()
strings_text = STRINGS.read_text()
facade_text = FACADE.read_text()
if 'include "../../src/lexer/lexer_character_access.elisa"' not in POSITIVE.read_text():
    raise SystemExit("positive proof no longer includes the production byte selector")
if 'include "./lexer_character_access.elisa"' not in NEGATIVE.read_text():
    raise SystemExit("negative control no longer includes the production byte selector")
if 'include "./lexer_character_access.elisa"' not in facade_text:
    raise SystemExit("lexer facade no longer includes the proved byte selector")
if "return lexer_byte_or_sentinel(byte, source_length, index, 0).char()" not in strings_text:
    raise SystemExit("Lexer.char_at no longer delegates its sentinel choice to the proved byte selector")
guard = "sentinel return if index >= source_length"
guarded_read = "if index < source_length:\n                byte <- source[index]"
if "byte: mutable u8 = 0" not in strings_text or guarded_read not in strings_text:
    raise SystemExit("Lexer.char_at no longer guards its only source load with the source length")
if "ensure index >= source_length implies result == sentinel" not in helper_text or "ensure index < source_length implies result == byte" not in helper_text:
    raise SystemExit("byte selector contract no longer states both exact range branches")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("lexer character-access proof requires a strict proof build")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [
    BIN,
    MANIFEST,
    MANIFEST_CHECKSUM,
    PROVER / "ELISA_COMPILER_REV",
    stage1_product,
    stage1_provenance,
    Path(__file__),
    HERE / "proof_product_gate.py",
    POSITIVE,
    NEGATIVE,
    HELPER,
    STRINGS,
    FACADE,
]
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


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
expected = {
    "lexer_byte_or_sentinel",
    "exactly_at_source_end_returns_the_sentinel",
    "beyond_source_end_returns_the_sentinel",
    "in_range_access_preserves_the_selected_byte",
}
assert expected <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert negative["summary"]["proven"] + 1 == negative["summary"]["obligations"]
assert [(finding["kind"], finding["name"]) for finding in negative["findings"]] == [
    ("ensure-unproven", "out_of_range_access_returns_a_non_sentinel_byte")
]

assert require_current_product(BIN, PROVER) == manifest, "proof-product provenance changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "exact byte-or-sentinel selection at and beyond the boundary, plus a source-structure check that the raw-pointer load is guarded",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": ["out_of_range_access_returns_a_non_sentinel_byte"],
    "proof_binary_sha256": hashlib.sha256(BIN.read_bytes()).hexdigest(),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
