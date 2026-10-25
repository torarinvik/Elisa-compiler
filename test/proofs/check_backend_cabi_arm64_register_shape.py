"""Bind arm64 C ABI register-shape proofs to argument and return LLVM plans."""
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
POSITIVE = HERE / "backend_cabi_arm64_register_shape.elisa"
NEGATIVE = HERE / "backend_cabi_arm64_register_shape_rejected.elisa"
POSITIVE_HASHES = {
    "arm64_aggregate_register_shape": "3220980a5f5b6cf412f1301b76ab747ea47ea86eebe51341298abc372d251131",
    "arm64_eight_byte_nonhfa_shape": "28265dcfb82dc7f3a522467576a26a0372c2ee7ab4941b3fe3eccf532f651132",
    "arm64_sixteen_byte_nonhfa_shape": "7212688149543627b554e2bfb35af3ace04e74784e4fe0229a433b2b09dfd9d8",
    "arm64_seventeen_byte_nonhfa_shape": "3da80d33bc279c2533f9d45289df16e032cd499f19e18745007264b4c49516ac",
    "arm64_large_hfa_shape": "c28a826323724b986183dfccf59c7a682794523889f510e573ab86560318789c",
}
NEGATIVE_HASHES = {
    "false_seventeen_bytes_use_two_registers": "1734d6b65d704772ab26ee38718625edd49f1e6e7ce79294a85c79819eb53152",
    "false_large_hfa_uses_indirect_shape": "a15c2d5dbdef677a49ee7ee87c33215a7705f7b020d0dd1e352dac4fc0299c93",
    "false_sixteen_bytes_use_sret": "be5832bf5cb47983474f4210fc1ed186540c5891031f86ed5dc105a3cb6d7e3b",
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
if not NEGATIVE.read_text().startswith('include "./backend_cabi_arm64_register_shape.elisa"'):
    raise SystemExit("false controls must import the arm64 shape model")
source_text = SOURCE.read_text()
argument = compact(section(source_text, "cabi_classify_arg"))
argument_steps = (
    "iftarget==0:",
    "hfa:usize=cabi_hfa_count(leaves)",
    "hfa_parts:darray[LLVMTypeRef]=[LLVMArrayType(cabi_leaf_type(leaves[0],ctx),hfa.u32())]",
    "ifsize<=8:",
    "i64_parts:darray[LLVMTypeRef]=[LLVMInt64TypeInContext(ctx)]",
    "ifsize<=16:",
    "pair_parts:darray[LLVMTypeRef]=[LLVMArrayType(LLVMInt64TypeInContext(ctx),2)]",
    "returnCabiArgPlan{direct:false,byval:false,aggregate:true,parts:no_parts,offsets:no_offsets,value_type:llvm_value}",
)
if any(part not in argument for part in argument_steps) or [argument.index(part) for part in argument_steps] != sorted(argument.index(part) for part in argument_steps):
    raise SystemExit("arm64 argument HFA/integer/pair/indirect representations changed")
returned = compact(section(source_text, "cabi_classify_ret_llvm"))
return_steps = (
    "iftarget==0:",
    "returnCabiRetPlan{direct:true,sret:false,ret_type:llvm_value,value_type:llvm_value}ifcabi_hfa_count(leaves)>0",
    "returnCabiRetPlan{direct:true,sret:false,ret_type:LLVMIntTypeInContext(ctx,(size*8).u32()),value_type:llvm_value}ifsize<=8",
    "returnCabiRetPlan{direct:true,sret:false,ret_type:LLVMArrayType(LLVMInt64TypeInContext(ctx),2),value_type:llvm_value}ifsize<=16",
)
if any(part not in returned for part in return_steps) or [returned.index(part) for part in return_steps] != sorted(returned.index(part) for part in return_steps):
    raise SystemExit("arm64 return HFA/scalar/pair representations changed")
size16_position = returned.index(return_steps[-1])
if returned.find("returnCabiRetPlan{direct:false,sret:true,ret_type:llvm_value,value_type:llvm_value}", size16_position) < 0:
    raise SystemExit("arm64 return above sixteen bytes must use sret")
if args.source_only:
    print(f"source_bound=True positive={len(POSITIVE_HASHES)} false_controls={len(NEGATIVE_HASHES)}")
    raise SystemExit(0)
product = require_current_product(BIN, PROVER)
if product.get("compile_mode") != "strict":
    raise SystemExit("arm64 register-shape proof requires strict Elisa-Proof build")
inputs = list(dict.fromkeys([BIN, BIN.with_name(BIN.name + ".manifest.json"), BIN.with_name(BIN.name + ".manifest.json.sha256"), PROVER / "ELISA_COMPILER_REV", Path(__file__), HERE / "proof_product_gate.py", SOURCE, POSITIVE, NEGATIVE, *source_include_closure([POSITIVE, NEGATIVE])]))
before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
def run(path: Path):
    result = subprocess.run([str(BIN), "--json", str(path)], capture_output=True, text=True, timeout=60)
    return result.returncode, json.loads(result.stdout)
code, positive = run(POSITIVE)
if code or positive.get("status") != "proved" or positive.get("summary", {}).get("proven") != positive.get("summary", {}).get("obligations") or positive.get("summary", {}).get("semantic_diagnostics"):
    raise SystemExit("arm64 register-shape obligations did not fully prove cleanly")
code, negative = run(NEGATIVE)
if code != 1 or negative.get("status") != "failed" or {finding.get("name") for finding in negative.get("findings", [])} != set(NEGATIVE_HASHES) or not all(finding.get("kind") == "ensure-unproven" and finding.get("status") in ("unknown", "disproved") for finding in negative.get("findings", [])):
    raise SystemExit("arm64 representation false controls were not rejected")
if {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs} != before:
    raise SystemExit("arm64 register-shape proof inputs changed during replay")
print(json.dumps({"proved": positive["summary"]["proven"], "false_controls_rejected": len(NEGATIVE_HASHES), "source_bound": True}))
