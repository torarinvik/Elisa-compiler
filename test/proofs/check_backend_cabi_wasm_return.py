"""Bind wasm C ABI aggregate return proofs to classifier and export wrapper."""
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
POSITIVE = HERE / "backend_cabi_wasm_return.elisa"
NEGATIVE = HERE / "backend_cabi_wasm_return_rejected.elisa"
POSITIVE_HASHES = {
    "wasm_aggregate_return_uses_sret": "1dcf3d51216aaebc161752c64ad5504540fb63604d9226474178799310b2d3a3",
    "wasm_single_leaf_aggregate_returns_directly": "de49c10586128c917092fd75e487d73a2f31015ebd1332f9aead8d6b70ecad4a",
    "wasm_multiple_leaf_aggregate_uses_sret": "560d4817a5c2ae2bd0575655181d364685ae1a03feccc0be65b20a149daba248",
    "wasm_unflattenable_aggregate_uses_sret": "008579294086e9dd1d136d91f9d4d4fc33aedd07707d9800a7d6c8ba8e4ad358",
    "wasm_zero_sized_aggregate_does_not_use_sret": "92d7467c96194c3ee3dafc2fde6533150aaae9610bc4a0e43d66771b606b76e6",
}
NEGATIVE_HASHES = {
    "false_multiple_leaf_aggregate_returns_directly": "1c4fe7efb3b7a0ed37d53fbd56676fe8880ddd2107eebbfa84b8b145da72f83f",
    "false_unflattenable_aggregate_returns_directly": "1f4c52dfd6ed9fb10376805893b8200961b75a99ef83042adf05eef413c4d37d",
    "false_zero_sized_aggregate_uses_sret": "22b9e01598b40b143aed7911894fad56f313502d17d4d0751ce58e7a11cdecfa",
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
if not NEGATIVE.read_text().startswith('include "./backend_cabi_wasm_return.elisa"'):
    raise SystemExit("false controls must import the wasm return policy")
classifier = compact(section(CLASSIFIER.read_text(), "cabi_classify_ret_llvm"))
ordered = (
    "returnCabiRetPlan{direct:true,sret:false,ret_type:llvm_value,value_type:llvm_value}ifnotret_is_aggregate",
    "returnCabiRetPlan{direct:true,sret:false,ret_type:llvm_value,value_type:llvm_value}ifsize==0",
    "flat_ok:bool=cabi_flatten(llvm_value,0,leaves,structs)",
    "returnCabiRetPlan{direct:false,sret:true,ret_type:llvm_value,value_type:llvm_value}ifflat_ok==false",
    "target:i32=cabi_target(structs)",
    "iftarget==2:",
    "returnCabiRetPlan{direct:true,sret:false,ret_type:cabi_leaf_type(leaves[0],ctx),value_type:llvm_value}ifleaves.count==1",
)
if any(part not in classifier for part in ordered) or [classifier.index(part) for part in ordered] != sorted(classifier.index(part) for part in ordered):
    raise SystemExit("wasm return classifier no longer matches zero-size, flatten, and single-leaf rules")
wasm_sret = "returnCabiRetPlan{direct:false,sret:true,ret_type:llvm_value,value_type:llvm_value}"
if classifier.rfind(wasm_sret) <= classifier.index(ordered[-1]):
    raise SystemExit("wasm aggregate returns with multiple leaves must use sret")
wrapper = compact(section(WRAPPER.read_text(), "emit_export_wrapper_to"))
wrapper_steps = (
    "llvm_param_cursor:mutableu32=1ifexport_ret_plan.sretelse0",
    "elifexport_ret_plan.sret:",
    "LLVMBuildStore(builder,call_result,LLVMGetParam(fn,0))",
    "LLVMBuildRetVoid(builder)",
)
sret_branch = wrapper[wrapper.find("elifexport_ret_plan.sret:"):]
if any(part not in sret_branch for part in wrapper_steps[1:]) or [sret_branch.index(part) for part in wrapper_steps[1:]] != sorted(sret_branch.index(part) for part in wrapper_steps[1:]) or wrapper_steps[0] not in wrapper:
    raise SystemExit("export sret wrapper must reserve the leading pointer, store result there, and return void")
if args.source_only:
    print(f"source_bound=True positive={len(POSITIVE_HASHES)} false_controls={len(NEGATIVE_HASHES)}")
    raise SystemExit(0)
product = require_current_product(BIN, PROVER)
if product.get("compile_mode") != "strict":
    raise SystemExit("wasm C ABI return proof requires strict Elisa-Proof build")
inputs = list(dict.fromkeys([BIN, BIN.with_name(BIN.name + ".manifest.json"), BIN.with_name(BIN.name + ".manifest.json.sha256"), PROVER / "ELISA_COMPILER_REV", Path(__file__), HERE / "proof_product_gate.py", CLASSIFIER, WRAPPER, POSITIVE, NEGATIVE, *source_include_closure([POSITIVE, NEGATIVE])]))
before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
def run(path: Path):
    result = subprocess.run([str(BIN), "--json", str(path)], capture_output=True, text=True, timeout=60)
    return result.returncode, json.loads(result.stdout)
code, positive = run(POSITIVE)
if code or positive.get("status") != "proved" or positive.get("summary", {}).get("proven") != positive.get("summary", {}).get("obligations") or positive.get("summary", {}).get("semantic_diagnostics"):
    raise SystemExit("wasm return obligations did not fully prove cleanly")
code, negative = run(NEGATIVE)
if code != 1 or negative.get("status") != "failed" or {finding.get("name") for finding in negative.get("findings", [])} != set(NEGATIVE_HASHES) or not all(finding.get("kind") == "ensure-unproven" and finding.get("status") in ("unknown", "disproved") for finding in negative.get("findings", [])):
    raise SystemExit("wasm return false controls were not rejected")
if {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs} != before:
    raise SystemExit("wasm return proof inputs changed during replay")
print(json.dumps({"proved": positive["summary"]["proven"], "false_controls_rejected": len(NEGATIVE_HASHES), "source_bound": True}))
