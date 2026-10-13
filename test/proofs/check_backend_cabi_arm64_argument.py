"""Bind arm64 C ABI aggregate argument proofs to classification and export lowering."""
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
POSITIVE = HERE / "backend_cabi_arm64_argument.elisa"
NEGATIVE = HERE / "backend_cabi_arm64_argument_rejected.elisa"
POSITIVE_HASHES = {
    "arm64_aggregate_argument_is_indirect": "6768847655b1c7beaa93ce4d1586f6da2f0df16eab0b2fd78d4c774efe7a9d6c",
    "arm64_eight_byte_nonhfa_is_direct": "8a3649ee287dde5b9f1a9fb7eb4c558c942e0167233630ddf5a85f1cb7f498a9",
    "arm64_sixteen_byte_nonhfa_is_direct": "2ad95159122a7b8d16b3d7fae627202c192be1ae56abe55478c318a3f806bc2f",
    "arm64_over_sixteen_nonhfa_is_indirect": "d2bb9fcb0b42766defdf6a9a6df1d8ee8a604d987e49c6096935407cae587fd3",
    "arm64_large_hfa_is_still_direct": "65ad682c641d07c22e9286f25296f7ad6271a432d262f1e27c79a2822919d4b1",
    "arm64_empty_aggregate_is_not_indirect": "ac72cfa707c05b3fd151180637af1d03ab3522bf883e6de4f7c0095275f39b07",
}
NEGATIVE_HASHES = {
    "false_large_nonhfa_uses_direct_parts": "fe21bdba9733988ccce92cf00b69d08adc07e4a53b23ccca45d7c3d80e7b813e",
    "false_large_hfa_uses_indirect_pointer": "51577838a409a80118baa7528986c2101028c9301a38ab9e437b01469d31a196",
    "false_unflattenable_aggregate_is_direct": "e705e6cce3ac37217a6e05e7a0f198bdc92912ffb0ce57819a251d3e70d3f170",
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
if not NEGATIVE.read_text().startswith('include "./backend_cabi_arm64_argument.elisa"'):
    raise SystemExit("false controls must import the arm64 argument model")
classifier = compact(section(CLASSIFIER.read_text(), "cabi_classify_arg"))
ordered = (
    "flat_ok:bool=cabi_flatten(llvm_value,0,leaves,structs)",
    "CabiArgPlan{direct:false,byval:true,aggregate:true,parts:no_parts,offsets:no_offsets,value_type:llvm_value}returnifflat_ok==false",
    "iftarget==0:",
    "hfa:usize=cabi_hfa_count(leaves)",
    "ifhfa>0:",
    "ifsize<=8:",
    "ifsize<=16:",
    "returnCabiArgPlan{direct:false,byval:false,aggregate:true,parts:no_parts,offsets:no_offsets,value_type:llvm_value}",
)
if any(part not in classifier for part in ordered) or [classifier.index(part) for part in ordered] != sorted(classifier.index(part) for part in ordered):
    raise SystemExit("arm64 aggregate argument policy or flatten-failure handling changed")
declare = compact(section(DECLARATION.read_text(), "declare_extern"))
declare_steps = (
    "ifextern_is_exportandcabi_is_aggregate(param_value_type):",
    "export_arg_plan:CabiArgPlan=cabi_classify_arg(param_value_type,structs,ctx)",
    "ifexport_arg_plan.direct:",
    "forexport_arg_partinexport_arg_plan.parts|extern_param_types|:extern_param_types.push(export_arg_part)",
    "else:extern_param_types.push(LLVMPointerTypeInContext(ctx,0))",
)
if any(part not in declare for part in declare_steps) or [declare.index(part) for part in declare_steps] != sorted(declare.index(part) for part in declare_steps):
    raise SystemExit("arm64 export arguments must use direct parts or the indirect pointer form")
if args.source_only:
    print(f"source_bound=True positive={len(POSITIVE_HASHES)} false_controls={len(NEGATIVE_HASHES)}")
    raise SystemExit(0)
product = require_current_product(BIN, PROVER)
if product.get("compile_mode") != "strict":
    raise SystemExit("arm64 C ABI argument proof requires strict Elisa-Proof build")
inputs = list(dict.fromkeys([BIN, BIN.with_name(BIN.name + ".manifest.json"), BIN.with_name(BIN.name + ".manifest.json.sha256"), PROVER / "ELISA_COMPILER_REV", Path(__file__), HERE / "proof_product_gate.py", CLASSIFIER, DECLARATION, POSITIVE, NEGATIVE, *source_include_closure([POSITIVE, NEGATIVE])]))
before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
def run(path: Path):
    result = subprocess.run([str(BIN), "--json", str(path)], capture_output=True, text=True, timeout=60)
    return result.returncode, json.loads(result.stdout)
code, positive = run(POSITIVE)
if code or positive.get("status") != "proved" or positive.get("summary", {}).get("proven") != positive.get("summary", {}).get("obligations") or positive.get("summary", {}).get("semantic_diagnostics"):
    raise SystemExit("arm64 argument obligations did not fully prove cleanly")
code, negative = run(NEGATIVE)
if code != 1 or negative.get("status") != "failed" or {finding.get("name") for finding in negative.get("findings", [])} != set(NEGATIVE_HASHES) or not all(finding.get("kind") == "ensure-unproven" and finding.get("status") in ("unknown", "disproved") for finding in negative.get("findings", [])):
    raise SystemExit("arm64 argument false controls were not rejected")
if {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs} != before:
    raise SystemExit("arm64 argument proof inputs changed during replay")
print(json.dumps({"proved": positive["summary"]["proven"], "false_controls_rejected": len(NEGATIVE_HASHES), "source_bound": True}))
