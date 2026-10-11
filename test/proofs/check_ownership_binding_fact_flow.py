"""Admit direct proofs of the source BindingId fact join and consume operations."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
from proof_product_gate import require_current_product

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PROVER = ROOT.parent / "elisa-proof"
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
if not __debug__:
    raise SystemExit("run without Python -O")
try:
    product_manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error

proof = HERE / "ownership_binding_fact_flow.elisa"
rejected = HERE / "ownership_binding_fact_flow_rejected.elisa"
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
semantic_sources = [ROOT / "src/semantic/binding_identity_types.elisa",
                    ROOT / "src/semantic/ownership_flow_domain.elisa",
                    ROOT / "src/semantic/ownership_binding_flow.elisa"]
inputs = [BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV",
          HERE / "proof_product_gate.py", Path(__file__), proof, rejected, *semantic_sources]
hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path):
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=60)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


code, positive = run(proof)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
assert not positive["findings"]
assert positive == run(proof)[1], "proof report changed across repeats"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
expected_positive = {"matching_binding_join_is_componentwise", "foreign_left_binding_is_rejected",
                     "foreign_right_binding_is_rejected", "foreign_left_serial_is_rejected",
                     "foreign_right_serial_is_rejected", "invalid_identity_join_is_rejected",
                     "eligible_binding_is_consumed_once", "arbitrary_binding_fact_cannot_be_accepted_twice",
                     "failed_consumption_preserves_every_fact",
                     "unreachable_binding_cannot_be_consumed", "unknown_binding_cannot_be_consumed",
                     "invalid_owner_cannot_be_consumed"}
assert expected_positive <= verified
assert all(row.get("verified") for row in positive["declaration_details"] if row["kind"] == "function")

code, negative = run(rejected)
expected_false = {"foreign_binding_can_join_as_known", "foreign_serial_binding_can_join_as_known",
                  "foreign_right_serial_binding_can_join_as_known", "foreign_fact_can_replace_join_target",
                  "consumed_binding_can_be_consumed_again", "arbitrary_binding_fact_can_be_accepted_twice"}
assert code == 1 and negative["status"] == "failed"
assert {row["name"] for row in negative["findings"]} == expected_false
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert not expected_false & {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert hashes == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product_manifest, "proof product or source tree changed during replay"
print(json.dumps({"admitted": True,
                  "scope": "BindingId-indexed fact joins and one-shot consume only; not CFG discovery or ownership legality",
                  "positive_obligations": positive["summary"]["proven"],
                  "independently_replayed": positive["replay"]["replayed"],
                  "false_claims_rejected": sorted(expected_false),
                  "sources_sha256": hashes}))
