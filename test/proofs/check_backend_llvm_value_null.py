"""Bind LLVM null-handle distinction proofs to the backend helper."""
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
POSITIVE = HERE / "backend_llvm_value_null.elisa"
EXPECTED = {
    "absent_handle_is_null": "cc7e7bf42809ea5dd5c7d29ef3e7b9d721e0f6dc68dfa1148ec02df2ea528120",
    "live_llvm_null_is_null": "7bceb7939bcd3ecfd17dbba5badaf0ef7a61548d4e602faaea3a6d4ada32364c",
    "live_nonnull_handle_is_not_null": "fa4c463d18745a311ebc21a575c16784f469ed0c5e774aa1f3b2dbd4b2beedd6",
}
def compact(text: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in text.splitlines())
def section(text: str, name: str) -> str:
    match = re.search(rf"(?m)^[ \t]*def {re.escape(name)}\(", text)
    if not match: raise SystemExit(f"missing {name}")
    following = re.search(r"(?m)^[ \t]*def [A-Za-z_]\w*\(", text[match.end():])
    return text[match.start():match.end() + following.start() if following else len(text)]
proof = POSITIVE.read_text()
for name, digest in EXPECTED.items():
    if hashlib.sha256(compact(section(proof, name)).encode()).hexdigest() != digest:
        raise SystemExit(f"{name} proof changed since source binding")
body = compact(section(SOURCE.read_text(), "llvm_value_is_null"))
if "returntrueifvalue==zeroed" not in body or "returnLLVMIsNull(value)!=0" not in body:
    raise SystemExit("LLVM null check must recognize absent handles and live LLVM null constants")
if body.index("returntrueifvalue==zeroed") > body.index("returnLLVMIsNull(value)!=0"):
    raise SystemExit("absent handle must be handled before querying LLVM")
if args.source_only:
    print("source_bound=True cases=3")
    raise SystemExit(0)
product = require_current_product(BIN, PROVER)
if product.get("compile_mode") != "strict": raise SystemExit("LLVM null proof requires strict Elisa-Proof build")
inputs = list(dict.fromkeys([BIN, BIN.with_name(BIN.name + ".manifest.json"), BIN.with_name(BIN.name + ".manifest.json.sha256"), PROVER / "ELISA_COMPILER_REV", Path(__file__), HERE / "proof_product_gate.py", SOURCE, POSITIVE, *source_include_closure([POSITIVE])]))
before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
result = subprocess.run([str(BIN), "--json", str(POSITIVE)], capture_output=True, text=True, timeout=60)
report = json.loads(result.stdout)
if result.returncode or report.get("status") != "proved" or report.get("summary", {}).get("proven") != report.get("summary", {}).get("obligations") or report.get("replay", {}).get("gaps") != 0:
    raise SystemExit("LLVM null distinction proof did not fully replay")
if {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs} != before:
    raise SystemExit("LLVM null proof inputs changed during replay")
print(json.dumps({"proved": report["summary"]["proven"], "source_bound": True, "replay_gaps": 0}))
