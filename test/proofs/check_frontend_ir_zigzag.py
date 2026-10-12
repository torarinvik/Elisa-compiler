"""Admit signed frontend-IR varint inverse laws against a strict proof build."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product


ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
POSITIVE = HERE / "frontend_ir_zigzag.elisa"
NEGATIVE = HERE / "frontend_ir_zigzag_rejected.elisa"
SOURCE = ROOT / "src/driver/frontend_ir.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    return "".join(text.split())


def function_body(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^[ \t]*def {re.escape(name)}\([^\n]*\)[^\n]*:\n(.*?)(?=^[ \t]*def |\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"could not locate production function {name}")
    return match.group(1)


source = compact(function_body(SOURCE.read_text(), "ir_varint"))
source_steps = (
    "falsereturnifnotir_uvarint(data,offset,&raw,&next)",
    "magnitude:i64=(raw>>1).i64()",
    "out_value<-((0-magnitude)-1)if(raw&1)!=0elsemagnitude",
    "out_next<-next",
    "returntrue",
)
positions = [source.find(step) for step in source_steps]
if any(position < 0 for position in positions) or positions != sorted(positions):
    raise SystemExit("signed IR varint decoding no longer follows the checked zigzag inverse")

even_branch = compact(function_body(
    POSITIVE.read_text(), "even_zigzag_payload_decodes_nonnegative"
))
even_branch_claim = (
    "requiresmagnitude>=0andnotodd",
    "ensureresult==true",
    "decoded:i64=(0-magnitude)-1ifoddelsemagnitude",
    "returndecoded==magnitude",
)
if any(claim not in even_branch for claim in even_branch_claim):
    raise SystemExit("even zigzag proof no longer establishes identity on the even branch")
odd_branch = compact(function_body(
    POSITIVE.read_text(), "odd_zigzag_payload_decodes_negative"
))
odd_branch_claim = (
    "requiresmagnitude>=0andodd",
    "ensureresult==true",
    "decoded:i64=(0-magnitude)-1ifoddelsemagnitude",
    "returndecoded<0",
)
if any(claim not in odd_branch for claim in odd_branch_claim):
    raise SystemExit("odd zigzag proof no longer establishes a negative result on the odd branch")

minimum_boundary = compact(function_body(
    POSITIVE.read_text(), "maximum_odd_zigzag_payload_decodes_to_i64_min"
))
minimum_boundary_claim = (
    "requiresmagnitude==9223372036854775807",
    "ensureresult==true",
    "return(0-magnitude)-1==(0-9223372036854775807)-1",
)
if any(claim not in minimum_boundary for claim in minimum_boundary_claim):
    raise SystemExit("signed IR zigzag proof no longer establishes the exact i64-minimum boundary")
decode_range = compact(function_body(POSITIVE.read_text(), "zigzag_decode_is_in_i64_range"))
decode_range_claim = (
    "requiresmagnitude>=0andmagnitude<=9223372036854775807",
    "ensureresult==true",
    "decoded:i64=(0-magnitude)-1ifoddelsemagnitude",
    "returndecoded>=(0-9223372036854775807)-1anddecoded<=9223372036854775807",
)
if any(claim not in decode_range for claim in decode_range_claim):
    raise SystemExit("signed IR zigzag proof no longer bounds both parity branches to i64")
underflow_counterexample = compact(function_body(
    NEGATIVE.read_text(), "maximum_odd_zigzag_payload_can_underflow"
))
if (
    "requiresmagnitude==9223372036854775807" not in underflow_counterexample
    or "ensureresult==true" not in underflow_counterexample
    or "return(0-magnitude)-1<(0-9223372036854775807)-1" not in underflow_counterexample
):
    raise SystemExit("signed IR zigzag proof no longer rejects a below-i64-minimum decode claim")

expected_positive = {
    "even_zigzag_payload_decodes_nonnegative",
    "odd_zigzag_payload_decodes_negative",
    "zigzag_decode_is_in_i64_range",
    "negative_value_roundtrips_through_zigzag_inverse",
    "maximum_odd_zigzag_payload_decodes_to_i64_min",
}
expected_negative = {
    "odd_zigzag_payload_can_decode_nonnegative",
    "negative_zigzag_inverse_roundtrip_can_be_off_by_one",
    "maximum_odd_zigzag_payload_can_underflow",
}


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


if declarations(POSITIVE) != expected_positive or declarations(NEGATIVE) != expected_negative:
    raise SystemExit("frontend IR zigzag proof declaration inventory changed")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("frontend IR zigzag proof requires a strict proof build")

compiler = product["compiler"]
stage1_product = Path(compiler["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN,
    MANIFEST,
    MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV",
    stage1_product,
    stage1_provenance,
    Path(__file__),
    HERE / "proof_product_gate.py",
    POSITIVE,
    NEGATIVE,
    SOURCE,
]))
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
assert positive["summary"]["proven"] == positive["summary"]["obligations"] == 10
assert not positive["findings"]
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == expected_positive

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["obligations"] == 6 and negative["summary"]["proven"] == 3
assert {(finding["kind"], finding["name"]) for finding in negative["findings"]} == {
    ("ensure-unproven", name) for name in expected_negative
}

assert require_current_product(BIN, PROVER) == product, "proof product provenance changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
if hashes_before != hashes_after:
    raise SystemExit("frontend IR zigzag proof inputs changed during replay")

print(json.dumps({
    "admitted": True,
    "scope": "signed frontend-IR zigzag sign, range, negative round trips, and i64 minimum boundary",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(expected_negative),
    "proof_binary_sha256": hashlib.sha256(BIN.read_bytes()).hexdigest(),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "inputs_sha256": hashes_before,
}, sort_keys=True))
