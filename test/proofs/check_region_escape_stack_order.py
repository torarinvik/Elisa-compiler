"""Admit source-linked proofs of the lexical region-store lifetime comparison."""
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
POSITIVE = HERE / "region_escape_stack_order.elisa"
NEGATIVE = HERE / "region_escape_stack_order_rejected.elisa"
IMPLEMENTATION = ROOT / "src/semantic/region_escape_assignments.elisa"
INTEGRATION = ROOT / "src/semantic/check_region_escape.elisa"
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")

if not __debug__:
    raise SystemExit("run without Python -O")

implementation_source = IMPLEMENTATION.read_text()
function_start = implementation_source.find("def region_escape_check_assign(")
if function_start < 0:
    raise SystemExit("production region assignment checker is missing")
next_function = implementation_source.find("\n        def ", function_start + len("def region_escape_check_assign("))
function_source = implementation_source[function_start:next_function if next_function >= 0 else None]
compact_function = "".join(function_source.split())
production_condition = (
    "escapes:bool=target_position.foundandvalue_position.found"
    "andtarget_position.position<value_position.position"
)
if production_condition not in compact_function:
    raise SystemExit("region-store lifetime comparison changed without updating its proof")
if "DiagnosticKind.RegionStoreEscape" not in compact_function or "ifescapes" not in compact_function:
    raise SystemExit("proved region-store comparison no longer gates the escape diagnostic")

integration = INTEGRATION.read_text()
if 'include "./region_escape_assignments.elisa"' not in integration:
    raise SystemExit("region checker no longer includes the proved assignment rule")
if "region_escape_check_assign(" not in integration:
    raise SystemExit("region checker no longer invokes the proved assignment rule")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("region-store lifetime proof requires a strict proof build")

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
    "production_store_escape_condition_is_exact",
    "outer_target_receiving_inner_value_is_an_escape",
    "equal_region_positions_do_not_escape",
    "inner_target_receiving_outer_value_does_not_escape",
    "missing_region_position_does_not_establish_escape",
}
assert expected <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert [(row["kind"], row["name"]) for row in negative["findings"]] == [
    ("ensure-unproven", "reversed_region_order_reports_outer_target_as_escape")]
assert require_current_product(BIN, PROVER) == manifest, "proof product changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "strict lexical region-position ordering for region-store escape diagnostics",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": ["reversed_region_order_reports_outer_target_as_escape"],
    "sources_sha256": hashes_before,
}, sort_keys=True))
