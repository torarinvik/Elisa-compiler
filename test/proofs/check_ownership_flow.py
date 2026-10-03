"""Admission gate for the imported Boolean ownership-domain laws, not compiler flow."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PROVER = ROOT.parent / "wasmbrowser-proof"
BIN = Path(os.environ.get("ELISA_PROOF_BIN", str(PROVER / "build/elisa-proof-ownership-flow"))).resolve(strict=True)
if not __debug__:
    raise SystemExit("run without Python -O")
if any(path.stat().st_mtime_ns > BIN.stat().st_mtime_ns for path in (PROVER / "src").rglob("*.elisa")):
    raise SystemExit("proof executable is older than prover source; rebuild it")
inputs = [BIN, Path(__file__), ROOT / "src/semantic/ownership_flow_domain.elisa",
          HERE / "ownership_flow_domain.elisa", HERE / "ownership_flow_domain_rejected.elisa",
          HERE / "ownership_reachable_join.elisa"]
hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}

def run(name):
    process = subprocess.run([str(BIN), "--json", str(HERE / name)], capture_output=True, text=True, timeout=30)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    assert not report["trust"]["trusted_assumptions"]
    return process.returncode, report

code, positive = run("ownership_flow_domain.elisa")
assert code == 0 and positive["status"] == "proved" and positive["verification_state"] == "proved"
assert positive["summary"]["proven"] == positive["summary"]["obligations"] == 36
assert positive == run("ownership_flow_domain.elisa")[1], "proof reports changed across repeats"
algebraic_names = {"possible_commutative", "possible_idempotent", "possible_associative",
              "possible_empty_identity", "known_commutative", "known_idempotent",
              "known_associative"}
assert not positive["findings"]
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert {"join_possible", "join_known", "can_move", "possible_preserves_consumed",
        "unknown_stays_unknown", "unknown_blocks_move", "unreachable_blocks_move",
        "live_owner_can_move", "consumed_blocks_move"} <= verified
assert algebraic_names <= verified
assert {"join_reachable_possible", "join_reachable_known"} <= verified
assert len(verified) == 18
assert all(row.get("verified") for row in positive["declaration_details"] if row["kind"] == "function")
code, negative = run("ownership_flow_domain_rejected.elisa")
assert code == 1 and negative["status"] == "failed"
false_names = {"false_join_discards_consumed", "false_unknown_is_known",
               "false_consumed_can_move", "false_unknown_can_move", "false_join_drops_peer",
               "false_join_changes_operator", "false_known_uses_or"}
assert {finding["name"] for finding in negative["findings"]} == false_names
assert all(finding["kind"] == "ensure-unproven" for finding in negative["findings"])
assert not false_names & {row["name"] for row in negative["declaration_details"] if row.get("verified")}
code, reachable = run("ownership_reachable_join.elisa")
assert code == 0 and reachable["status"] == "proved"
assert reachable["summary"]["proven"] == reachable["summary"]["obligations"] == 16
assert reachable == run("ownership_reachable_join.elisa")[1]
assert not reachable["findings"]
assert hashes == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
print(json.dumps({"admitted": True, "scope": "imported Boolean ownership-domain laws only",
                  "proved": 36, "obligations": 36, "replayed": 36,
                  "reachable_join_report_proved": 16,
                  "open_declarations": [], "false_claims_rejected": sorted(false_names),
                  "sources_sha256": hashes}, sort_keys=True))
