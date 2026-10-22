"""Bind x86-64 C aggregate argument proofs to classification and export lowering."""
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
POSITIVE = HERE / "backend_cabi_x86_argument_byval.elisa"
NEGATIVE = HERE / "backend_cabi_x86_argument_byval_rejected.elisa"
POSITIVE_HASHES = {
    "x86_aggregate_argument_uses_byval": "9fca7ceeb5fe04fdbd5a5244ac0d0fcad0fcd269b971754d150048e3cbd0bebf",
    "two_eightbyte_aggregate_argument_is_direct": "3bc95ff037b9de3a0f3b48a865f3b1e20e35cd4e995bbe1dc76242544f09575e",
    "aggregate_over_two_eightbytes_argument_uses_byval": "2a385e3f1eb047a698d227db1deff959b9ab358c027eba7550678800ead6f305",
    "unflattenable_aggregate_argument_uses_byval": "c45c793562d743130d05c732b4d1dc2f528c7ab83d8430c2fd89336f9b3aed9d",
}
NEGATIVE_HASHES = {
    "false_two_eightbyte_aggregate_argument_uses_byval": "b4731c8290e4c616bb1eaa47743694c71ab797a1c016e56a2e06a22b8f640a9e",
    "false_large_x86_aggregate_argument_is_direct": "7b720a2d68f6f84695ace11c612ed48c5f6c787b46f8e33b0123d7b9556f992b",
    "false_unflattenable_aggregate_argument_is_direct": "d4ebaebc49b5261f2eb35a3b2215126b79f887afe9d54ba52e8f3fa0b648b3e4",
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
if not NEGATIVE.read_text().startswith('include "./backend_cabi_x86_argument_byval.elisa"'):
    raise SystemExit("false controls must import the x86 argument model")
classifier = compact(section(CLASSIFIER.read_text(), "cabi_classify_arg"))
ordered = (
    "arg_is_aggregate:bool=cabi_is_aggregate(value_type)",
    "returnCabiArgPlan{direct:true,byval:false,aggregate:true,parts:scalar_parts,offsets:scalar_offsets,value_type:llvm_value}ifsize==0",
    "flat_ok:bool=cabi_flatten(llvm_value,0,leaves,structs)",
    "returnCabiArgPlan{direct:false,byval:true,aggregate:true,parts:no_parts,offsets:no_offsets,value_type:llvm_value}ifflat_ok==false",
    "target:i32=cabi_target(structs)",
    "iftarget==2:",
    "iftarget==0:",
    "returnCabiArgPlan{direct:false,byval:true,aggregate:true,parts:no_parts,offsets:no_offsets,value_type:llvm_value}ifsize>16",
    "x86_parts:mutabledarray[LLVMTypeRef]=[]",
)
if any(part not in classifier for part in ordered) or [classifier.index(part) for part in ordered] != sorted(classifier.index(part) for part in ordered):
    raise SystemExit("C argument classifier no longer matches aggregate, flatten, target, and x86 size policy")
declare = compact(section(DECLARATION.read_text(), "declare_extern"))
declare_steps = (
    "ifextern_is_exportandcabi_is_aggregate(param_value_type):",
    "export_arg_plan:CabiArgPlan=cabi_classify_arg(param_value_type,structs,ctx)",
    "ifexport_arg_plan.direct:",
    "export_arg_part_count:usize=export_arg_plan.parts.count",
    "forexport_arg_part_indexin0..<export_arg_part_count|extern_param_types|:extern_param_types.push(export_arg_plan.parts[export_arg_part_index])",
    "else:extern_param_types.push(LLVMPointerTypeInContext(ctx,0))",
)
if any(part not in declare for part in declare_steps) or [declare.index(part) for part in declare_steps] != sorted(declare.index(part) for part in declare_steps):
    raise SystemExit("exported aggregate arguments must use direct C parts or one byval pointer")
if args.source_only:
    print(f"source_bound=True positive={len(POSITIVE_HASHES)} false_controls={len(NEGATIVE_HASHES)}")
    raise SystemExit(0)
product = require_current_product(BIN, PROVER)
if product.get("compile_mode") != "strict":
    raise SystemExit("C ABI argument proof requires strict Elisa-Proof build")
inputs = list(dict.fromkeys([BIN, BIN.with_name(BIN.name + ".manifest.json"), BIN.with_name(BIN.name + ".manifest.json.sha256"), PROVER / "ELISA_COMPILER_REV", Path(__file__), HERE / "proof_product_gate.py", CLASSIFIER, DECLARATION, POSITIVE, NEGATIVE, *source_include_closure([POSITIVE, NEGATIVE])]))
before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
def run(path: Path):
    result = subprocess.run([str(BIN), "--json", str(path)], capture_output=True, text=True, timeout=60)
    return result.returncode, json.loads(result.stdout)
code, positive = run(POSITIVE)
if code or positive.get("status") != "proved" or positive.get("summary", {}).get("proven") != positive.get("summary", {}).get("obligations"):
    raise SystemExit("x86 C argument obligations did not fully prove")
code, negative = run(NEGATIVE)
if code != 1 or negative.get("status") != "failed" or {finding.get("name") for finding in negative.get("findings", [])} != set(NEGATIVE_HASHES) or not all(finding.get("kind") == "ensure-unproven" and finding.get("status") in ("unknown", "disproved") for finding in negative.get("findings", [])):
    raise SystemExit("x86 C argument false controls were not rejected")
if {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs} != before:
    raise SystemExit("C ABI argument proof inputs changed during replay")
print(json.dumps({"proved": positive["summary"]["proven"], "false_controls_rejected": len(NEGATIVE_HASHES), "source_bound": True}))
