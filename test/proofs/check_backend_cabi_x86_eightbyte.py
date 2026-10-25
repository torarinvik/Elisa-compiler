"""Bind x86-64 eightbyte priority proofs to the LLVM type classifier."""
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
SOURCE = ROOT / "src/backend/codegen_c_abi.elisa"
POSITIVE = HERE / "backend_cabi_x86_eightbyte.elisa"
NEGATIVE = HERE / "backend_cabi_x86_eightbyte_rejected.elisa"
POSITIVE_HASHES = {
    "x86_eightbyte_class": "2f3749df45957eac954857b59418c26e9f3e223450cf693ffc7b12a820039c5f",
    "integer_class_dominates_mixed_leaves": "47792178f23397f34f378dac5ef8df0fb9129349a13c1cd37294da8491f57b32",
    "double_class_dominates_float32_leaves": "814b5404abafbb934ef788eb87aa491896aeb1030e09f036ae1dda334d74e2f4",
    "two_float32_leaves_form_vector": "45aea06e817ae99f94be7ca8e874e4f187aa2ca545b6788e2742a4fec5ef6da9",
}
NEGATIVE_HASHES = {
    "false_integer_loses_to_double": "b620c5284d7b5f43b526579d9c63d5e4d8afa000c7cff3d724db446562e85174",
    "false_double_loses_to_float_vector": "d097035427c35b200c33b8004076218468596b7fcdf6136b1a5642ac60df22b3",
    "false_two_float32_leaves_are_scalar": "efe0bdc669b7353d4503352e0632fbe6d1554b36a11ec3e10a2021d45515b5de",
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
if not NEGATIVE.read_text().startswith('include "./backend_cabi_x86_eightbyte.elisa"'):
    raise SystemExit("false controls must import the x86 eightbyte policy")
body = compact(section(SOURCE.read_text(), "cabi_x86_eightbyte"))
ordered = (
    "lo:u64=eb*8",
    "hi:u64=lo+8",
    "continueifleaves[leaf_index].offset>=hiorleaves[leaf_index].offset+leaves[leaf_index].size<=lo",
    "ints<-ints+1ifleaves[leaf_index].kind==0",
    "f32s<-f32s+1ifleaves[leaf_index].kind==1",
    "f64s<-f64s+1ifleaves[leaf_index].kind==2",
    "found<-ints+f32s+f64s>0",
    "returnLLVMInt64TypeInContext(ctx)ifnotany_leaf",
    "ifints>0:",
    "returnLLVMDoubleTypeInContext(ctx)iff64s>0",
    "returnLLVMVectorType(LLVMFloatTypeInContext(ctx),2)iff32s>=2",
    "returnLLVMFloatTypeInContext(ctx)",
)
if any(part not in body for part in ordered) or [body.index(part) for part in ordered] != sorted(body.index(part) for part in ordered):
    raise SystemExit("x86 eightbyte leaf census or integer/double/vector/float priority changed")
if args.source_only:
    print(f"source_bound=True positive={len(POSITIVE_HASHES)} false_controls={len(NEGATIVE_HASHES)}")
    raise SystemExit(0)
product = require_current_product(BIN, PROVER)
if product.get("compile_mode") != "strict":
    raise SystemExit("x86 eightbyte proof requires strict Elisa-Proof build")
inputs = list(dict.fromkeys([BIN, BIN.with_name(BIN.name + ".manifest.json"), BIN.with_name(BIN.name + ".manifest.json.sha256"), PROVER / "ELISA_COMPILER_REV", Path(__file__), HERE / "proof_product_gate.py", SOURCE, POSITIVE, NEGATIVE, *source_include_closure([POSITIVE, NEGATIVE])]))
before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
def run(path: Path):
    result = subprocess.run([str(BIN), "--json", str(path)], capture_output=True, text=True, timeout=60)
    return result.returncode, json.loads(result.stdout)
code, positive = run(POSITIVE)
if code or positive.get("status") != "proved" or positive.get("summary", {}).get("proven") != positive.get("summary", {}).get("obligations") or positive.get("summary", {}).get("semantic_diagnostics"):
    raise SystemExit("x86 eightbyte obligations did not fully prove cleanly")
code, negative = run(NEGATIVE)
if code != 1 or negative.get("status") != "failed" or {finding.get("name") for finding in negative.get("findings", [])} != set(NEGATIVE_HASHES) or not all(finding.get("kind") == "ensure-unproven" and finding.get("status") in ("unknown", "disproved") for finding in negative.get("findings", [])):
    raise SystemExit("x86 eightbyte priority false controls were not rejected")
if {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs} != before:
    raise SystemExit("x86 eightbyte proof inputs changed during replay")
print(json.dumps({"proved": positive["summary"]["proven"], "false_controls_rejected": len(NEGATIVE_HASHES), "source_bound": True}))
