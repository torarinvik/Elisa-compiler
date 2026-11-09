import hashlib
import json
import sys
from pathlib import Path

out = Path(sys.argv[1])
scope = sys.argv[2]
if scope not in ("compile_only", "full_runtime"):
    raise SystemExit(f"invalid timing sample scope: {scope}")
names = ["build_samples.csv", "compile_samples.csv"]
names.append("counter_samples.csv")
if scope == "full_runtime":
    names.append("samples.csv")
rows = []
for name in sorted(names):
    path = out / name
    if not path.is_file():
        raise SystemExit(f"missing timing sample artifact: {path}")
    rows.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {name}\n")
manifest_bytes = "".join(rows).encode("utf-8")
manifest_path = out / "timing_samples.sha256"
manifest_path.write_bytes(manifest_bytes)

fingerprint_path = out / "canonical_workload_fingerprint.json"
record = json.loads(fingerprint_path.read_text())
provenance = record.get("run_provenance")
if not isinstance(provenance, dict) or provenance.get("scope") != scope:
    raise SystemExit("canonical fingerprint has inconsistent timing sample scope")
provenance["timing_samples_manifest_sha256"] = hashlib.sha256(manifest_bytes).hexdigest()
binding = json.dumps(
    {"payload": record["payload"], "run_provenance": provenance},
    sort_keys=True,
    separators=(",", ":"),
).encode("utf-8")
record["run_fingerprint_sha256"] = hashlib.sha256(binding).hexdigest()
fingerprint_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
