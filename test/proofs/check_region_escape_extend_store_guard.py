"""Admit source-linked proof of the scalar/container `extend` store-check boundary."""
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
POSITIVE = HERE / "region_escape_extend_store_guard.elisa"
NEGATIVE = HERE / "region_escape_extend_store_guard_rejected.elisa"
IMPLEMENTATION = ROOT / "src/semantic/region_escape_stores.elisa"
INTEGRATION = ROOT / "src/semantic/check_region_escape.elisa"
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")

if not __debug__:
    raise SystemExit("run without Python -O")

source = IMPLEMENTATION.read_text()
start = source.find("def region_escape_check_store(")
if start < 0:
    raise SystemExit("production region-store checker is missing")
end = source.find("\n        def ", start + len("def region_escape_check_store("))
function = re.sub(r"#.*$", "", source[start:end if end >= 0 else None], flags=re.MULTILINE)
compact = "".join(function.split())
if "is_extend:bool=grow_call_is_extend(callee)" not in compact:
    raise SystemExit("container-growth operation classification changed without updating its proof")
guard = "returnifis_extendandnotreceiver_elements_are_containers(annotations,grow.receiver,line,local_names,local_types)"
if guard not in compact:
    raise SystemExit("scalar-only extend no longer skips the reference-store check")
if "value_region:sview=region_escape_stored_or_call_region(arguments[grow.value_index]" not in compact:
    raise SystemExit("extend store-path no longer computes the inserted value region after its guard")
if "ifnotregion_escape_value_carries_handles(arguments[grow.value_index]" not in compact:
    raise SystemExit("extend store-path no longer uses the region-handle classifier after its guard")

expected = {
    "element_store_check_reached_is_exact",
    "extending_scalar_elements_skips_reference_store_check",
    "extending_container_elements_reaches_reference_store_check",
    "ordinary_growth_method_reaches_reference_store_check",
}
declarations = set(re.findall(r"(?m)^def\s+(\w+)\s*\(", POSITIVE.read_text()))
if not expected <= declarations:
    raise SystemExit("extend-store proof lost an operation or element-shape law")

integration = INTEGRATION.read_text()
if 'include "./region_escape_stores.elisa"' not in integration:
    raise SystemExit("region escape checker no longer includes the proved extend-store guard")
if "region_escape_check_store(" not in integration:
    raise SystemExit("region escape checker no longer invokes the proved extend-store guard")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("extend-store proof requires a strict proof build")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV", stage1_product,
          stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
          *source_include_closure([POSITIVE, NEGATIVE, IMPLEMENTATION, INTEGRATION])]
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
    ("ensure-unproven", "extending_scalar_elements_runs_reference_store_check"),
    ("ensure-unproven", "ordinary_scalar_growth_skips_reference_store_check"),
]
assert require_current_product(BIN, PROVER) == manifest, "proof product changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "element-region store-check reachability for extend and other growth methods",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": [row["name"] for row in negative["findings"]],
    "sources_sha256": hashes_before,
}, sort_keys=True))
