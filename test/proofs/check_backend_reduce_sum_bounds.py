"""Admit the view-length and source-index bound used by the reduce_sum lowering."""
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
CALL_NAMED = ROOT / "src/backend/codegen_call_named.elisa"
INTERNED_TYPES = ROOT / "src/backend/codegen_interned_types.elisa"
RUNTIME_DECL = ROOT / "src/backend/codegen_runtime_decl.elisa"
LLVM_TYPES = ROOT / "src/backend/codegen_llvm_types.elisa"
LLVM_C = ROOT / "src/backend/llvm_c.elisa"
COLLECTIONS = ROOT / "elisacore_std/collections.elisa"
POSITIVE = HERE / "backend_reduce_sum_bounds.elisa"
NEGATIVE = HERE / "backend_reduce_sum_bounds_rejected.elisa"
POSITIVE_NAMES = {
    "reduce_sum_loop_body_requires_index_below_count",
    "reduce_sum_initial_index_satisfies_count_bound",
    "reduce_sum_loop_step_preserves_count_bound",
    "empty_reduce_sum_view_skips_the_body",
    "one_past_reduce_sum_index_is_rejected",
}
NEGATIVE_NAMES = {
    "false_claim_one_past_reduce_sum_index_is_bounded",
    "false_claim_reduce_sum_step_stays_strictly_below_count",
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


def require_ordered(source: str, steps: tuple[str, ...], label: str) -> None:
    cursor = 0
    for step in steps:
        position = source.find(step, cursor)
        if position < 0:
            raise SystemExit(f"{label} changed its proved operation order: {step}")
        cursor = position + len(step)


reduce_sum = compact(function_section(CALL_NAMED.read_text(), "emit_call_named"))
require_ordered(reduce_sum, (
    'ifcallee_name=="reduce_sum"andarguments.count>=2:',
    'reduce_data:LLVMValueRef=LLVMBuildExtractValue(builder,reduce_source,0,"reduce_sum.src.data")',
    'reduce_total:LLVMValueRef=darray_size_value_i64(LLVMBuildExtractValue(builder,reduce_source,1,"reduce_sum.total.raw"),ctx,builder,"reduce_sum.total")',
    'reduce_index:LLVMValueRef=build_entry_alloca(builder,reduce_i64,"reduce_sum.i")',
    '_=LLVMBuildStore(builder,LLVMConstInt(reduce_i64,0,0),reduce_index)',
    'reduce_function:LLVMValueRef=LLVMGetBasicBlockParent(LLVMGetInsertBlock(builder))',
    'reduce_cond:LLVMBasicBlockRef=LLVMAppendBasicBlockInContext(ctx,reduce_function,"reduce_sum.cond")',
    'reduce_body:LLVMBasicBlockRef=LLVMAppendBasicBlockInContext(ctx,reduce_function,"reduce_sum.body")',
    'reduce_end:LLVMBasicBlockRef=LLVMAppendBasicBlockInContext(ctx,reduce_function,"reduce_sum.end")',
    '_=LLVMBuildBr(builder,reduce_cond)',
    'LLVMPositionBuilderAtEnd(builder,reduce_cond)',
    'reduce_at:LLVMValueRef=LLVMBuildLoad2(builder,reduce_i64,reduce_index,"reduce_sum.index")',
    'LLVMBuildCondBr(builder,LLVMBuildICmp(builder,36,reduce_at,reduce_total,"reduce_sum.has_more"),reduce_body,reduce_end)',
    'LLVMPositionBuilderAtEnd(builder,reduce_body)',
    'reduce_offsets:mutabledarray[LLVMValueRef]=[reduce_at]',
    'reduce_offsets_pointer:void&=(&reduce_offsets[0]).cast[void&]canUnsafe.PointerCast',
    'LLVMBuildGEP2(builder,reduce_elem_llvm,reduce_data,reduce_offsets_pointer,1,"reduce_sum.src.ptr")',
    'LLVMBuildStore(builder,LLVMBuildAdd(builder,LLVMBuildLoad2(builder,reduce_i64,reduce_index,"reduce_sum.index.cur"),LLVMConstInt(reduce_i64,1,0),"reduce_sum.index.next"),reduce_index)',
    '_=LLVMBuildBr(builder,reduce_cond)',
), "reduce_sum unsigned view indexing")
if 'LLVMBuildExtractValue(builder,reduce_source,1,"reduce_sum.total")' in reduce_sum:
    raise SystemExit("reduce_sum must normalize target-sized view length before comparing with its i64 loop index")

normalizer = compact(function_section(INTERNED_TYPES.read_text(), "darray_size_value_i64"))
if "returnLLVMBuildZExt(builder,value,size_type,name)ifLLVMGetIntTypeWidth(source_type)<64elsevalue" not in normalizer:
    raise SystemExit("reduce_sum view count must be zero-extended from wasm32 usize")
runtime_size = compact(function_section(RUNTIME_DECL.read_text(), "runtime_size_llvm_type"))
if "LLVMInt32TypeInContext(ctx)returniftarget_bits==32" not in runtime_size or \
        "returnLLVMInt64TypeInContext(ctx)" not in runtime_size:
    raise SystemExit("view count storage must follow target usize width")
view_type = compact(function_section(LLVM_TYPES.read_text(), "llvm_type_of"))
if "view_fields:mutabledarray[LLVMTypeRef]=[LLVMPointerTypeInContext(ctx,0),runtime_size_llvm_type(ctx,structs.target.target_pointer_bits)]" not in view_type:
    raise SystemExit("DynArrayView field 1 must be target-sized usize")
if "structDynArrayView:data:mutablevoid&?len:mutableusize" not in compact(COLLECTIONS.read_text()):
    raise SystemExit("source DynArrayView length must remain usize")
if "ULT:i32=36" not in compact(LLVM_C.read_text()):
    raise SystemExit("reduce_sum loop bound must use LLVM's unsigned-less-than predicate")

if declarations(POSITIVE) != POSITIVE_NAMES or declarations(NEGATIVE) != NEGATIVE_NAMES:
    raise SystemExit("reduce_sum bound proof inventory changed")
positive_text = POSITIVE.read_text()
expected_positive = {
    "reduce_sum_initial_index_satisfies_count_bound": "def reduce_sum_initial_index_satisfies_count_bound(count:u64)->bool:\nensure result==true\nreturn 0<=count",
    "reduce_sum_loop_step_preserves_count_bound": "def reduce_sum_loop_step_preserves_count_bound(index:u64,count:u64)->bool:\nrequires index<count\nensure result==true\nreturn index+1<=count",
}
for name, expected in expected_positive.items():
    if compact(function_section(positive_text, name)) != compact(expected):
        raise SystemExit(f"reduce_sum loop invariant theorem {name} changed")
negative_text = NEGATIVE.read_text()
expected_negative = "def false_claim_reduce_sum_step_stays_strictly_below_count(index:u64,count:u64)->bool:\nrequires index<count\nrequires index+1==count\nensure result==true\nreturn index+1<count"
if compact(function_section(negative_text, "false_claim_reduce_sum_step_stays_strictly_below_count")) != compact(expected_negative):
    raise SystemExit("reduce_sum loop-step negative control changed")
if 'include "./backend_reduce_sum_bounds.elisa"' not in NEGATIVE.read_text():
    raise SystemExit("negative control no longer includes the admitted reduce_sum proof")

product = require_current_product(BIN, PROVER)
if product.get("compile_mode") != "strict":
    raise SystemExit("reduce_sum bounds proof requires a strict proof build")
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
    CALL_NAMED,
    INTERNED_TYPES,
    RUNTIME_DECL,
    LLVM_TYPES,
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
    "scope": "reduce_sum only loads indices below the target-sized view count normalized to its i64 loop carrier",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(NEGATIVE_NAMES),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "source_sha256": hashes_before,
}, sort_keys=True))
