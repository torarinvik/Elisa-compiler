"""Bind aggregate ABI threshold proofs to LLVM ABI-size lowering."""
from __future__ import annotations
import argparse, hashlib, json, os, re, subprocess
from pathlib import Path
from proof_product_gate import require_current_product, source_include_closure

parser = argparse.ArgumentParser()
parser.add_argument("--source-only", action="store_true")
args = parser.parse_args()
ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve()
SOURCE = ROOT / "src/backend/codegen_abi_facts.elisa"
POSITIVE = HERE / "backend_aggregate_abi_threshold.elisa"
NEGATIVE = HERE / "backend_aggregate_abi_threshold_rejected.elisa"
EXPECTED = {
    "aggregate_uses_indirect_abi": "8e562f9e2bac593a35bbb7c67b212ae0d321022ae040bd2309f6b657fb87741c",
    "aggregate_at_threshold_is_indirect": "fdaabc5803b5caa2ba0873b1fd987db1d1fe2e8a8f14fba2072e504ae6c71011",
    "aggregate_below_threshold_is_direct": "874f6a6963250b556d7fb2680ba86244dc6c7c7ed11453b15aa122a9394e1476",
    "scalar_never_uses_indirect_aggregate_abi": "b9b853e71d1d07fc12ea049a1f4a048082e50dbc6a9ab739522d8d9cd0a9f666",
}
FALSE = {
    "false_1023_byte_aggregate_is_indirect": "4c4c79e1c06cbde2466763e81f407eb8633dc691ac696806666ecf3a4f01904b",
    "false_scalar_is_indirect": "b80bf76b9523f853ecb641acd914bf4f5524906ae85f0cf736720804e24e8e5d",
}
def compact(text: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in text.splitlines())
def section(text: str, name: str) -> str:
    match = re.search(rf"(?m)^[ \t]*def {re.escape(name)}\(", text)
    if not match:
        raise SystemExit(f"missing {name}")
    following = re.search(r"(?m)^[ \t]*def [A-Za-z_]\w*\(", text[match.end():])
    return text[match.start():match.end() + following.start() if following else len(text)]
for path, expected in ((POSITIVE, EXPECTED), (NEGATIVE, FALSE)):
    source = path.read_text()
    for name, digest in expected.items():
        if hashlib.sha256(compact(section(source, name)).encode()).hexdigest() != digest:
            raise SystemExit(f"{name} proof changed since source binding")
if not NEGATIVE.read_text().startswith('include "./backend_aggregate_abi_threshold.elisa"'):
    raise SystemExit("false controls must import the threshold model")
abi = compact(section(SOURCE.read_text(), "value_type_uses_indirect_aggregate"))
expected_source = (
    "aggregate:bool=value_type.kind==TypeKind.Structorvalue_type.kind==TypeKind.Arrayorvalue_type.kind==TypeKind.PayloadEnumorvalue_type.kind==TypeKind.Optional",
    "returnfalseifnotaggregate",
    "aggregate_type:LLVMTypeRef=llvm_type_of(value_type,structs,ctx)",
    "returnLLVMABISizeOfType(structs.target.target_data,aggregate_type)>=1024.u64()",
)
if any(part not in abi for part in expected_source) or [abi.index(part) for part in expected_source] != sorted(abi.index(part) for part in expected_source):
    raise SystemExit("aggregate ABI eligibility or LLVM size threshold changed")
sret = compact(section(SOURCE.read_text(), "value_type_uses_sret"))
if "returnvalue_type_uses_indirect_aggregate(value_type,structs,ctx)" not in sret:
    raise SystemExit("sret decision no longer uses indirect aggregate policy")
if args.source_only:
    print("source_bound=True positive=4 false_controls=2")
    raise SystemExit(0)
product = require_current_product(BIN, PROVER)
if product.get("compile_mode") != "strict":
    raise SystemExit("aggregate ABI proof requires strict Elisa-Proof build")
inputs = list(dict.fromkeys([BIN, BIN.with_name(BIN.name + ".manifest.json"), BIN.with_name(BIN.name + ".manifest.json.sha256"), PROVER / "ELISA_COMPILER_REV", Path(__file__), HERE / "proof_product_gate.py", SOURCE, POSITIVE, NEGATIVE, *source_include_closure([POSITIVE, NEGATIVE])]))
before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
def run(path: Path):
    result = subprocess.run([str(BIN), "--json", str(path)], capture_output=True, text=True, timeout=60)
    return result.returncode, json.loads(result.stdout)
code, positive = run(POSITIVE)
if code or positive.get("status") != "proved" or positive.get("summary", {}).get("proven") != positive.get("summary", {}).get("obligations"):
    raise SystemExit("aggregate ABI threshold proof did not fully prove")
code, negative = run(NEGATIVE)
if code != 1 or negative.get("status") != "failed" or {f.get("name") for f in negative.get("findings", [])} != set(FALSE) or not all(f.get("kind") == "ensure-unproven" and f.get("status") in ("unknown", "disproved") for f in negative.get("findings", [])):
    raise SystemExit("aggregate ABI false controls were not rejected")
if {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs} != before:
    raise SystemExit("aggregate ABI proof inputs changed during replay")
print(json.dumps({"proved": positive["summary"]["proven"], "false_controls_rejected": len(FALSE), "source_bound": True}))
