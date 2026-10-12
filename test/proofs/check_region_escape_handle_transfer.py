"""Admit source-linked proofs of region-handle propagation across expression shapes."""
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
POSITIVE = HERE / "region_escape_handle_transfer.elisa"
NEGATIVE = HERE / "region_escape_handle_transfer_rejected.elisa"
IMPLEMENTATION = ROOT / "src/semantic/region_escape_stores.elisa"
INTEGRATION = ROOT / "src/semantic/check_region_escape.elisa"
ASSIGNMENTS = ROOT / "src/semantic/region_escape_assignments.elisa"
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")

if not __debug__:
    raise SystemExit("run without Python -O")

implementation_source = IMPLEMENTATION.read_text()
function_start = implementation_source.find("def region_escape_value_carries_handles(")
if function_start < 0:
    raise SystemExit("production region-handle classifier is missing")
next_function = implementation_source.find("\n        def ", function_start + len("def region_escape_value_carries_handles("))
function_source = implementation_source[function_start:next_function if next_function >= 0 else None]
compact = "".join(function_source.split())
production_arms = (
    "Expr.IntLit(_,_)|Expr.FloatLit(_,_)|Expr.BoolLit(_,_)|Expr.CharLit(_, _):returnfalse",
    "Expr.Tuple(carries_elements,carries_tuple_line):returnanyelementincarries_elementswhereregion_escape_value_carries_handles(element,annotations,line,local_names,local_types,table)",
    "Expr.Array(carries_elements,carries_array_line):returntrue",
    "Expr.RecordUpdate(carries_base,carries_fields,carries_update_line):returnregion_escape_value_carries_handles(carries_base,annotations,line,local_names,local_types,table)oranyfieldincarries_fieldswhereregion_escape_value_carries_handles(field.value,annotations,line,local_names,local_types,table)",
    "Expr.If(carries_condition,carries_then,carries_else,carries_if_line):returnregion_escape_value_carries_handles(carries_then,annotations,line,local_names,local_types,table)orregion_escape_value_carries_handles(carries_else,annotations,line,local_names,local_types,table)",
    'falsereturnifcarries_field_name=="len"orcarries_field_name=="count"',
)
for arm in production_arms:
    if "".join(arm.split()) not in compact:
        raise SystemExit(f"region-handle transfer arm changed without updating its proof: {arm}")
if "#Anunknownelementtypecannotestablishthatcopyingitissafe.returntrue" not in compact:
    raise SystemExit("unknown index elements no longer conservatively carry a region handle")

expected = {
    "tuple_handle_transfer_is_exact",
    "empty_tuple_carries_no_region_handle",
    "record_update_handle_transfer_is_exact",
    "conditional_handle_transfer_is_exact",
    "array_literal_is_conservatively_treated_as_handle_carrying",
    "scalar_literal_carries_no_region_handle",
    "unknown_index_is_conservatively_treated_as_handle_carrying",
    "length_and_count_fields_carry_no_region_handle",
}
declarations = set(re.findall(r"(?m)^def\s+(\w+)\s*\(", POSITIVE.read_text()))
if not expected <= declarations:
    raise SystemExit("region-handle proof lost a transfer or conservatism law")

compact_assignments = "".join(ASSIGNMENTS.read_text().split())
if "region_escape_value_carries_handles(value,annotations,line,local_type_names,local_type_exprs,table)" not in compact_assignments:
    raise SystemExit("assignment escape analysis no longer calls the proved handle classifier")
integration = INTEGRATION.read_text()
if 'include "./region_escape_stores.elisa"' not in integration:
    raise SystemExit("region escape checker no longer includes the proved handle classifier")
if "region_escape_stored_or_call_region(" not in integration or "region_escape_check_assign(" not in integration:
    raise SystemExit("region escape integration no longer reaches the proved handle-analysis path")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("region-handle transfer proof requires a strict proof build")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV", stage1_product,
          stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
          *source_include_closure([POSITIVE, NEGATIVE, IMPLEMENTATION, ASSIGNMENTS, INTEGRATION])]
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
    ("ensure-unproven", "empty_tuple_can_carry_region_handle"),
    ("ensure-unproven", "length_field_may_carry_region_handle"),
]
assert require_current_product(BIN, PROVER) == manifest, "proof product changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "conservative region-handle propagation across literals, aggregates, branches, and projections",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": [row["name"] for row in negative["findings"]],
    "sources_sha256": hashes_before,
}, sort_keys=True))
