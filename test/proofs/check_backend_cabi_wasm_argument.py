"""Bind wasm C ABI aggregate argument proofs to target-specific plans."""
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
POSITIVE = HERE / "backend_cabi_wasm_argument.elisa"
NEGATIVE = HERE / "backend_cabi_wasm_argument_rejected.elisa"
POSITIVE_HASHES = {
    "wasm_aggregate_argument_is_byval": "8a6b3c6e1dc501deda3df7fd1e051f59807652c02fe267034ef7f4c426e877d3",
    "wasm_one_leaf_aggregate_is_direct": "e8e7bccf50007b21c2fb67483f92b6776587faf6ed40045237c45b9fd0c3f758",
    "wasm_multileaf_aggregate_is_indirect": "de9c4999ef3ae05fe45380cd15f3490e6cd8e2110d507a8e422da41ba1b2db0d",
    "wasm_unflattenable_aggregate_is_indirect": "58615835b94ee0154745b278b1d1427e3a426756301443546a3c991e0353f49b",
    "wasm_zero_sized_aggregate_is_not_byval": "5e8a9807aa9a6835252e2fec91d8cdcd877bb73d9df3bf2958177a018403ab5f",
}
NEGATIVE_HASHES = {
    "false_multileaf_aggregate_is_direct": "7e7af8094d1246a5a5c422a5a848a694563a459479178759df06a85678d07e0f",
    "false_unflattenable_aggregate_is_direct": "e705e6cce3ac37217a6e05e7a0f198bdc92912ffb0ce57819a251d3e70d3f170",
    "false_zero_sized_aggregate_is_byval": "dd2231763dbee42e687d32298ebbc213b1331116318248564c7b1dd70e192ba5",
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
if not NEGATIVE.read_text().startswith('include "./backend_cabi_wasm_argument.elisa"'):
    raise SystemExit("false controls must import the wasm argument policy")
body = compact(section(SOURCE.read_text(), "cabi_classify_arg"))
ordered = (
    "CabiArgPlan{direct:true,byval:false,aggregate:true,parts:scalar_parts,offsets:scalar_offsets,value_type:llvm_value}returnifsize==0",
    "flat_ok:bool=cabi_flatten(llvm_value,0,leaves,structs)",
    "CabiArgPlan{direct:false,byval:true,aggregate:true,parts:no_parts,offsets:no_offsets,value_type:llvm_value}returnifflat_ok==false",
    "iftarget==2:",
    "ifleaves.count==1:",
    "wasm_parts:darray[LLVMTypeRef]=[cabi_leaf_type(leaves[0],ctx)]",
    "wasm_offsets:darray[u64]=[leaves[0].offset]",
    "returnCabiArgPlan{direct:true,byval:false,aggregate:true,parts:wasm_parts,offsets:wasm_offsets,value_type:llvm_value}",
    "returnCabiArgPlan{direct:false,byval:true,aggregate:true,parts:no_parts,offsets:no_offsets,value_type:llvm_value}",
)
if any(part not in body for part in ordered) or [body.index(part) for part in ordered] != sorted(body.index(part) for part in ordered):
    raise SystemExit("wasm aggregate argument rule or zero-size/flatten-failure handling changed")
if args.source_only:
    print(f"source_bound=True positive={len(POSITIVE_HASHES)} false_controls={len(NEGATIVE_HASHES)}")
    raise SystemExit(0)
product = require_current_product(BIN, PROVER)
if product.get("compile_mode") != "strict":
    raise SystemExit("wasm C ABI argument proof requires strict Elisa-Proof build")
inputs = list(dict.fromkeys([BIN, BIN.with_name(BIN.name + ".manifest.json"), BIN.with_name(BIN.name + ".manifest.json.sha256"), PROVER / "ELISA_COMPILER_REV", Path(__file__), HERE / "proof_product_gate.py", SOURCE, POSITIVE, NEGATIVE, *source_include_closure([POSITIVE, NEGATIVE])]))
before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
def run(path: Path):
    result = subprocess.run([str(BIN), "--json", str(path)], capture_output=True, text=True, timeout=60)
    return result.returncode, json.loads(result.stdout)
code, positive = run(POSITIVE)
if code or positive.get("status") != "proved" or positive.get("summary", {}).get("proven") != positive.get("summary", {}).get("obligations") or positive.get("summary", {}).get("semantic_diagnostics"):
    raise SystemExit("wasm argument obligations did not fully prove cleanly")
code, negative = run(NEGATIVE)
if code != 1 or negative.get("status") != "failed" or {finding.get("name") for finding in negative.get("findings", [])} != set(NEGATIVE_HASHES) or not all(finding.get("kind") == "ensure-unproven" and finding.get("status") in ("unknown", "disproved") for finding in negative.get("findings", [])):
    raise SystemExit("wasm argument false controls were not rejected")
if {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs} != before:
    raise SystemExit("wasm argument proof inputs changed during replay")
print(json.dumps({"proved": positive["summary"]["proven"], "false_controls_rejected": len(NEGATIVE_HASHES), "source_bound": True}))
