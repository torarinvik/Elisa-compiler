"""Bind x86-64 C aggregate return proofs to classifier and extern declaration."""
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
DECLARATION = ROOT / "src/backend/codegen_declare_extern.elisa"
POSITIVE = HERE / "backend_cabi_x86_return_sret.elisa"
NEGATIVE = HERE / "backend_cabi_x86_return_sret_rejected.elisa"
POSITIVE_HASHES = {
    "x86_aggregate_return_uses_sret": "37ec81dcc6b3a68c2dbce31320703a708860b41a4373112e64c95f7ddf6205d7",
    "two_eightbyte_aggregate_returns_directly": "691fdceac2e05a8802e7371140d5e8736962aad7202298f5e0fc0bea34dda999",
    "aggregate_over_two_eightbytes_uses_sret": "a5b4c7bb128b965c739b5ff847684ecbee26cee7d667082be0cfd0965d5dbe48",
    "unflattenable_aggregate_uses_sret": "e4007033cf9e0d42afe42cf7f306e371ad1b6ec0d43d7cb3faadb313e74e610f",
}
NEGATIVE_HASHES = {
    "false_two_eightbyte_aggregate_uses_sret": "d06e85d6efbba44f2c84a9b682364a4f7411f1ea6fd9be9f4de7e98ea8f7af5a",
    "false_large_x86_aggregate_returns_directly": "de51f8974883607b24376460307504e6a7467f3124bbf0a5dbe5ad447b40f8c5",
    "false_unflattenable_aggregate_returns_directly": "8295f47b74e9397f15b5b16b469062e68f07465826478f133fc9858195b665bf",
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
if not NEGATIVE.read_text().startswith('include "./backend_cabi_x86_return_sret.elisa"'):
    raise SystemExit("false controls must import the x86 C return model")
classifier = compact(section(CLASSIFIER.read_text(), "cabi_classify_ret_llvm"))
ordered = (
    "CabiRetPlan{direct:true,sret:false,ret_type:llvm_value,value_type:llvm_value}returnifnotret_is_aggregate",
    "CabiRetPlan{direct:true,sret:false,ret_type:llvm_value,value_type:llvm_value}returnifsize==0",
    "flat_ok:bool=cabi_flatten(llvm_value,0,leaves,structs)",
    "CabiRetPlan{direct:false,sret:true,ret_type:llvm_value,value_type:llvm_value}returnifflat_ok==false",
    "target:i32=cabi_target(structs)",
    "iftarget==2:",
    "iftarget==0:",
    "CabiRetPlan{direct:false,sret:true,ret_type:llvm_value,value_type:llvm_value}returnifsize>16",
)
if any(part not in classifier for part in ordered) or [classifier.index(part) for part in ordered] != sorted(classifier.index(part) for part in ordered):
    raise SystemExit("C ABI return classification no longer matches aggregate, flatten, target, and x86 size policy")
declare = compact(section(DECLARATION.read_text(), "declare_extern"))
declare_steps = (
    "extern_error_ret_plan:CabiRetPlan=cabi_classify_ret_llvm(extern_error_llvm,true,structs,ctx)",
    "ifextern_error_ret_plan.sret:",
    "llvm_return<-LLVMVoidTypeInContext(ctx)",
    "extern_error_sret<-true",
    "error_sret_params:mutabledarray[LLVMTypeRef]=[LLVMPointerTypeInContext(ctx,0)]",
    "error_sret_params.extend(extern_param_types)",
    "extern_param_types<-error_sret_params",
)
if any(part not in declare for part in declare_steps) or [declare.index(part) for part in declare_steps] != sorted(declare.index(part) for part in declare_steps):
    raise SystemExit("extern payload-error sret must use void return and prepend one pointer")
if args.source_only:
    print(f"source_bound=True positive={len(POSITIVE_HASHES)} false_controls={len(NEGATIVE_HASHES)}")
    raise SystemExit(0)
product = require_current_product(BIN, PROVER)
if product.get("compile_mode") != "strict":
    raise SystemExit("C ABI return proof requires strict Elisa-Proof build")
inputs = list(dict.fromkeys([BIN, BIN.with_name(BIN.name + ".manifest.json"), BIN.with_name(BIN.name + ".manifest.json.sha256"), PROVER / "ELISA_COMPILER_REV", Path(__file__), HERE / "proof_product_gate.py", CLASSIFIER, DECLARATION, POSITIVE, NEGATIVE, *source_include_closure([POSITIVE, NEGATIVE])]))
before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
def run(path: Path):
    result = subprocess.run([str(BIN), "--json", str(path)], capture_output=True, text=True, timeout=60)
    return result.returncode, json.loads(result.stdout)
code, positive = run(POSITIVE)
if code or positive.get("status") != "proved" or positive.get("summary", {}).get("proven") != positive.get("summary", {}).get("obligations"):
    raise SystemExit("x86 C return obligations did not fully prove")
code, negative = run(NEGATIVE)
if code != 1 or negative.get("status") != "failed" or {finding.get("name") for finding in negative.get("findings", [])} != set(NEGATIVE_HASHES) or not all(finding.get("kind") == "ensure-unproven" and finding.get("status") in ("unknown", "disproved") for finding in negative.get("findings", [])):
    raise SystemExit("x86 C return false controls were not rejected")
if {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs} != before:
    raise SystemExit("C ABI return proof inputs changed during replay")
print(json.dumps({"proved": positive["summary"]["proven"], "false_controls_rejected": len(NEGATIVE_HASHES), "source_bound": True}))
