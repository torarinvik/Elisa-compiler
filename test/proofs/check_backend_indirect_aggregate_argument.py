"""Bind indirect aggregate argument copy proofs to the codegen helper."""
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
POSITIVE = HERE / "backend_indirect_aggregate_argument.elisa"
NEGATIVE = HERE / "backend_indirect_aggregate_argument_rejected.elisa"
POSITIVE_HASHES = {
    "indirect_aggregate_argument_allocates_slot": "70a179cab679fc81dd4f5c8da55ba8c8e7a1c29f1851437f6cf7b4e193dad951",
    "indirect_aggregate_argument_stores_value": "1337e58b3b3e12ce14e8b24ecdf5818da1565bf27baaa0fd6479642cd1dddb48",
    "direct_aggregate_argument_uses_original_value": "8d62a61d323e4b255ae2b315d7b87c69b5031098a1accd1b072c7dbdb0630270",
}
NEGATIVE_HASHES = {
    "false_indirect_value_skips_slot": "6b7af7656d14a48cc0b8e38773af49a79005c6bf1b7ce3a75a1240eb0237b0e4",
    "false_indirect_value_skips_store": "1204a56a72266d4f4f2d4bc9fda51d27a1241f4c84705e6d2f284cd63cabb08d",
}
def compact(text: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in text.splitlines())
def section(text: str, name: str) -> str:
    match = re.search(rf"(?m)^[ \t]*def {re.escape(name)}\(", text)
    if not match:
        raise SystemExit(f"missing {name}")
    following = re.search(r"(?m)^[ \t]*def [A-Za-z_]\w*\(", text[match.end():])
    return text[match.start():match.end() + following.start() if following else len(text)]
for path, expected in ((POSITIVE, POSITIVE_HASHES), (NEGATIVE, NEGATIVE_HASHES)):
    text = path.read_text()
    for name, digest in expected.items():
        if hashlib.sha256(compact(section(text, name)).encode()).hexdigest() != digest:
            raise SystemExit(f"{name} proof changed since source binding")
if not NEGATIVE.read_text().startswith('include "./backend_indirect_aggregate_argument.elisa"'):
    raise SystemExit("false controls must import the positive model")
body = compact(section(SOURCE.read_text(), "materialize_indirect_aggregate_argument"))
ordered = (
    "indirect:bool=value_type_uses_indirect_aggregate(value_type,structs,ctx)",
    "returnvalueifnotindirect",
    'slot:LLVMValueRef=build_entry_alloca(builder,llvm_type_of(value_type,structs,ctx),"byval.arg")',
    "_=LLVMBuildStore(builder,value,slot)",
    "returnslot",
)
if any(part not in body for part in ordered) or [body.index(part) for part in ordered] != sorted(body.index(part) for part in ordered):
    raise SystemExit("indirect aggregate materialization must pass through or allocate, store, then return the slot")
if args.source_only:
    print(f"source_bound=True positive={len(POSITIVE_HASHES)} false_controls={len(NEGATIVE_HASHES)}")
    raise SystemExit(0)
product = require_current_product(BIN, PROVER)
if product.get("compile_mode") != "strict":
    raise SystemExit("indirect aggregate ABI proof requires strict Elisa-Proof build")
inputs = list(dict.fromkeys([BIN, BIN.with_name(BIN.name + ".manifest.json"), BIN.with_name(BIN.name + ".manifest.json.sha256"), PROVER / "ELISA_COMPILER_REV", Path(__file__), HERE / "proof_product_gate.py", SOURCE, POSITIVE, NEGATIVE, *source_include_closure([POSITIVE, NEGATIVE])]))
before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
def run(path: Path):
    result = subprocess.run([str(BIN), "--json", str(path)], capture_output=True, text=True, timeout=60)
    return result.returncode, json.loads(result.stdout)
code, positive = run(POSITIVE)
if code or positive.get("status") != "proved" or positive.get("summary", {}).get("proven") != positive.get("summary", {}).get("obligations"):
    raise SystemExit("indirect aggregate argument obligations did not fully prove")
code, negative = run(NEGATIVE)
if code != 1 or negative.get("status") != "failed" or {finding.get("name") for finding in negative.get("findings", [])} != set(NEGATIVE_HASHES) or not all(finding.get("kind") == "ensure-unproven" and finding.get("status") in ("unknown", "disproved") for finding in negative.get("findings", [])):
    raise SystemExit("indirect aggregate false controls were not rejected")
if {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs} != before:
    raise SystemExit("indirect aggregate proof inputs changed during replay")
print(json.dumps({"proved": positive["summary"]["proven"], "false_controls_rejected": len(NEGATIVE_HASHES), "source_bound": True}))
