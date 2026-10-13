"""Bind declared LLVM ABI slot proofs to codegen push order."""
from __future__ import annotations
import argparse, hashlib, json, os, re, subprocess
from pathlib import Path
from proof_product_gate import require_current_product, source_include_closure

parser = argparse.ArgumentParser()
parser.add_argument("--source-only", action="store_true")
args = parser.parse_args()
ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PROOF = Path(__file__).resolve().with_name("backend_declared_parameter_abi.elisa")
NEGATIVE = Path(__file__).resolve().with_name("backend_declared_parameter_abi_rejected.elisa")
SOURCE = ROOT / "src/backend/codegen_declare_signature.elisa"
EXPECTED = {
    "declared_parameter_count": "27108f4e97250a3980a7346416ce22d9f780d79b8e929d582ac135120d140d0d",
    "source_parameter_start": "00f28ff3abf97da3a24d8ec82a6d0c4353ffbfc2e32e2dc0f932c7250772a8a7",
    "packed_store_parameter_index": "2479a901ced6e16a32e8962d736b0830428f00f1109cbb2973bb6e236ad258f2",
    "arena_parameter_start": "6f52cde8df5fe2ae5706e1f1635b7aa1332355620eb3f1bdad6fcc0598cd06ac",
}
FALSE = {
    "false_source_parameters_start_at_zero": "f32fe7d9e7ab204da4e92fdb669ac50de22a13eab7c4c3053b6185f93cc1a90d",
    "false_store_index_ignores_sret": "36cbdac0f9d3ee68d25009fcd41833708a1e586e83e439d93f86eb4d7b7c6171",
    "false_count_omits_sret": "6602efeb9a8fc9bfe54318c96da107a06efcd34ad7732d92d1629da1f7e1ed66",
}
def compact(s: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in s.splitlines())
def section(s: str, name: str) -> str:
    match = re.search(rf"(?m)^[ \t]*def {re.escape(name)}\(", s)
    if not match:
        raise SystemExit(f"missing {name}")
    following = re.search(r"(?m)^[ \t]*def [A-Za-z_]\w*\(", s[match.end():])
    return s[match.start():match.end() + following.start() if following else len(s)]
proof = PROOF.read_text()
for name, digest in EXPECTED.items():
    body = compact(section(proof, name))
    actual = hashlib.sha256(body.encode()).hexdigest()
    if actual != digest:
        raise SystemExit(f"{name} proof changed since source binding")
negative = NEGATIVE.read_text()
for name, digest in FALSE.items():
    if hashlib.sha256(compact(section(negative, name)).encode()).hexdigest() != digest:
        raise SystemExit(f"{name} false control changed")
if not negative.startswith('include "./backend_declared_parameter_abi.elisa"'):
    raise SystemExit("ABI false controls must include the positive model")
source = compact(section(SOURCE.read_text(), "declared_parameter_llvm_types"))
ordered = (
    "llvm_param_types.push(LLVMPointerTypeInContext(ctx,0))ifsret_return",
    "fordeclared_param_typeindeclared_param_types|llvm_param_types,structs,ctx|:",
    "ifvalue_type_uses_indirect_aggregate(declared_param_type,structs,ctx):llvm_param_types.push(LLVMPointerTypeInContext(ctx,0))else:llvm_param_types.push(llvm_type_of(declared_param_type,structs,ctx))",
    "ifwants_store:ast_store_type:ValueType=ValueType{kind:TypeKind.PackedStore,bits:0}llvm_param_types.push(llvm_type_of(ast_store_type,structs,ctx))",
    "for_arena_indexin0..<arena_count:llvm_param_types.push(LLVMPointerTypeInContext(ctx,0))",
    "returnllvm_param_types",
)
if any(item not in source for item in ordered) or [source.index(item) for item in ordered] != sorted(source.index(item) for item in ordered):
    raise SystemExit("declared parameter ABI push order changed")
if args.source_only:
    print(f"source_bound=True proof_functions={len(EXPECTED)} false_controls={len(FALSE)}")
else:
    prover = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
    binary = Path(os.environ.get("ELISA_PROOF_BIN", prover / "build/elisa-proof")).resolve()
    product = require_current_product(binary, prover)
    if product.get("compile_mode") != "strict":
        raise SystemExit("ABI proof requires strict Elisa-Proof build")
    inputs = list(dict.fromkeys([binary, binary.with_name(binary.name + ".manifest.json"), binary.with_name(binary.name + ".manifest.json.sha256"), prover / "ELISA_COMPILER_REV", Path(__file__), HERE / "proof_product_gate.py", SOURCE, PROOF, NEGATIVE, *source_include_closure([PROOF, NEGATIVE])]))
    before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
    def run(path: Path):
        result = subprocess.run([str(binary), "--json", str(path)], capture_output=True, text=True, timeout=60)
        return result.returncode, json.loads(result.stdout)
    code, report = run(PROOF)
    if code or report.get("status") != "proved" or report.get("summary", {}).get("proven") != report.get("summary", {}).get("obligations"):
        raise SystemExit("ABI parameter layout proof did not fully prove")
    code, rejected = run(NEGATIVE)
    if code != 1 or rejected.get("status") != "failed" or {f.get("name") for f in rejected.get("findings", [])} != set(FALSE) or not all(f.get("kind") == "ensure-unproven" and f.get("status") in ("unknown", "disproved") for f in rejected.get("findings", [])):
        raise SystemExit("ABI slot-layout false controls were not rejected")
    if {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs} != before:
        raise SystemExit("ABI proof inputs changed during replay")
    print(json.dumps({"proved": report["summary"]["proven"], "false_controls_rejected": len(FALSE), "source_bound": True}))
