"""Bind C ABI conversion shape proofs to guarded LLVM field operations."""
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
SOURCE = ROOT / "src/backend/codegen_call.elisa"
POSITIVE = HERE / "backend_cabi_plan_shape.elisa"
NEGATIVE = HERE / "backend_cabi_plan_shape_rejected.elisa"
POSITIVE_HASHES = {
    "cabi_plan_operation_shape_is_safe": "328fe427af934a227fd369a83096b934f3ee9110bcd6a7c58f0650f86f508691",
    "view_pointer_split_requires_two_fields": "f154e6edcfccde5306ee2b914312617d43934e2d34f8d005f5a0fa2c4254674e",
    "view_length_split_requires_two_fields": "34768a1fe8612ed32c604b192e992fc73799603bba6cce7f2b5ec64e2a60779e",
    "resource_handle_extract_requires_one_field": "cd72d6b421f7008fae99c8c9714e7d151da746166a73283dddcfb3504db7a680",
    "resource_handle_load_requires_pointer": "c73b4bdaa6e8f06a0061b37e32bb52a5244691986a0cbe0031c61d2804de967d",
}
NEGATIVE_HASHES = {
    "false_view_split_accepts_one_field": "af2ba702df9797e3ec108b1feeae8280eef65b9ba0c19711fb0c9166091e11e1",
    "false_resource_extract_accepts_zero_fields": "8226330c3a4c1624d10a1435d1f58b3fa08783acbeb5d5d6686bb07d68de79e2",
    "false_pointer_load_accepts_aggregate": "1be5d65a877c01a29f0b9b0ddf5bab3276b77e15aeab11f7cabe7aab4a3d9e27",
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
if not NEGATIVE.read_text().startswith('include "./backend_cabi_plan_shape.elisa"'):
    raise SystemExit("false controls must import the C ABI shape model")
body = compact(section(SOURCE.read_text(), "emit_direct_call_indexed"))
ordered = (
    "source_kind:u32=LLVMGetTypeKind(LLVMTypeOf(source))",
    "source_fields:u32=LLVMCountStructElementTypes(LLVMTypeOf(source))ifsource_kind==10else0",
    "ifcode%8==1orcode%8==2:plan_shape_bad<-trueifsource_fields<2",
    "elifcode%8==3:plan_shape_bad<-trueifsource_fields<1",
    "elifcode%8==4:plan_shape_bad<-trueifsource_kind!=12",
    "ifplan_shape_bad:planned_values.push(source)",
    'elifcode%8==1:planned_values.push(LLVMBuildExtractValue(builder,source,0,"extern.view.ptr"))',
    'elifcode%8==2:planned_values.push(LLVMBuildExtractValue(builder,source,1,"extern.view.len"))',
    'elifcode%8==3:planned_values.push(LLVMBuildExtractValue(builder,source,0,"extern.resource.handle"))',
    'elifcode%8==4:planned_values.push(LLVMBuildLoad2(builder,LLVMPointerTypeInContext(ctx,0),source,"extern.resource.handle"))',
    "nullreturnifplan_shape_bad",
)
if any(part not in body for part in ordered) or [body.index(part) for part in ordered] != sorted(body.index(part) for part in ordered):
    raise SystemExit("C ABI shape checks must precede and guard field extraction or pointer load")
if args.source_only:
    print(f"source_bound=True positive={len(POSITIVE_HASHES)} false_controls={len(NEGATIVE_HASHES)}")
    raise SystemExit(0)
product = require_current_product(BIN, PROVER)
if product.get("compile_mode") != "strict":
    raise SystemExit("C ABI shape proof requires strict Elisa-Proof build")
inputs = list(dict.fromkeys([BIN, BIN.with_name(BIN.name + ".manifest.json"), BIN.with_name(BIN.name + ".manifest.json.sha256"), PROVER / "ELISA_COMPILER_REV", Path(__file__), HERE / "proof_product_gate.py", SOURCE, POSITIVE, NEGATIVE, *source_include_closure([POSITIVE, NEGATIVE])]))
before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
def run(path: Path):
    result = subprocess.run([str(BIN), "--json", str(path)], capture_output=True, text=True, timeout=60)
    return result.returncode, json.loads(result.stdout)
code, positive = run(POSITIVE)
if code or positive.get("status") != "proved" or positive.get("summary", {}).get("proven") != positive.get("summary", {}).get("obligations"):
    raise SystemExit("C ABI shape obligations did not fully prove")
code, negative = run(NEGATIVE)
if code != 1 or negative.get("status") != "failed" or {finding.get("name") for finding in negative.get("findings", [])} != set(NEGATIVE_HASHES) or not all(finding.get("kind") == "ensure-unproven" and finding.get("status") in ("unknown", "disproved") for finding in negative.get("findings", [])):
    raise SystemExit("C ABI malformed-shape controls were not rejected")
if {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs} != before:
    raise SystemExit("C ABI shape proof inputs changed during replay")
print(json.dumps({"proved": positive["summary"]["proven"], "false_controls_rejected": len(NEGATIVE_HASHES), "source_bound": True}))
