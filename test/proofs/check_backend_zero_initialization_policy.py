"""Bind zero-initialization policy proofs to backend memset selection."""
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
POSITIVE = HERE / "backend_zero_initialization_policy.elisa"
EXPECTED = {
    "large_bytewise_value_uses_memset": "643e5609ddeb764b57fb14e009ab1e81c0981832670cce8a5a2b78a44dbb4fce",
    "small_bytewise_value_uses_store": "0001b2d1da8c136bac57b6b18e1c9ef59da396968f5be9d037ee96f7b7b1db89",
    "large_nonbytewise_value_uses_store": "db2ff777a2e06f210de1fedff69b8fa9550654ea89dc11eaba134e94193a08a6",
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
source = SOURCE.read_text()
emit = compact(section(source, "emit_zero_value_to_slot"))
if "ifvalue_size>=256andvalue_type_zero_is_bytewise(value_type,structs)" not in emit:
    raise SystemExit("memset selection no longer requires the 256-byte threshold and safe type predicate")
if "LLVMBuildMemSet" not in emit or "LLVMBuildStore(builder,LLVMConstNull(value_llvm_type),slot)" not in emit:
    raise SystemExit("zero initialization must retain memset and LLVM null-store paths")
safe = compact(section(source, "value_type_zero_is_bytewise"))
for required in (
    "value_type.kind==TypeKind.Signedorvalue_type.kind==TypeKind.Unsignedorvalue_type.kind==TypeKind.Boolorvalue_type.kind==TypeKind.Float",
    "returnvalue_type_zero_is_bytewise(structs.interned_types.array_elements[array_slot],structs)",
    "returnfalseifarray_slot>=structs.interned_types.array_elements.count",
    "returnfalseifstruct_slot>=structs.records.field_count.count",
    "returnfalseifnotvalue_type_zero_is_bytewise(field_type,structs)",
    "returntrue",
    "returnfalse",
):
    if required not in safe: raise SystemExit("safe-zero type classification or bounds guard changed")
if args.source_only:
    print("source_bound=True threshold=256 positive=3")
    raise SystemExit(0)
product = require_current_product(BIN, PROVER)
if product.get("compile_mode") != "strict": raise SystemExit("zero initialization proof requires strict Elisa-Proof build")
inputs = list(dict.fromkeys([BIN, BIN.with_name(BIN.name + ".manifest.json"), BIN.with_name(BIN.name + ".manifest.json.sha256"), PROVER / "ELISA_COMPILER_REV", Path(__file__), HERE / "proof_product_gate.py", SOURCE, POSITIVE, *source_include_closure([POSITIVE])]))
before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
result = subprocess.run([str(BIN), "--json", str(POSITIVE)], capture_output=True, text=True, timeout=60)
report = json.loads(result.stdout)
if result.returncode or report.get("status") != "proved" or report.get("summary", {}).get("proven") != report.get("summary", {}).get("obligations") or report.get("replay", {}).get("gaps") != 0:
    raise SystemExit("zero initialization policy proof did not fully replay")
if {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs} != before:
    raise SystemExit("zero initialization proof inputs changed during replay")
print(json.dumps({"proved": report["summary"]["proven"], "source_bound": True, "replay_gaps": 0}))
