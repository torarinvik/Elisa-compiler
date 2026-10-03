"""Track the open nested-record summary replay gap; not an admission gate."""
import json
import os
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[2]
prover = root.parent / "wasmbrowser-proof"
binary = Path(os.environ.get("ELISA_PROOF_BIN", str(prover / "build/elisa-proof-ownership-flow")))
if any(p.stat().st_mtime_ns > binary.stat().st_mtime_ns for p in (prover / "src").rglob("*.elisa")):
    raise SystemExit("rebuild the stale proof executable")
process = subprocess.run([str(binary), "--json", str(Path(__file__).with_name("ownership_binding_identity.elisa"))], capture_output=True, text=True, timeout=30)
report = json.loads(process.stdout)
assert report["summary"]["semantic_errors"] == 0
assert not report["trust"]["trusted_assumptions"]
assert report["summary"]["proven"] == report["summary"]["obligations"] == 21
assert report["replay"] == {"certificates": 21, "replayed": 20, "gaps": 1}
gaps = [c for c in report["certificates"] if not c["replayed"]]
assert len(gaps) == 1 and gaps[0]["name"] == "serial_zero_is_valid"
assert report["status"] == "proved_with_replay_gaps"
print(json.dumps({"admitted": False, "producer_proven": 21, "independently_replayed": 20,
                  "open": "serial_zero_is_valid nested-record summary replay"}))
