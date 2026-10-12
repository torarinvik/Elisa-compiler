"""Check the metadata operand guard and its replayable index-bound proof."""
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product


ROOT = Path(__file__).resolve().parents[2]
PROVER = ROOT.parent / "elisa-proof"
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
SOURCE = ROOT / "src/backend/codegen_target_machine.elisa"
POSITIVE = HERE / "codegen_metadata_operand_bounds.elisa"
NEGATIVE = HERE / "codegen_metadata_operand_bounds_rejected.elisa"

source = SOURCE.read_text()
match = re.search(
    r"(?ms)^[ \t]*def md_property_is\([^\n]*\)[^\n]*:\n(.*?)(?=^[ \t]*def |\Z)",
    source,
)
if match is None:
    raise SystemExit("could not locate metadata property checker")
body = "".join(match.group(1).split())
steps = (
    "operand_count:usize=LLVMGetMDNodeNumOperands(property).usize()",
    "falsereturnifoperand_count==0",
    "operands:mutabledarray[LLVMValueRef]=[propertyfor_in0..<operand_count]",
    "LLVMGetMDNodeOperands(property,(&operands[0]).cast[void&]canUnsafe.PointerCast)",
    "LLVMGetMDString(operands[0],",
)
positions = [body.find(step) for step in steps]
if any(position < 0 for position in positions) or positions != sorted(positions):
    raise SystemExit("metadata operand zero is not guarded by the matching allocated operand count")

expected_positive = {
    "metadata_operand_zero_is_in_bounds",
    "empty_metadata_node_has_no_valid_operand_zero",
}
expected_negative = {"empty_metadata_node_operand_zero_is_in_bounds"}
declarations = lambda path: set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))
if declarations(POSITIVE) != expected_positive or declarations(NEGATIVE) != expected_negative:
    raise SystemExit("metadata operand bound proof inventory changed")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("metadata operand bound proof requires a strict proof build")


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=60)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["proven"] == positive["summary"]["obligations"] == 4
assert not positive["findings"]
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == expected_positive

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["obligations"] == 2 and negative["summary"]["proven"] == 1
assert {(finding["kind"], finding["name"]) for finding in negative["findings"]} == {
    ("ensure-unproven", name) for name in expected_negative
}

print(json.dumps({
    "scope": "operand zero is in bounds exactly when the captured metadata operand count is nonzero",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(expected_negative),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
}, sort_keys=True))
