"""Admit source-bound proof that zip_map validates each source extent before indexing."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
SOURCE = ROOT / "src/backend/codegen_call_named.elisa"
GUARDS = ROOT / "src/backend/codegen_guards.elisa"
INTERNED_TYPES = ROOT / "src/backend/codegen_interned_types.elisa"
LLVM_TYPES = ROOT / "src/backend/codegen_llvm_types.elisa"
RUNTIME_DECL = ROOT / "src/backend/codegen_runtime_decl.elisa"
LLVM_C = ROOT / "src/backend/llvm_c.elisa"
COLLECTIONS = ROOT / "elisacore_std/collections.elisa"
POSITIVE = HERE / "backend_zip_map_bounds.elisa"
NEGATIVE = HERE / "backend_zip_map_bounds_rejected.elisa"
POSITIVE_NAMES = {
    "zip_index_is_inside_every_view",
    "source_count_guard_accepts_a_covering_view",
    "source_count_guard_rejects_a_short_view",
    "zero_destination_has_no_loop_index",
}
NEGATIVE_NAMES = {
    "false_claim_short_source_covers_destination",
    "false_claim_source_guard_accepts_short_view",
}


def compact(text: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in text.splitlines())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


zip_map = compact(function_section(SOURCE.read_text(), "emit_call_named"))
zip_steps = (
    'ifcallee_name=="zip_map"andarguments.count==4:',
    'zip_total:LLVMValueRef=darray_size_value_i64(LLVMBuildExtractValue(builder,zip_dst,1,"zip_map.total.raw"),ctx,builder,"zip_map.total")',
    'zip_src1_total:LLVMValueRef=darray_size_value_i64(LLVMBuildExtractValue(builder,zip_src1,1,"zip_map.src1.total.raw"),ctx,builder,"zip_map.src1.total")',
    'zip_src2_total:LLVMValueRef=darray_size_value_i64(LLVMBuildExtractValue(builder,zip_src2,1,"zip_map.src2.total.raw"),ctx,builder,"zip_map.src2.total")',
    'emit_required_count_available_guard(zip_total,zip_src1_total,m,ctx,builder)',
    'emit_required_count_available_guard(zip_total,zip_src2_total,m,ctx,builder)',
    'zip_at:LLVMValueRef=LLVMBuildLoad2(builder,zip_i64,zip_index,"zip_map.index")',
    'LLVMBuildCondBr(builder,LLVMBuildICmp(builder,36,zip_at,zip_total,"zip_map.has_more"),zip_body,zip_end)',
    'LLVMBuildGEP2(builder,zip_elem_llvm,zip_src1_data,zip_off1_pointer,1,"zip_map.src1.ptr")',
    'LLVMBuildGEP2(builder,zip_elem_llvm,zip_src2_data,zip_off2_pointer,1,"zip_map.src2.ptr")',
)
positions = [zip_map.find(step) for step in zip_steps]
if any(position < 0 for position in positions) or positions != sorted(positions):
    raise SystemExit("zip_map must normalize all counts and guard both sources before its loop and source GEPs")
if zip_map.count("emit_required_count_available_guard(zip_total,") != 2:
    raise SystemExit("zip_map must guard both source views against the destination count")

guard = compact(function_section(GUARDS.read_text(), "emit_required_count_available_guard"))
guard_steps = (
    'enough:LLVMValueRef=LLVMBuildICmp(builder,LLVMIntPredicate::UGE,available_count,required_count,"view.count.available")',
    '_=LLVMBuildCondBr(builder,enough,ok_block,fail_block)',
    'LLVMPositionBuilderAtEnd(builder,fail_block)',
    'emit_trap_unreachable(m,ctx,builder)',
    'LLVMPositionBuilderAtEnd(builder,ok_block)',
)
guard_positions = [guard.find(step) for step in guard_steps]
if any(position < 0 for position in guard_positions) or guard_positions != sorted(guard_positions):
    raise SystemExit("source extent guard must trap when available_count < required_count")

normalizer = compact(function_section(INTERNED_TYPES.read_text(), "darray_size_value_i64"))
if "returnLLVMBuildZExt(builder,value,size_type,name)ifLLVMGetIntTypeWidth(source_type)<64elsevalue" not in normalizer:
    raise SystemExit("zip_map view counts must be zero-extended before unsigned comparison")
if "UGE:i32=35" not in compact(LLVM_C.read_text()):
    raise SystemExit("zip_map count guard must bind UGE to LLVMIntPredicate's unsigned-greater-or-equal value")
runtime_size = compact(function_section(RUNTIME_DECL.read_text(), "runtime_size_llvm_type"))
if "LLVMInt32TypeInContext(ctx)returniftarget_bits==32" not in runtime_size or \
        "returnLLVMInt64TypeInContext(ctx)" not in runtime_size:
    raise SystemExit("view lengths must use target-sized usize fields")
view_type = compact(function_section(LLVM_TYPES.read_text(), "llvm_type_of"))
if "view_fields:mutabledarray[LLVMTypeRef]=[LLVMPointerTypeInContext(ctx,0),runtime_size_llvm_type(ctx,structs.target.target_pointer_bits)]" not in view_type:
    raise SystemExit("DynArrayView count field must have the target usize width")
if "structDynArrayView:data:mutablevoid&?len:mutableusize" not in compact(COLLECTIONS.read_text()):
    raise SystemExit("source DynArrayView length must remain usize")

if declarations(POSITIVE) != POSITIVE_NAMES or declarations(NEGATIVE) != NEGATIVE_NAMES:
    raise SystemExit("zip_map bounds proof inventory changed")
if 'include "./backend_zip_map_bounds.elisa"' not in NEGATIVE.read_text():
    raise SystemExit("negative controls no longer include the admitted zip_map bounds proof")

product = require_current_product(BIN, PROVER)
if product.get("compile_mode") != "strict":
    raise SystemExit("zip_map bounds proof requires a strict proof build")
stage1_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN,
    BIN.with_name(BIN.name + ".manifest.json"),
    BIN.with_name(BIN.name + ".manifest.json.sha256"),
    PROVER / "ELISA_COMPILER_REV",
    stage1_product,
    stage1_provenance,
    Path(__file__),
    HERE / "proof_product_gate.py",
    SOURCE,
    GUARDS,
    INTERNED_TYPES,
    LLVM_TYPES,
    RUNTIME_DECL,
    LLVM_C,
    COLLECTIONS,
    POSITIVE,
    NEGATIVE,
    *source_include_closure([POSITIVE, NEGATIVE]),
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True, text=True, timeout=60)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"]
    assert report["trust"]["kernel_replayed_certificates"] == report["replay"]["replayed"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["declarations"] == len(POSITIVE_NAMES)
assert positive["summary"]["obligations"] == positive["summary"]["proven"]
assert not positive["findings"]
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == POSITIVE_NAMES

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["declarations"] == len(POSITIVE_NAMES) + len(NEGATIVE_NAMES)
assert {row["name"] for row in negative["findings"]} == NEGATIVE_NAMES
assert all(row["kind"] == "ensure-unproven" and row["status"] in ("unknown", "disproved")
           for row in negative["findings"])
assert not NEGATIVE_NAMES & {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product
print(json.dumps({
    "admitted": True,
    "scope": "zip_map source reads are bounded by the destination and each validated source count",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(NEGATIVE_NAMES),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "source_sha256": hashes_before,
}, sort_keys=True))
