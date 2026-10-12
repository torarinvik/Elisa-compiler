"""Admit source-linked proofs of region-provenance merging across value paths."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve(strict=True)
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
POSITIVE = HERE / "region_escape_deeper_region.elisa"
NEGATIVE = HERE / "region_escape_deeper_region_rejected.elisa"
PROVENANCE = ROOT / "src/semantic/region_escape_provenance.elisa"
INTEGRATION = ROOT / "src/semantic/check_region_escape.elisa"
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")

if not __debug__:
    raise SystemExit("run without Python -O")

provenance_source = PROVENANCE.read_text()
helper_start = provenance_source.find("def region_escape_deeper_region(")
if helper_start < 0:
    raise SystemExit("production region provenance merge helper is missing")
next_helper = provenance_source.find("\n        def ", helper_start + len("def region_escape_deeper_region("))
helper_source = provenance_source[helper_start:next_helper if next_helper >= 0 else None]
compact_helper = "".join(helper_source.split())
source_rule = (
    "returnrightifright_position.foundand(notleft_position.foundor"
    "right_position.position>left_position.position)"
    "returnrightifleft==\"\"returnleft"
)
if source_rule not in compact_helper:
    raise SystemExit("region provenance merge rule changed without updating its proof")

# The helper is used to merge each match/catch arm and each aggregate/conditional
# branch, so the proof covers the production operation's high-risk call sites.
compact_source = "".join(provenance_source.split())
for required in (
    "arm_region<-region_escape_deeper_region(arm_region,candidate,nesting)",
    "result_region<-region_escape_deeper_region(result_region,candidate,nesting)",
    "returnregion_escape_deeper_region(then_region,else_region,nesting)",
):
    if required not in compact_source:
        raise SystemExit(f"region provenance aggregation lost a proved merge site: {required}")

integration = INTEGRATION.read_text()
if 'include "./region_escape_provenance.elisa"' not in integration:
    raise SystemExit("region checker no longer includes the proved provenance merge")
if "region_escape_stored_or_call_region(" not in integration:
    raise SystemExit("region checker no longer calls the source provenance analysis")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("region-provenance merge proof requires a strict proof build")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV", stage1_product,
          stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
          *source_include_closure([POSITIVE, NEGATIVE, INTEGRATION])]
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
assert positive == run(POSITIVE)[1], "proof report changed across repeated runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
expected = {
    "right_region_is_selected",
    "inner_right_region_dominates_outer_left",
    "local_right_region_dominates_untracked_left",
    "local_left_region_survives_untracked_right",
    "empty_left_region_is_filled_from_right",
}
assert expected <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert [(row["kind"], row["name"]) for row in negative["findings"]] == [
    ("ensure-unproven", "outer_left_region_can_hide_inner_right_region")]
assert require_current_product(BIN, PROVER) == manifest, "proof product changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "deepest-region provenance selection across branches, aggregates, match, and catch",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": ["outer_left_region_can_hide_inner_right_region"],
    "sources_sha256": hashes_before,
}, sort_keys=True))
