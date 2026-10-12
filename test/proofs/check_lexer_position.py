"""Replay the lexer-position constructor proof with an exact Elisa-proof product."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
PROVER = ROOT.parent / "elisa-proof"
BIN = Path(os.environ.get("ELISA_PROOF_BIN", str(PROVER / "build/elisa-proof"))).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
HERE = Path(__file__).resolve().parent
POSITIVE = HERE / "lexer_position.elisa"
NEGATIVE = HERE / "lexer_position_rejected.elisa"
SOURCES = [ROOT / "src/lexer/lexer.elisa", ROOT / "src/lexer/tokens.elisa",
           ROOT / "src/lexer/lexer_position.elisa", POSITIVE, NEGATIVE]

if not __debug__:
    raise SystemExit("run without Python -O")
if not MANIFEST.is_file():
    raise SystemExit(f"missing proof build manifest: {MANIFEST}")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error

disk_manifest = json.loads(MANIFEST.read_text())
if disk_manifest != manifest:
    raise SystemExit("proof manifest changed during initial admission")
binary_digest = hashlib.sha256(BIN.read_bytes()).hexdigest()
if manifest.get("binary", {}).get("sha256") != binary_digest:
    raise SystemExit("proof executable does not match its build manifest")
if manifest.get("compile_mode") != "strict":
    raise SystemExit("lexer position proof requires a strict proof build")

stale_sources = [path for path in (PROVER / "src").rglob("*.elisa")
                 if path.stat().st_mtime_ns > BIN.stat().st_mtime_ns]
if stale_sources:
    raise SystemExit(f"proof executable is stale; rebuild after {stale_sources[0]}")

inputs = [BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
          PROVER / "ELISA_COMPILER_REV", Path(__file__).with_name("proof_product_gate.py"),
          Path(__file__), *SOURCES]
inputs.extend(source_include_closure([POSITIVE, NEGATIVE]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=30)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["proven"] == positive["summary"]["obligations"] == 10
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "proof report changed across repeated runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert {"LexerPosition", "position_preserves_line", "position_preserves_column",
        "position_preserves_offset"} <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["proven"] + 1 == negative["summary"]["obligations"]
assert [(finding["kind"], finding["name"]) for finding in negative["findings"]] == [
    ("ensure-unproven", "position_does_not_swap_line_and_column")]
assert not {"position_does_not_swap_line_and_column"} & {
    row["name"] for row in negative["declaration_details"] if row.get("verified")}

hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
try:
    manifest_after = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance changed during replay: {error}") from error
assert manifest_after == manifest, "proof product manifest changed during replay"
print(json.dumps({"admitted": True, "scope": "LexerPosition constructor field preservation",
                  "positive_obligations": positive["summary"]["proven"],
                  "negative_claims_rejected": ["position_does_not_swap_line_and_column"],
                  "proof_binary_sha256": binary_digest,
                  "proof_revision": manifest["proof"].get("head"),
                  "compiler_revision": manifest["compiler"].get("source_revision"),
                  "source_sha256": hashes_before}, sort_keys=True))
