"""Bind C ABI scalar leaf kind proofs to flattening and leaf type reconstruction."""
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
POSITIVE = HERE / "backend_cabi_leaf_kind.elisa"
NEGATIVE = HERE / "backend_cabi_leaf_kind_rejected.elisa"
POSITIVE_HASHES = {
    "cabi_scalar_leaf_class": "b3ae1331bd4985cd2caf518f427cf2a097118644143bd0694c07e0fa9de98c70",
    "llvm_float_leaf_maps_to_float_class": "de014da07ad3f6e3d848c3fb21953da5b19ea54b1218d5a81743bc83a4245d2e",
    "llvm_double_leaf_maps_to_double_class": "a92c2a28d48fa20221e943d4cc0d20d90c04a992ca4f5a2bafc06a4c6ad40153",
    "integer_or_pointer_leaf_maps_to_integer_class": "b34b988a3d89b3cceabca1f3f2c53848a774002edc07617dd78a5c31f4811311",
    "unsupported_scalar_kind_is_rejected": "4d92ae83618653e09813b064296a85427f5212523f85e6e943d9b20cb746a1e5",
}
NEGATIVE_HASHES = {
    "false_llvm_half_is_supported_leaf": "f47cce8348f95607a6c1ff24baf01a32c101f9c0fc010c3d5d3e0aa3336f78aa",
    "false_x86_fp80_is_supported_leaf": "d63293794a38e2bf9772a90c67bc99ac9a4054c3c58f41fe3ebb6734f8b14575",
    "false_struct_kind_is_supported_scalar_leaf": "134e177f2c7d3d5fbf0dfeb3147b478edbc997d2753c52b54562525c2c3142a4",
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
if not NEGATIVE.read_text().startswith('include "./backend_cabi_leaf_kind.elisa"'):
    raise SystemExit("false controls must import the leaf-kind policy")
source_text = SOURCE.read_text()
flatten = compact(section(source_text, "cabi_flatten"))
flatten_steps = (
    "ifkind==2:leaves.push(CabiLeaf{offset:base,size:4,kind:1})",
    "ifkind==3:leaves.push(CabiLeaf{offset:base,size:8,kind:2})",
    "ifkind==8orkind==12:leaves.push(CabiLeaf{offset:base,size:LLVMABISizeOfType(structs.target.target_data,ty),kind:0})",
    "returnfalse",
)
if any(part not in flatten for part in flatten_steps) or [flatten.index(part) for part in flatten_steps] != sorted(flatten.index(part) for part in flatten_steps):
    raise SystemExit("C ABI flattener scalar-kind mapping or unsupported-kind rejection changed")
leaf_type = compact(section(source_text, "cabi_leaf_type"))
type_steps = (
    "LLVMFloatTypeInContext(ctx)returnifleaf.kind==1",
    "LLVMDoubleTypeInContext(ctx)returnifleaf.kind==2",
    "returnLLVMIntTypeInContext(ctx,(leaf.size*8).u32())",
)
if any(part not in leaf_type for part in type_steps) or [leaf_type.index(part) for part in type_steps] != sorted(leaf_type.index(part) for part in type_steps):
    raise SystemExit("C ABI leaf kind reconstruction no longer matches the flattening codes")
if args.source_only:
    print(f"source_bound=True positive={len(POSITIVE_HASHES)} false_controls={len(NEGATIVE_HASHES)}")
    raise SystemExit(0)
product = require_current_product(BIN, PROVER)
if product.get("compile_mode") != "strict":
    raise SystemExit("C ABI leaf-kind proof requires strict Elisa-Proof build")
inputs = list(dict.fromkeys([BIN, BIN.with_name(BIN.name + ".manifest.json"), BIN.with_name(BIN.name + ".manifest.json.sha256"), PROVER / "ELISA_COMPILER_REV", Path(__file__), HERE / "proof_product_gate.py", SOURCE, POSITIVE, NEGATIVE, *source_include_closure([POSITIVE, NEGATIVE])]))
before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
def run(path: Path):
    result = subprocess.run([str(BIN), "--json", str(path)], capture_output=True, text=True, timeout=60)
    return result.returncode, json.loads(result.stdout)
code, positive = run(POSITIVE)
if code or positive.get("status") != "proved" or positive.get("summary", {}).get("proven") != positive.get("summary", {}).get("obligations") or positive.get("summary", {}).get("semantic_diagnostics"):
    raise SystemExit("C ABI leaf-kind obligations did not fully prove cleanly")
code, negative = run(NEGATIVE)
if code != 1 or negative.get("status") != "failed" or {finding.get("name") for finding in negative.get("findings", [])} != set(NEGATIVE_HASHES) or not all(finding.get("kind") == "ensure-unproven" and finding.get("status") in ("unknown", "disproved") for finding in negative.get("findings", [])):
    raise SystemExit("unsupported C ABI leaf-kind controls were not rejected")
if {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs} != before:
    raise SystemExit("C ABI leaf-kind proof inputs changed during replay")
print(json.dumps({"proved": positive["summary"]["proven"], "false_controls_rejected": len(NEGATIVE_HASHES), "source_bound": True}))
