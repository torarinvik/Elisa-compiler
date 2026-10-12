"""Admit signed frontend-IR writer proofs against a strict Elisa-proof product."""
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
POSITIVE = HERE / "frontend_ir_writer_zigzag.elisa"
NEGATIVE = HERE / "frontend_ir_writer_zigzag_rejected.elisa"
WRITER = ROOT / "src/driver/frontend_ir_write.elisa"
READER = ROOT / "src/driver/frontend_ir.elisa"

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
        raise SystemExit(f"could not locate function {name}")
    return match.group(1)


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


writer_text = WRITER.read_text()
writer_body = function_body(writer_text, "ir_varint_out")
writer_code = "\n".join(line.split("#", 1)[0] for line in writer_body.splitlines())
writer = compact(writer_code)
writer_steps = (
    "zigzag:u64=(((0-(value+1)).u64()<<1)|1)ifvalue<0else(value.u64()<<1)",
    "ir_uvarint_out(buffer,zigzag)",
)
positions = [writer.find(step) for step in writer_steps]
if any(position < 0 for position in positions) or positions != sorted(positions):
    raise SystemExit("IR writer no longer uses the overflow-safe signed zigzag map before uvarint output")
if "0-value" in writer:
    raise SystemExit("IR writer reintroduced signed negation of the input value")

reader = compact(function_body(READER.read_text(), "ir_varint"))
reader_steps = (
    "magnitude:i64=(raw>>1).i64()",
    "out_value<-((0-magnitude)-1)if(raw&1)!=0elsemagnitude",
    "out_next<-next",
    "returntrue",
)
reader_positions = [reader.find(step) for step in reader_steps]
if any(position < 0 for position in reader_positions) or reader_positions != sorted(reader_positions):
    raise SystemExit("IR reader no longer decodes the signed zigzag magnitude used by the writer proof")

roundtrip = compact(function_body(POSITIVE.read_text(), "writer_negative_zigzag_roundtrips"))
roundtrip_claim = (
    "requiresvalue<0",
    "ensureresult==true",
    "magnitude:i64=0-(value+1)",
    "return(0-magnitude)-1==value",
)
if any(claim not in roundtrip for claim in roundtrip_claim):
    raise SystemExit("writer proof no longer proves exact recovery for every negative i64")

minimum = compact(function_body(POSITIVE.read_text(), "writer_minimum_safe_negation_is_maximum"))
minimum_claim = (
    "ensureresult==true",
    "return0-(((0-9223372036854775807)-1)+1)==9223372036854775807",
)
if any(claim not in minimum for claim in minimum_claim):
    raise SystemExit("writer proof no longer checks the safe magnitude at i64::MIN")

false_claim = compact(function_body(NEGATIVE.read_text(), "writer_negative_roundtrip_can_be_off_by_one"))
if any(claim not in false_claim for claim in (
    "requiresvalue<0",
    "ensureresult==true",
    "magnitude:i64=0-(value+1)",
    "return(0-magnitude)-1==value+1",
)):
    raise SystemExit("writer negative control no longer asserts an incorrect off-by-one result")

expected_positive = {
    "writer_negative_zigzag_roundtrips",
    "writer_minimum_safe_negation_is_maximum",
}
expected_negative = {"writer_negative_roundtrip_can_be_off_by_one"}
if declarations(POSITIVE) != expected_positive or declarations(NEGATIVE) != expected_negative:
    raise SystemExit("frontend IR writer zigzag proof declaration inventory changed")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("frontend IR writer zigzag proof requires a strict proof build")

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
    WRITER,
    READER,
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
assert positive["summary"]["proven"] == positive["summary"]["obligations"] == 4
assert not positive["findings"]
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == expected_positive

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["obligations"] == 2 and negative["summary"]["proven"] == 1
assert [(row["kind"], row["name"]) for row in negative["findings"]] == [
    ("ensure-unproven", "writer_negative_roundtrip_can_be_off_by_one")
]

assert require_current_product(BIN, PROVER) == product, "proof product provenance changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
if hashes_before != hashes_after:
    raise SystemExit("frontend IR writer proof inputs changed during replay")

print(json.dumps({
    "admitted": True,
    "scope": "overflow-safe signed frontend-IR zigzag magnitude, exact negative roundtrip, and i64-minimum boundary",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(expected_negative),
    "proof_binary_sha256": hashlib.sha256(BIN.read_bytes()).hexdigest(),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "inputs_sha256": hashes_before,
}, sort_keys=True))
