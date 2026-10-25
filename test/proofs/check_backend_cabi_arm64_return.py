"""Bind arm64 C ABI aggregate return proofs to classifier and export wrapper."""
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
CLASSIFIER = ROOT / "src/backend/codegen_c_abi.elisa"
WRAPPER = ROOT / "src/backend/codegen_export_wrappers.elisa"
POSITIVE = HERE / "backend_cabi_arm64_return.elisa"
NEGATIVE = HERE / "backend_cabi_arm64_return_rejected.elisa"
POSITIVE_HASHES = {
    "arm64_aggregate_return_uses_sret": "984e58896a7d0c87ba98e257980cab73874227b5fe1e708ea44ddf1180a3f3af",
    "arm64_eight_byte_nonhfa_return_is_direct": "66395966aa0dff68afe3398a012b2e398a8f8b92a62685caf32e811bea4cc204",
    "arm64_sixteen_byte_nonhfa_return_is_direct": "045eb1890a2f45029bd136009da281b85221c7e447d7024e97eb573b73c4335a",
    "arm64_over_sixteen_nonhfa_return_uses_sret": "e55a84af5c1ec47f3d0752b26f42d9e1f5c3c6cab9992a7773b5920a103f97ba",
    "arm64_hfa_return_stays_direct": "f52b2f5ecbe5a87c60b30cd1f26a282cf6c055e120788ea4fbbd0b300afba81a",
    "arm64_empty_aggregate_return_does_not_use_sret": "8100c1467bbc423244d11d4a0857069fee422a0d89a11d77fa4a29a06fd6187f",
}
NEGATIVE_HASHES = {
    "false_large_nonhfa_return_is_direct": "c53fa4b9448d607ac8680cc2053fb363a3c595739af4b32f7d3f8902cdf1a967",
    "false_large_hfa_return_uses_sret": "4134bee8cb230536c53a160e0b2378161d7e4eda75fb30cabf01ac5bceae65fc",
    "false_unflattenable_return_is_direct": "d4a2c8e81f46d2906b885c2201d6df830bb123a2240f622005a81c1c859c1ec9",
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
if not NEGATIVE.read_text().startswith('include "./backend_cabi_arm64_return.elisa"'):
    raise SystemExit("false controls must import the arm64 return model")
classifier = compact(section(CLASSIFIER.read_text(), "cabi_classify_ret_llvm"))
ordered = (
    "returnCabiRetPlan{direct:true,sret:false,ret_type:llvm_value,value_type:llvm_value}ifnotret_is_aggregate",
    "returnCabiRetPlan{direct:true,sret:false,ret_type:llvm_value,value_type:llvm_value}ifsize==0",
    "flat_ok:bool=cabi_flatten(llvm_value,0,leaves,structs)",
    "returnCabiRetPlan{direct:false,sret:true,ret_type:llvm_value,value_type:llvm_value}ifflat_ok==false",
    "target:i32=cabi_target(structs)",
    "iftarget==0:",
    "returnCabiRetPlan{direct:true,sret:false,ret_type:llvm_value,value_type:llvm_value}ifcabi_hfa_count(leaves)>0",
    "returnCabiRetPlan{direct:true,sret:false,ret_type:LLVMIntTypeInContext(ctx,(size*8).u32()),value_type:llvm_value}ifsize<=8",
    "returnCabiRetPlan{direct:true,sret:false,ret_type:LLVMArrayType(LLVMInt64TypeInContext(ctx),2),value_type:llvm_value}ifsize<=16",
)
if any(part not in classifier for part in ordered) or [classifier.index(part) for part in ordered] != sorted(classifier.index(part) for part in ordered):
    raise SystemExit("arm64 return classifier no longer matches HFA and size branches")
size16_position = classifier.index("returnCabiRetPlan{direct:true,sret:false,ret_type:LLVMArrayType(LLVMInt64TypeInContext(ctx),2),value_type:llvm_value}ifsize<=16")
if classifier.find("returnCabiRetPlan{direct:false,sret:true,ret_type:llvm_value,value_type:llvm_value}", size16_position) < 0:
    raise SystemExit("arm64 aggregate returns above sixteen bytes must use sret")
wrapper = compact(section(WRAPPER.read_text(), "emit_export_wrapper_to"))
if "llvm_param_cursor:mutableu32=1ifexport_ret_plan.sretelse0" not in wrapper:
    raise SystemExit("export wrapper must reserve the leading sret parameter")
sret_branch = wrapper[wrapper.find("elifexport_ret_plan.sret:"):]
sret_steps = ("LLVMBuildStore(builder,call_result,LLVMGetParam(fn,0))", "LLVMBuildRetVoid(builder)")
if any(part not in sret_branch for part in sret_steps) or [sret_branch.index(part) for part in sret_steps] != sorted(sret_branch.index(part) for part in sret_steps):
    raise SystemExit("sret wrapper must store through the leading pointer and return void")
if 'elifcabi_is_aggregate(export_ret_declared)andexport_ret_plan.ret_type!=export_ret_plan.value_type:' not in wrapper or 'LLVMBuildRet(builder,LLVMBuildLoad2(builder,export_ret_plan.ret_type,export_ret_slot,"export.ret"))' not in wrapper:
    raise SystemExit("direct lowered aggregate returns must be converted to the ABI return type")
if args.source_only:
    print(f"source_bound=True positive={len(POSITIVE_HASHES)} false_controls={len(NEGATIVE_HASHES)}")
    raise SystemExit(0)
product = require_current_product(BIN, PROVER)
if product.get("compile_mode") != "strict":
    raise SystemExit("arm64 C ABI return proof requires strict Elisa-Proof build")
inputs = list(dict.fromkeys([BIN, BIN.with_name(BIN.name + ".manifest.json"), BIN.with_name(BIN.name + ".manifest.json.sha256"), PROVER / "ELISA_COMPILER_REV", Path(__file__), HERE / "proof_product_gate.py", CLASSIFIER, WRAPPER, POSITIVE, NEGATIVE, *source_include_closure([POSITIVE, NEGATIVE])]))
before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
def run(path: Path):
    result = subprocess.run([str(BIN), "--json", str(path)], capture_output=True, text=True, timeout=60)
    return result.returncode, json.loads(result.stdout)
code, positive = run(POSITIVE)
if code or positive.get("status") != "proved" or positive.get("summary", {}).get("proven") != positive.get("summary", {}).get("obligations") or positive.get("summary", {}).get("semantic_diagnostics"):
    raise SystemExit("arm64 return obligations did not fully prove cleanly")
code, negative = run(NEGATIVE)
if code != 1 or negative.get("status") != "failed" or {finding.get("name") for finding in negative.get("findings", [])} != set(NEGATIVE_HASHES) or not all(finding.get("kind") == "ensure-unproven" and finding.get("status") in ("unknown", "disproved") for finding in negative.get("findings", [])):
    raise SystemExit("arm64 return false controls were not rejected")
if {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs} != before:
    raise SystemExit("arm64 return proof inputs changed during replay")
print(json.dumps({"proved": positive["summary"]["proven"], "false_controls_rejected": len(NEGATIVE_HASHES), "source_bound": True}))
