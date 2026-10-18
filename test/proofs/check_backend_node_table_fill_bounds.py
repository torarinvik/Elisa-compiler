"""Bind checked node_table_fill allocation arithmetic to source-backed proofs."""
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
CALL = ROOT / "src/backend/codegen_call.elisa"
CONTAINER_OPS = ROOT / "src/backend/codegen_container_ops.elisa"
INTERNED_TYPES = ROOT / "src/backend/codegen_interned_types.elisa"
RUNTIME_DECL = ROOT / "src/backend/codegen_runtime_decl.elisa"
VALUE_TYPE = ROOT / "src/backend/codegen_value_type.elisa"
LLVM_C = ROOT / "src/backend/llvm_c.elisa"
POLICY = ROOT / "src/backend/codegen_cstr_terminator_policy.elisa"
POSITIVE = HERE / "backend_node_table_fill_bounds.elisa"
NEGATIVE = HERE / "backend_node_table_fill_bounds_rejected.elisa"
POSITIVE_NAMES = {
    "admitted_count_roundtrips_through_target_usize",
    "wasm32_count_guard_rejects_first_unrepresentable_count",
    "admitted_node_count_fits_target_usize",
    "zero_stride_allocation_size_is_zero",
    "positive_stride_allocation_size_fits_target",
    "empty_node_table_skips_the_fill_branch",
    "nonempty_node_table_has_the_requested_view_length",
}
NEGATIVE_NAMES = {
    "false_claim_first_unrepresentable_count_roundtrips",
    "false_claim_wasm32_accepts_first_unrepresentable_count",
    "false_claim_u32_allocation_product_fits",
    "false_claim_empty_node_table_takes_the_fill_branch",
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


policy_text = compact(POLICY.read_text())
if "constU32_MAX:u64=4294967295" not in policy_text or \
        "constU64_MAX:u64=18446744073709551615u64" not in policy_text:
    raise SystemExit("node_table_fill target-size proof lost the named usize maxima")
target_max = compact(function_section(POLICY.read_text(), "target_size_max"))
if "32:U32_MAX64:U64_MAX_:0" not in target_max:
    raise SystemExit("node_table_fill target-size model no longer covers wasm32 and 64-bit targets")

container = CONTAINER_OPS.read_text()
container_u32_max = re.search(r"(?m)^\s*const DARRAY_U32_MAX: u64 = (\d+)\s*$", container)
policy_u32_max = re.search(r"(?m)^\s*const U32_MAX: u64 = (\d+)\s*$", POLICY.read_text())
if container_u32_max is None or policy_u32_max is None or container_u32_max.group(1) != policy_u32_max.group(1):
    raise SystemExit("reserve overflow guard's wasm32 bound changed without updating its proof")

checked_target = compact(function_section(container, "emit_checked_target_size"))
require_ordered(checked_target, (
    "returnvalueiftarget_bits!=32",
    'too_wide:LLVMValueRef=LLVMBuildICmp(builder,34,value,LLVMConstInt(LLVMTypeOf(value),DARRAY_U32_MAX,0),"reserve.target.overflow")',
    "_=LLVMBuildCondBr(builder,too_wide,trap_block,continue_block)",
    "LLVMPositionBuilderAtEnd(builder,trap_block)",
    "emit_trap_unreachable(m,ctx,builder)",
    "LLVMPositionBuilderAtEnd(builder,continue_block)",
    "returnvalue",
), "target-size overflow guard")

overflow_binary = compact(function_section(container, "emit_overflow_binary"))
require_ordered(overflow_binary, (
    "ifmultiplyandtarget_bits==32:",
    'product:LLVMValueRef=LLVMBuildMul(builder,left,right,"reserve.u64.product")',
    'high_word:LLVMValueRef=LLVMBuildAdd(builder,high_product,LLVMBuildAdd(builder,LLVMBuildLShr(builder,middle,shift32,"reserve.u64.middle.high"),LLVMBuildLShr(builder,cross,shift32,"reserve.u64.cross.high"),"reserve.u64.high.carries"),"reserve.u64.high.word")',
    'overflow:mutableLLVMValueRef=LLVMBuildICmp(builder,33,high_word,zero,"reserve.u64.overflow")',
    'left_exceeds:LLVMValueRef=LLVMBuildICmp(builder,34,left,LLVMConstInt(int_type,DARRAY_U32_MAX,0),"reserve.left.u32.overflow")',
    'right_exceeds:LLVMValueRef=LLVMBuildICmp(builder,34,right,LLVMConstInt(int_type,DARRAY_U32_MAX,0),"reserve.right.u32.overflow")',
    'value_exceeds:LLVMValueRef=LLVMBuildICmp(builder,34,product,LLVMConstInt(int_type,DARRAY_U32_MAX,0),"reserve.value.u32.overflow")',
    'overflow<-LLVMBuildOr(builder,overflow,target_overflow,"reserve.target.overflow")',
    'intrinsic_name:sview="llvm.umul.with.overflow"ifmultiplyelse"llvm.uadd.with.overflow"',
    'call:LLVMValueRef=LLVMBuildCall2(builder,LLVMGlobalGetValueType(intrinsic_fn),intrinsic_fn,arguments_pointer,2,"checked.binary")',
    'value:LLVMValueRef=LLVMBuildExtractValue(builder,call,0,"checked.value")',
    'overflow:mutableLLVMValueRef=LLVMBuildExtractValue(builder,call,1,"checked.overflow")',
    'left_exceeds:LLVMValueRef=LLVMBuildICmp(builder,34,left,LLVMConstInt(int_type,DARRAY_U32_MAX,0),"reserve.left.u32.overflow")',
    'right_exceeds:LLVMValueRef=LLVMBuildICmp(builder,34,right,LLVMConstInt(int_type,DARRAY_U32_MAX,0),"reserve.right.u32.overflow")',
    'value_exceeds:LLVMValueRef=LLVMBuildICmp(builder,34,value,LLVMConstInt(int_type,DARRAY_U32_MAX,0),"reserve.value.u32.overflow")',
    'overflow<-LLVMBuildOr(builder,overflow,target_overflow,"reserve.target.overflow")',
), "checked unsigned allocation product")

checked_binary = compact(function_section(container, "emit_checked_reserve_binary"))
require_ordered(checked_binary, (
    "ifemit_overflow_binary(left,right,multiply,m,ctx,builder,target_bits)isresult:",
    "_=LLVMBuildCondBr(builder,result.overflow,trap_block,continue_block)",
    "LLVMPositionBuilderAtEnd(builder,trap_block)",
    "emit_trap_unreachable(m,ctx,builder)",
    "LLVMPositionBuilderAtEnd(builder,continue_block)",
    "returnresult.value",
), "checked allocation arithmetic trap")

call = compact(function_section(CALL.read_text(), "emit_call"))
node_table_steps = (
    'ifntf_name=="node_table_fill"andntf_type_args.count==2andarguments.count==3:',
    'if(emit_expression(arguments[2],ntf_element,local_scope,fns,structs,generics,runtime,m,ctx,builder)canGlobal{Read,Write})isntf_init:',
    'ntf_size_type:LLVMTypeRef=runtime_size_llvm_type(ctx,structs.target.target_pointer_bits)',
    'ntf_count_type:LLVMTypeRef=LLVMFunctionType(ntf_size_type,ntf_count_params_ptr,1,0)',
    'ntf_count_native:LLVMValueRef=LLVMBuildCall2(builder,ntf_count_type,ntf_count_fn,ntf_count_args_ptr,1,"node.table.count")',
    'ntf_count:LLVMValueRef=darray_size_value_i64(ntf_count_native,ctx,builder,"node.table.count.i64")',
    'ntf_count_target:LLVMValueRef?=emit_checked_target_size(ntf_count,m,ctx,builder,structs.target.target_pointer_bits)',
    'ifntf_count_targetisntf_checked_count:',
    'ntf_result_slot:LLVMValueRef=build_entry_alloca(builder,ntf_view_type,"node.table.result")',
    '_=LLVMBuildStore(builder,LLVMConstNull(ntf_view_type),ntf_result_slot)',
    'ntf_fill_block:LLVMBasicBlockRef=LLVMAppendBasicBlockInContext(ctx,ntf_function,"node.table.fill")',
    'ntf_done_block:LLVMBasicBlockRef=LLVMAppendBasicBlockInContext(ctx,ntf_function,"node.table.done")',
    'ntf_has_rows:LLVMValueRef=LLVMBuildICmp(builder,33,ntf_checked_count,LLVMConstInt(LLVMTypeOf(ntf_checked_count),0,0),"node.table.nonempty")',
    '_=LLVMBuildCondBr(builder,ntf_has_rows,ntf_fill_block,ntf_done_block)',
    'LLVMPositionBuilderAtEnd(builder,ntf_fill_block)',
    'ntf_stride:LLVMValueRef=element_stride(ntf_element,structs,ctx)',
    'emit_checked_reserve_binary(ntf_count,ntf_stride,true,m,ctx,builder,structs.target.target_pointer_bits)isntf_bytes',
    'ntf_alloc_type:LLVMTypeRef=LLVMFunctionType(ntf_ptr_type,ntf_alloc_params_ptr,2,0)',
    'ntf_alloc_args:mutabledarray[LLVMValueRef]=[ntf_arena,runtime_size_argument(ntf_bytes,ctx,builder,structs.target.target_pointer_bits)]',
    'ntf_data:LLVMValueRef=LLVMBuildCall2(builder,ntf_alloc_type,ntf_alloc_fn,ntf_alloc_args_ptr,2,"node.table.alloc")',
    'ntf_view<-LLVMBuildInsertValue(builder,ntf_view,darray_size_value_target(ntf_checked_count,ctx,builder,"node.table.view.len.target",structs.target.target_pointer_bits),1,"node.table.view.len")',
    'ntf_fill_type:LLVMTypeRef=LLVMFunctionType(LLVMVoidTypeInContext(ctx),ntf_fill_params_ptr,2,0)',
    'ntf_fill_fn:LLVMValueRef=declare_or_get_named(m,"arena_da_fill",ntf_fill_type)',
    'ntf_fill_args:mutabledarray[LLVMValueRef]=[ntf_view,ntf_init]',
    '_=LLVMBuildCall2(builder,ntf_fill_type,ntf_fill_fn,ntf_fill_args_ptr,2,"")',
    '_=LLVMBuildStore(builder,ntf_view,ntf_result_slot)',
    '_=LLVMBuildBr(builder,ntf_done_block)',
    'LLVMPositionBuilderAtEnd(builder,ntf_done_block)',
    'returnLLVMBuildLoad2(builder,ntf_view_type,ntf_result_slot,"node.table.result.value")',
)
require_ordered(call, node_table_steps, "node_table_fill checked allocation lowering")
if call.count('emit_expression(arguments[2],ntf_element,local_scope,fns,structs,generics,runtime,m,ctx,builder)') != 1:
    raise SystemExit("node_table_fill initializer must be evaluated exactly once before the empty/nonempty branch")

runtime_size = compact(function_section(RUNTIME_DECL.read_text(), "runtime_size_llvm_type"))
if "LLVMInt32TypeInContext(ctx)returniftarget_bits==32" not in runtime_size or \
        "returnLLVMInt64TypeInContext(ctx)" not in runtime_size:
    raise SystemExit("node_table_fill runtime count ABI must follow target usize")
runtime_argument = compact(function_section(RUNTIME_DECL.read_text(), "runtime_size_argument"))
if 'returnLLVMBuildTrunc(builder,value,size_type,"runtime.usize")iftarget_bits==32elseLLVMBuildZExt(builder,value,size_type,"runtime.usize")' not in runtime_argument:
    raise SystemExit("node_table_fill allocation byte argument must use checked target usize conversion")
count_normalizer = compact(function_section(INTERNED_TYPES.read_text(), "darray_size_value_i64"))
if "returnLLVMBuildZExt(builder,value,size_type,name)ifLLVMGetIntTypeWidth(source_type)<64elsevalue" not in count_normalizer:
    raise SystemExit("node_table_fill native usize count must be zero-extended before its i64 check")
target_size_conversion = compact(function_section(INTERNED_TYPES.read_text(), "darray_size_value_target"))
require_ordered(target_size_conversion, (
    "target_type:LLVMTypeRef=darray_size_type(ctx,target_bits)",
    "source_type:LLVMTypeRef=LLVMTypeOf(value)",
    "target_width:u32=target_bits",
    "source_width:u32=LLVMGetIntTypeWidth(source_type)",
    "ifsource_width>target_width:",
    "returnLLVMBuildTrunc(builder,value,target_type,name)",
    "ifsource_width<target_width:",
    "returnLLVMBuildZExt(builder,value,target_type,name)",
    "returnvalue",
), "node_table_fill result view usize conversion")

llvm_bindings = compact(LLVM_C.read_text())
if "NE:i32=33" not in llvm_bindings or "UGT:i32=34" not in llvm_bindings:
    raise SystemExit("node_table_fill comparison IDs no longer match their LLVMIntPredicate bindings")
target_pointer_bits = compact(function_section(VALUE_TYPE.read_text(), "target_pointer_bits"))
if target_pointer_bits != compact("""
def target_pointer_bits() -> u32:
    return 32 if getenv("ELISA_STAGE1_WASM") is wasm_target
    return 64
"""):
    raise SystemExit("node_table_fill target-size model must match the compiler's wasm32 and 64-bit targets")
if declarations(POSITIVE) != POSITIVE_NAMES or declarations(NEGATIVE) != NEGATIVE_NAMES:
    raise SystemExit("node_table_fill proof inventory changed")
if 'include "../../src/backend/codegen_cstr_terminator_policy.elisa"' not in POSITIVE.read_text() or \
        'include "./backend_node_table_fill_bounds.elisa"' not in NEGATIVE.read_text():
    raise SystemExit("node_table_fill proofs must reuse the production target-size policy and positive model")

positive_text = POSITIVE.read_text()
expected_positive = {
    "admitted_count_roundtrips_through_target_usize": "def admitted_count_roundtrips_through_target_usize(count:u64,pointer_bits:u32)->bool:\nrequires pointer_bits==BackendCStrTerminatorPolicy::POINTER_BITS_32 or pointer_bits==BackendCStrTerminatorPolicy::POINTER_BITS_64\nrequires count<=BackendCStrTerminatorPolicy::target_size_max(pointer_bits)\nensure result==true\nreturn (count%(BackendCStrTerminatorPolicy::U32_MAX+1)==count)ifpointer_bits==BackendCStrTerminatorPolicy::POINTER_BITS_32elsecount==count",
    "wasm32_count_guard_rejects_first_unrepresentable_count": "def wasm32_count_guard_rejects_first_unrepresentable_count()->bool:\nensure result==true\ncount:u64=BackendCStrTerminatorPolicy::U32_MAX+1\nreturnnot(count<=BackendCStrTerminatorPolicy::target_size_max(BackendCStrTerminatorPolicy::POINTER_BITS_32))",
    "admitted_node_count_fits_target_usize": "def admitted_node_count_fits_target_usize(count:u64,pointer_bits:u32)->bool:\nrequires pointer_bits==BackendCStrTerminatorPolicy::POINTER_BITS_32 or pointer_bits==BackendCStrTerminatorPolicy::POINTER_BITS_64\nrequires count<=BackendCStrTerminatorPolicy::target_size_max(pointer_bits)\nensure result==true\nreturn count<=BackendCStrTerminatorPolicy::target_size_max(pointer_bits)",
    "zero_stride_allocation_size_is_zero": "def zero_stride_allocation_size_is_zero(count:u64,pointer_bits:u32)->bool:\nrequires pointer_bits==BackendCStrTerminatorPolicy::POINTER_BITS_32 or pointer_bits==BackendCStrTerminatorPolicy::POINTER_BITS_64\nrequires count<=BackendCStrTerminatorPolicy::target_size_max(pointer_bits)\nensure result==true\nreturn count*0<=BackendCStrTerminatorPolicy::target_size_max(pointer_bits)",
    "positive_stride_allocation_size_fits_target": "def positive_stride_allocation_size_fits_target(count:u64,stride:u64,pointer_bits:u32)->bool:\nrequires pointer_bits==BackendCStrTerminatorPolicy::POINTER_BITS_32 or pointer_bits==BackendCStrTerminatorPolicy::POINTER_BITS_64\nrequires count<=BackendCStrTerminatorPolicy::target_size_max(pointer_bits)\nrequires stride>0 and stride<=BackendCStrTerminatorPolicy::target_size_max(pointer_bits)\nrequires count<=BackendCStrTerminatorPolicy::target_size_max(pointer_bits)/stride\nensure result==true\nreturn count*stride<=BackendCStrTerminatorPolicy::target_size_max(pointer_bits)",
    "empty_node_table_skips_the_fill_branch": "def empty_node_table_skips_the_fill_branch(count:u64)->bool:\nrequires count==0\nensure result==true\nreturnnot(count!=0)",
    "nonempty_node_table_has_the_requested_view_length": "def nonempty_node_table_has_the_requested_view_length(count:u64,pointer_bits:u32)->bool:\nrequires pointer_bits==BackendCStrTerminatorPolicy::POINTER_BITS_32 or pointer_bits==BackendCStrTerminatorPolicy::POINTER_BITS_64\nrequires count>0 and count<=BackendCStrTerminatorPolicy::target_size_max(pointer_bits)\nensure result==true\nview_length:u64=(count%(BackendCStrTerminatorPolicy::U32_MAX+1))ifpointer_bits==BackendCStrTerminatorPolicy::POINTER_BITS_32elsecount\nreturn view_length>0 and view_length==count",
}
for name, expected in expected_positive.items():
    if compact(function_section(positive_text, name)) != compact(expected):
        raise SystemExit(f"node_table_fill theorem {name} changed")

negative_text = NEGATIVE.read_text()
expected_negative = {
    "false_claim_first_unrepresentable_count_roundtrips": "def false_claim_first_unrepresentable_count_roundtrips()->bool:\nensure result==true\ncount:u64=BackendCStrTerminatorPolicy::U32_MAX+1\nreturncount%(BackendCStrTerminatorPolicy::U32_MAX+1)==count",
    "false_claim_wasm32_accepts_first_unrepresentable_count": "def false_claim_wasm32_accepts_first_unrepresentable_count()->bool:\nensure result==true\ncount:u64=BackendCStrTerminatorPolicy::U32_MAX+1\nreturncount<=BackendCStrTerminatorPolicy::target_size_max(BackendCStrTerminatorPolicy::POINTER_BITS_32)",
    "false_claim_u32_allocation_product_fits": "def false_claim_u32_allocation_product_fits()->bool:\nensure result==true\ncount:u64=65536\nstride:u64=65536\nreturncount*stride<=BackendCStrTerminatorPolicy::U32_MAX",
    "false_claim_empty_node_table_takes_the_fill_branch": "def false_claim_empty_node_table_takes_the_fill_branch()->bool:\nensure result==true\ncount:u64=0\nreturncount!=0",
}
for name, expected in expected_negative.items():
    if compact(function_section(negative_text, name)) != compact(expected):
        raise SystemExit(f"node_table_fill negative control {name} changed")

product = require_current_product(BIN, PROVER)
if product.get("compile_mode") != "strict":
    raise SystemExit("node_table_fill arithmetic proof requires a strict proof build")
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
    CALL,
    CONTAINER_OPS,
    INTERNED_TYPES,
    RUNTIME_DECL,
    VALUE_TYPE,
    LLVM_C,
    POLICY,
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
    "scope": "node_table_fill traps target-size overflow, bounds allocation bytes, and skips empty fills",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(NEGATIVE_NAMES),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "source_sha256": hashes_before,
}, sort_keys=True))
