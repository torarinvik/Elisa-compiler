"""Admit source-linked identity laws only with complete independent replay."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[2]
prover = root.parent / "wasmbrowser-proof"
binary = Path(os.environ.get("ELISA_PROOF_BIN", str(prover / "build/elisa-proof-ownership-flow")))
if not __debug__:
    raise SystemExit("run without Python -O")
if any(p.stat().st_mtime_ns > binary.stat().st_mtime_ns for p in (prover / "src").rglob("*.elisa")):
    raise SystemExit("rebuild the stale proof executable")
here = Path(__file__).resolve().parent
inputs = [binary, Path(__file__), root / "src/semantic/binding_identity_types.elisa",
          root / "src/semantic/ownership_binding_flow.elisa", root / "src/semantic/ownership_flow_domain.elisa",
          here / "ownership_binding_identity.elisa", here / "ownership_binding_identity_rejected.elisa",
          here / "ownership_identity_replay_probe.elisa"]
hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}

def run(name):
    process = subprocess.run([str(binary), "--json", str(here / name)], capture_output=True, text=True, timeout=30)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report

code, report = run("ownership_binding_identity.elisa")
assert code == 0 and report["status"] == report["verification_state"] == "proved"
assert report["summary"]["proven"] == report["summary"]["obligations"] == 23
assert not report["findings"]
assert report == run("ownership_binding_identity.elisa")[1]
verified = {d["name"] for d in report["declaration_details"] if d.get("verified")}
assert {"binding_identity_reflexive", "serial_zero_is_valid", "missing_declaration_is_invalid"} <= verified
code, isolated = run("ownership_identity_replay_probe.elisa")
assert code == 0 and isolated["status"] == "proved"
assert isolated["summary"]["proven"] == isolated["summary"]["obligations"] == 6
code, rejected = run("ownership_binding_identity_rejected.elisa")
false_names = {"invalid_owner_is_valid", "different_serials_are_equal", "different_functions_are_equal"}
assert code == 1 and rejected["status"] == "failed"
assert {f["name"] for f in rejected["findings"]} == false_names
assert all(f["kind"] == "ensure-unproven" for f in rejected["findings"])
assert not false_names & {d["name"] for d in rejected["declaration_details"] if d.get("verified")}
assert hashes == {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
print(json.dumps({"admitted": True, "scope": "BindingId identity laws only, not ownership flow",
                  "producer_proven": 23, "independently_replayed": 23,
                  "false_claims_rejected": sorted(false_names), "sources_sha256": hashes}))
