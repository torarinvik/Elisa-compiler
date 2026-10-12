"""Admit source-linked step proofs for lexical region-stack position scanning."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve(strict=True)
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
POSITIVE = HERE / "region_escape_stack_scan.elisa"
NEGATIVE = HERE / "region_escape_stack_scan_rejected.elisa"
PROVENANCE = ROOT / "src/semantic/region_escape_provenance.elisa"
ASSIGNMENTS = ROOT / "src/semantic/region_escape_assignments.elisa"
STORES = ROOT / "src/semantic/region_escape_stores.elisa"
INTEGRATION = ROOT / "src/semantic/check_region_escape.elisa"
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")

if not __debug__:
    raise SystemExit("run without Python -O")

source = PROVENANCE.read_text()
start = source.find("def region_stack_position(")
if start < 0:
    raise SystemExit("production region-stack position scan is missing")
end = source.find("\n        def ", start + len("def region_stack_position("))
function = re.sub(r"#.*$", "", source[start:end if end >= 0 else None], flags=re.MULTILINE)
compact = "".join(function.split())
production_steps = (
    "found_here:mutablebool=false",
    "position_here:mutableusize=0",
    "matched:bool=nesting[probe]==region_name",
    "found_here<-trueifmatched",
    "position_here<-probeifmatched",
    "probe<-probe+1",
    "return(found_here,position_here)",
)
for step in production_steps:
    if step not in compact:
        raise SystemExit(f"region-stack scan transition changed without updating its proof: {step}")
if "whileprobe<nesting.count|probe:usize=0,found_here,position_here|" not in compact:
    raise SystemExit("region-stack scan no longer examines each stack position from index zero")

for path, use in (
    (ASSIGNMENTS, "region_stack_position(nesting,value_region)"),
    (ASSIGNMENTS, "region_stack_position(nesting,target_region)"),
    (STORES, "region_stack_position(nesting,owner_region)"),
    (STORES, "region_stack_position(nesting,value_region)"),
    (STORES, "region_stack_position(nesting,container_region)"),
):
    if "".join(path.read_text().split()).find(use) < 0:
        raise SystemExit(f"region escape caller no longer uses the proved scan: {path.name}: {use}")

integration = INTEGRATION.read_text()
if 'include "./region_escape_provenance.elisa"' not in integration:
    raise SystemExit("region escape integration no longer includes the proved stack scan")

expected = {
    "stack_scan_found_update_is_exact",
    "a_match_sets_stack_scan_found",
    "a_nonmatch_preserves_an_earlier_stack_match",
    "stack_scan_position_update_is_exact",
    "a_matching_probe_becomes_the_recorded_position",
    "a_nonmatching_probe_preserves_the_recorded_position",
    "a_later_matching_probe_overwrites_an_earlier_match",
    "an_unmatched_empty_scan_keeps_the_zero_position",
}
declarations = set(re.findall(r"(?m)^def\s+(\w+)\s*\(", POSITIVE.read_text()))
if not expected <= declarations:
    raise SystemExit("region-stack proof lost a scan-state transition or boundary law")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("region-stack scan proof requires a strict proof build")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV", stage1_product,
          stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
          *source_include_closure([POSITIVE, NEGATIVE, PROVENANCE, ASSIGNMENTS, STORES, INTEGRATION])]
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
assert expected <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert [(row["kind"], row["name"]) for row in negative["findings"]] == [
    ("ensure-unproven", "an_unmatched_probe_clears_a_previous_match"),
    ("ensure-unproven", "a_matching_probe_preserves_the_earlier_position"),
]
assert require_current_product(BIN, PROVER) == manifest, "proof product changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "found-state and latest-match position transitions in lexical region-stack scans",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": [row["name"] for row in negative["findings"]],
    "sources_sha256": hashes_before,
}, sort_keys=True))
