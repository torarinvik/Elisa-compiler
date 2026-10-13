"""Prove and bind noalias stripping at externally callable LLVM ABI boundaries."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure

parser = argparse.ArgumentParser()
parser.add_argument("--source-only", action="store_true")
args = parser.parse_args()
ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve(strict=not args.source_only)
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=not args.source_only)
ATTRS = ROOT / "src/backend/codegen_attrs.elisa"
WRAPPERS = ROOT / "src/backend/codegen_export_wrappers.elisa"
MODULE = ROOT / "src/backend/codegen_module.elisa"
LLVM_C = ROOT / "src/backend/llvm_c.elisa"
POSITIVE = HERE / "backend_noalias_abi_boundary.elisa"
NEGATIVE = HERE / "backend_noalias_abi_boundary_rejected.elisa"
POSITIVE_NAMES = {
    "external_linkage_requires_noalias_removal",
    "internal_linkage_keeps_the_noalias_contract",
    "parameter_enum_attribute_index_is_one_based",
    "removal_index_never_names_the_function_attribute",
}
NEGATIVE_NAMES = {
    "false_external_linkage_keeps_noalias",
    "false_internal_linkage_strips_noalias",
    "false_first_parameter_uses_function_attribute_index",
}
PROOF_HASHES = {
    "external_linkage_requires_noalias_removal": "89dbe6dce45f88a4cfdefa6caa8b9342de27797e00675520895cbcf80570a41f",
    "internal_linkage_keeps_the_noalias_contract": "7d1c104541df915d3886a9cd85651e3e240f76885ae26ee066b9ec4acff3a92a",
    "parameter_enum_attribute_index_is_one_based": "0cae14e58f7747e4fdac78ddc4e7f29921f1684535f69f34596c0c07fdd5b6b0",
    "removal_index_never_names_the_function_attribute": "455ef6e3bcbaebd79005ee3789e8850dbe9ed0e3e0d5203de5be403f10bfb577",
    "false_external_linkage_keeps_noalias": "ce770595c87f08046c5da52afb12f62f6faf76afd2798f247c247992546375af",
    "false_internal_linkage_strips_noalias": "53101376e75be23e250c364b8b0301c325ea8e6754851956cb513aab5e743910",
    "false_first_parameter_uses_function_attribute_index": "b85774177bb7fc3b0ad3a8a22bb939f56f5b8b4623c5361e5f6a61b5be7dc1e1",
}


def compact(text: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in text.splitlines())


def section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected one {name} declaration")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


attrs = ATTRS.read_text()
wrappers = WRAPPERS.read_text()
module = MODULE.read_text()
llvm_c = LLVM_C.read_text()
remove_one = compact(section(attrs, "remove_noalias_parameter_attributes"))
for shape in (
    'kind_name:cstr=sview_to_cstr("noalias",kind_storage)',
    'kind:u32=LLVMGetEnumAttributeKindForName(kind_name,7.usize())',
    "returnifkind==0",
    "parameter_count:usize=LLVMCountParams(fn).usize()",
    "forparameter_offsetin0..<parameter_count|fn,kind|:",
    "LLVMRemoveEnumAttributeAtIndex(fn,(parameter_offset+1.usize()).u32(),kind)",
):
    if shape not in remove_one:
        raise SystemExit(f"noalias parameter removal changed its one-based parameter policy: {shape}")
remove_external = compact(section(attrs, "remove_external_noalias_parameter_attributes"))
if ("function:mutableLLVMValueRef?=LLVMGetFirstFunction(m)" not in remove_external or
        "linkage:u32=LLVMGetLinkage(handle)" not in remove_external or
        "remove_noalias_parameter_attributes(handle)iflinkage!=8andlinkage!=9" not in remove_external or
        "function<-LLVMGetNextFunction(handle)" not in remove_external):
    raise SystemExit("module noalias cleanup must retain only LLVM internal/private linkage")
wrapper = compact(section(wrappers, "emit_export_wrapper_to"))
if "remove_noalias_parameter_attributes(target)ifstructs.target.noalias_mutable_refs" not in wrapper:
    raise SystemExit("export wrapper no longer clears noalias on its externally callable target")
core = compact(section(module, "emit_module_core"))
cleanup = "remove_external_noalias_parameter_attributes(m)ifstructs.target.noalias_mutable_refs"
if core.count(cleanup) != 1 or core.find(cleanup) < core.rfind("emit_export_wrapper"):
    raise SystemExit("external noalias cleanup must run after wrapper and function emission")
if "externLLVMRemoveEnumAttributeAtIndex(function:LLVMValueRef,index:u32,kind:u32)->void" not in compact(llvm_c):
    raise SystemExit("LLVM C binding for removing the selected enum parameter attribute changed")

if declarations(POSITIVE) != POSITIVE_NAMES or declarations(NEGATIVE) != NEGATIVE_NAMES:
    raise SystemExit("noalias ABI proof inventory changed")
if not NEGATIVE.read_text().startswith('include "./backend_noalias_abi_boundary.elisa"'):
    raise SystemExit("noalias ABI false claims must include the positive policy model")
for name, expected in PROOF_HASHES.items():
    owner = POSITIVE if name in POSITIVE_NAMES else NEGATIVE
    actual = hashlib.sha256(compact(section(owner.read_text(), name)).encode()).hexdigest()
    if actual != expected:
        raise SystemExit(f"noalias boundary theorem {name} changed since source binding")

if args.source_only:
    print(json.dumps({"source_bound": True, "positive": len(POSITIVE_NAMES),
                      "false_controls": len(NEGATIVE_NAMES)}))
    raise SystemExit(0)

product = require_current_product(BIN, PROVER)
if product.get("compile_mode") != "strict":
    raise SystemExit("noalias ABI proof requires a strict Elisa-Proof build")
inputs = list(dict.fromkeys([BIN, BIN.with_name(BIN.name + ".manifest.json"),
    BIN.with_name(BIN.name + ".manifest.json.sha256"), PROVER / "ELISA_COMPILER_REV",
    Path(__file__), HERE / "proof_product_gate.py", ATTRS, WRAPPERS, MODULE, LLVM_C,
    POSITIVE, NEGATIVE, *source_include_closure([POSITIVE, NEGATIVE])]))
before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                            text=True, timeout=60)
    return process.returncode, json.loads(process.stdout)


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["obligations"] == positive["summary"]["proven"]
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == POSITIVE_NAMES
code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert {row["name"] for row in negative["findings"]} == NEGATIVE_NAMES
assert all(row["kind"] == "ensure-unproven" and row["status"] in ("unknown", "disproved")
           for row in negative["findings"])
if {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs} != before:
    raise SystemExit("compiler or proof inputs changed during replay")
print(json.dumps({"positive_obligations": positive["summary"]["proven"],
                  "false_claims_rejected": sorted(NEGATIVE_NAMES), "source_bound": True}))
