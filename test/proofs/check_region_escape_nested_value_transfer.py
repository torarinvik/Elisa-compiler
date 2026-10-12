"""Admit source-linked proofs of nested region-handle transfer rules."""
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
POSITIVE = HERE / "region_escape_nested_value_transfer.elisa"
NEGATIVE = HERE / "region_escape_nested_value_transfer_rejected.elisa"
IMPLEMENTATION = ROOT / "src/semantic/region_escape_stores.elisa"
INTEGRATION = ROOT / "src/semantic/check_region_escape.elisa"
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")

if not __debug__:
    raise SystemExit("run without Python -O")


def source_function(name: str) -> str:
    source = IMPLEMENTATION.read_text()
    start = source.find(f"def {name}(")
    if start < 0:
        raise SystemExit(f"production region-handle helper is missing: {name}")
    end = source.find("\n        def ", start + len(f"def {name}("))
    return "".join(source[start:end if end >= 0 else None].split())


body = source_function("region_escape_body_carries_handles")
value = source_function("region_escape_value_carries_handles")
body_arms = (
    "ifexplicit_valueisvalue:returnregion_escape_value_carries_handles(value,annotations,line,body_names,body_types,table)",
    "returntrueifbody.count==0",
    "Stmt.Expr(value,_):region_escape_value_carries_handles(value,annotations,line,body_names,body_types,table)",
    "_:true",
)
value_arms = (
    "Expr.Block(body,carries_value,_,_):returnregion_escape_body_carries_handles(body,carries_value,annotations,line,local_names,local_types,table)",
    "Expr.Match(_,carries_arms,_):forarmincarries_arms:arm_names:mutabledarray[sview]=[namefornameinlocal_names]",
    "returntrueifregion_escape_body_carries_handles(arm.body,null,annotations,line,arm_names,arm_types,table)returnfalse",
    "Expr.Catch(guarded,carries_arms,_):truereturnifregion_escape_value_carries_handles(guarded,annotations,line,local_names,local_types,table)",
    "truereturnifarm.body.count==0",
    "Stmt.Expr(arm_value,_):truereturnifregion_escape_value_carries_handles(arm_value,annotations,line,local_names,local_types,table)",
)
for arm in body_arms:
    if arm not in body:
        raise SystemExit(f"production block handle-transfer arm changed without updating its proof: {arm}")
for arm in value_arms:
    if arm not in value:
        raise SystemExit(f"production match/catch handle-transfer arm changed without updating its proof: {arm}")
if "_:returntrue" not in value[value.find("Expr.Catch("):]:
    raise SystemExit("catch non-expression arms no longer conservatively carry region handles")
if "returnfalse" not in value[value.find("Expr.Catch("):]:
    raise SystemExit("catch with no carrying paths no longer returns false")

expected = {
    "block_handle_transfer_is_exact",
    "explicit_block_value_overrides_body",
    "implicit_empty_block_is_conservative",
    "block_trailing_expression_preserves_handle_status",
    "block_trailing_non_expression_is_conservative",
    "match_handle_transfer_is_exact",
    "match_with_no_arms_carries_no_region_handle",
    "catch_handle_transfer_is_exact",
    "catch_without_handler_arms_preserves_guarded_value",
    "conservative_catch_arm_can_carry_a_region_handle",
}
declarations = set(re.findall(r"(?m)^def\s+(\w+)\s*\(", POSITIVE.read_text()))
if not expected <= declarations:
    raise SystemExit("nested-value proof lost a block, match, or catch transfer law")

integration = INTEGRATION.read_text()
if 'include "./region_escape_stores.elisa"' not in integration:
    raise SystemExit("region escape checker no longer includes nested-value handle analysis")
if "region_escape_stored_or_call_region(" not in integration:
    raise SystemExit("region escape integration no longer reaches nested-value handle analysis")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("nested region-value transfer proof requires a strict proof build")

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
    ("ensure-unproven", "implicit_empty_block_carries_no_region_handle"),
    ("ensure-unproven", "match_with_a_carrying_arm_carries_no_region_handle"),
]
assert require_current_product(BIN, PROVER) == manifest, "proof product changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "block result, match-arm, and catch-handler region-handle propagation",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": [row["name"] for row in negative["findings"]],
    "sources_sha256": hashes_before,
}, sort_keys=True))
