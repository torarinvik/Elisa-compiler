"""Replay the lexer end-boundary proof against the production cursor helper."""
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
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
POSITIVE = HERE / "lexer_cursor_domain.elisa"
NEGATIVE = HERE / "lexer_cursor_domain_rejected.elisa"
HELPER = ROOT / "src/lexer/lexer_cursor_domain.elisa"
CORE = ROOT / "src/lexer/lexer_core.elisa"
FACADE = ROOT / "src/lexer/lexer.elisa"
TOKEN_SOURCE = ROOT / "src/lexer/tokens.elisa"
COMPILER_PIN = PROVER / "ELISA_COMPILER_REV"

if not __debug__:
    raise SystemExit("run without Python -O")
if not MANIFEST.is_file():
    raise SystemExit(f"missing proof build manifest: {MANIFEST}")

helper_text = HELPER.read_text()
core_text = CORE.read_text()
facade_text = FACADE.read_text()
proof_text = POSITIVE.read_text()
if 'include "./lexer_cursor_domain.elisa"' not in core_text:
    raise AssertionError("lexer core no longer imports the proved cursor predicate")
if 'include "./lexer_core.elisa"' not in facade_text:
    raise AssertionError("lexer facade no longer includes the production cursor checks")
if 'include "../../src/lexer/lexer_cursor_domain.elisa"' not in proof_text:
    raise AssertionError("proof no longer includes the production cursor predicate")
if "ensure result == (position >= source_length)" not in helper_text:
    raise AssertionError("cursor boundary postcondition changed")
if "return position >= source_length" not in helper_text:
    raise AssertionError("cursor boundary implementation changed")
if "ensure result == (lexer.position >= lexer.source_length)" not in core_text:
    raise AssertionError("lexer end-of-source contract changed")
if "return LexerCursorDomain::cursor_at_or_past_source_end(lexer.position, lexer.source_length)" not in core_text:
    raise AssertionError("lexer end-of-source no longer delegates to the proved helper")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("lexer cursor proof requires a strict proof build")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
INPUTS = [*source_include_closure([POSITIVE, NEGATIVE]), BIN, MANIFEST, MANIFEST_CHECKSUM, COMPILER_PIN, stage1_product,
          stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
          POSITIVE, NEGATIVE, HELPER, CORE, FACADE, TOKEN_SOURCE]
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
assert positive == run(POSITIVE)[1], "proof report changed across repeated runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
expected = {
    "cursor_at_or_past_source_end",
    "position_before_end_is_not_at_end",
    "position_at_end_is_at_end",
    "position_after_end_is_at_end",
    "end_predicate_matches_the_boundary_order",
}
assert expected <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["proven"] + 1 == negative["summary"]["obligations"]
assert [(finding["kind"], finding["name"]) for finding in negative["findings"]] == [
    ("ensure-unproven", "a_position_before_end_is_already_at_end")]
assert "a_position_before_end_is_already_at_end" not in {
    row["name"] for row in negative["declaration_details"] if row.get("verified")}

assert require_current_product(BIN, PROVER) == manifest, "proof-product provenance changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in INPUTS}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "lexer cursor end-boundary predicate and production call site",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": ["a_position_before_end_is_already_at_end"],
    "proof_binary_sha256": hashlib.sha256(BIN.read_bytes()).hexdigest(),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
