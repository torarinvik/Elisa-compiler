"""Admit a source-bound proof that signed negative indices cannot reach a GEP."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
GUARDS = ROOT / "src/backend/codegen_guards.elisa"
CONVERT = ROOT / "src/backend/codegen_convert.elisa"
INDEX_READ = ROOT / "src/backend/codegen_expr_index_read.elisa"
ASSIGN = ROOT / "src/backend/codegen_stmt_assign_place.elisa"
STRUCT_REG = ROOT / "src/backend/codegen_struct_reg.elisa"
CALL_NAMED = ROOT / "src/backend/codegen_call_named.elisa"
PLACE = ROOT / "src/backend/codegen_place.elisa"
STRUCT_CHAIN = ROOT / "src/backend/codegen_struct_chain_type.elisa"
LOOPS = ROOT / "src/backend/codegen_stmt_loops.elisa"
CALL_RECEIVER = ROOT / "src/backend/codegen_call_receiver.elisa"
INTERNED_TYPES = ROOT / "src/backend/codegen_interned_types.elisa"
RUNTIME_DECL = ROOT / "src/backend/codegen_runtime_decl.elisa"
LLVM_TYPES = ROOT / "src/backend/codegen_llvm_types.elisa"
COLLECTIONS = ROOT / "elisacore_std/collections.elisa"
LITERALS = ROOT / "src/backend/codegen_expr_literals.elisa"
UNARY = ROOT / "src/backend/codegen_expr_unary.elisa"
POSITIVE = HERE / "backend_index_guard.elisa"
NEGATIVE = HERE / "backend_index_guard_rejected.elisa"
CHUNKS_POSITIVE = HERE / "backend_chunks_exact_validation.elisa"
CHUNKS_NEGATIVE = HERE / "backend_chunks_exact_validation_rejected.elisa"
LLVM_CONFIG = shutil.which(os.environ.get("LLVM_CONFIG", "llvm-config"))

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in text.splitlines())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)def {re.escape(name)}(?:\[[^\]\n]*\])?\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*(?:\[[^\]\n]*\])?\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


def require_ordered(source: str, steps: tuple[str, ...], label: str) -> None:
    positions: list[int] = []
    cursor = 0
    for step in steps:
        position = source.find(step, cursor)
        positions.append(position)
        if position >= 0:
            cursor = position + len(step)
    if any(position < 0 for position in positions):
        raise SystemExit(f"{label} changed its proved operation order: {positions}")


def llvm_integer_predicates() -> dict[str, int]:
    if LLVM_CONFIG is None:
        raise SystemExit("llvm-config is required to bind guard predicates to LLVM")
    include_dir = subprocess.run([LLVM_CONFIG, "--includedir"], check=True,
                                 capture_output=True, text=True, timeout=15).stdout.strip()
    header = Path(include_dir) / "llvm-c/Core.h"
    if not header.is_file():
        raise SystemExit(f"LLVM C API header is missing: {header}")
    text = header.read_text()
    end = re.search(r"\}\s*LLVMIntPredicate\s*;", text)
    start = text.rfind("typedef enum", 0, end.start()) if end else -1
    if end is None or start < 0:
        raise SystemExit("could not locate LLVMIntPredicate in llvm-c/Core.h")
    members = re.findall(r"\b(LLVMInt[A-Za-z0-9_]+)\s*(?:=\s*(\d+))?\s*,?", text[start:end.start()])
    values: dict[str, int] = {}
    current = -1
    for name, explicit in members:
        current = int(explicit) if explicit else current + 1
        values[name] = current
    return values


positive_names = {
    "signed_index_guard",
    "negative_signed_index_is_rejected",
    "nonnegative_signed_index_keeps_the_count_check",
    "unsigned_index_guard_is_exact",
    "index_source_is_signed",
    "untyped_integer_literal_forces_signed_index",
    "nonliteral_unmodeled_index_uses_expected_signedness",
    "modeled_index_keeps_source_signedness",
    "soa_row_membership_guard",
    "negative_signed_row_id_is_not_valid",
    "out_of_bounds_unsigned_index_is_rejected",
    "either_failed_guard_component_is_rejected",
    "negative_untyped_literal_never_passes_index_guard",
}
if declarations(POSITIVE) != positive_names:
    raise SystemExit("index-guard proof inventory changed")
negative_names = {
    "false_claim_negative_signed_index_can_pass",
    "false_claim_negative_untyped_literal_is_unsigned",
    "false_claim_out_of_bounds_unsigned_index_is_accepted",
    "false_claim_negative_untyped_literal_can_pass_index_guard",
}
if declarations(NEGATIVE) != negative_names or \
        'include "./backend_index_guard.elisa"' not in NEGATIVE.read_text():
    raise SystemExit("index-guard rejection control changed")
if compact(function_section(POSITIVE.read_text(), "out_of_bounds_unsigned_index_is_rejected")) != compact("""
def out_of_bounds_unsigned_index_is_rejected(index_nonnegative: bool) -> bool:
    ensure result == true
    return not signed_index_guard(index_nonnegative, false)
""") or compact(function_section(POSITIVE.read_text(), "either_failed_guard_component_is_rejected")) != compact("""
def either_failed_guard_component_is_rejected(index_nonnegative: bool, unsigned_in_bounds: bool) -> bool:
    ensure result == (not index_nonnegative or not unsigned_in_bounds)
    return not signed_index_guard(index_nonnegative, unsigned_in_bounds)
""") or compact(function_section(POSITIVE.read_text(), "negative_untyped_literal_never_passes_index_guard")) != compact("""
def negative_untyped_literal_never_passes_index_guard(untyped_integer_literal: bool, expected_is_signed: bool, unsigned_in_bounds: bool) -> bool:
    requires untyped_integer_literal
    ensure result == true
    source_is_signed: bool = untyped_integer_literal or expected_is_signed
    return not signed_index_guard(not source_is_signed, unsigned_in_bounds)
"""):
    raise SystemExit("index guard proofs no longer reject either an unsigned bounds failure or a signedness failure")
if declarations(CHUNKS_POSITIVE) != {
    "chunks_exact_guard",
    "chunks_exact_size_is_valid",
    "zero_chunk_size_is_rejected",
    "nonpositive_signed_chunk_size_is_rejected",
    "positive_signed_chunk_size_is_accepted",
    "nonzero_unsigned_chunk_size_is_accepted",
    "nondivisible_view_length_is_rejected",
    "accepted_input_has_both_preconditions",
    "every_exact_chunk_window_stays_within_length",
    "unsigned_counted_loop_condition_preserves_bound",
    "wasm32_roundtrip_rejects_high_source_bits",
}:
    raise SystemExit("chunks_exact validation proof inventory changed")
if declarations(CHUNKS_NEGATIVE) != {
    "false_claim_zero_chunk_size_is_accepted",
    "false_claim_negative_signed_chunk_size_is_accepted",
    "false_claim_nondivisible_input_is_accepted",
    "false_claim_wasm32_high_source_roundtrips",
    "false_claim_one_past_chunk_is_in_bounds",
} or 'include "./backend_chunks_exact_validation.elisa"' not in CHUNKS_NEGATIVE.read_text():
    raise SystemExit("chunks_exact validation rejection controls changed")

predicates = llvm_integer_predicates()
if predicates.get("LLVMIntULT") != 36 or predicates.get("LLVMIntSGE") != 39 or \
        predicates.get("LLVMIntNE") != 33 or predicates.get("LLVMIntEQ") != 32 or \
        predicates.get("LLVMIntSGT") != 38:
    raise SystemExit("LLVM index or chunks_exact integer predicate value changed")

guards_source = GUARDS.read_text()
count_guard = compact(function_section(guards_source, "emit_count_bounds_guard"))
require_ordered(count_guard, (
    'unsigned_valid:LLVMValueRef=LLVMBuildICmp(builder,36,compare_index,compare_count,"wd.in_bounds.unsigned")',
    'ifindex_is_signed:',
    'index_nonnegative:LLVMValueRef=LLVMBuildICmp(builder,39,index,LLVMConstInt(index_type,0,0),"wd.index.nonnegative")',
    'valid<-LLVMBuildAnd(builder,index_nonnegative,unsigned_valid,"wd.in_bounds.signed")',
    '_=LLVMBuildCondBr(builder,valid,ok_block,fail_block)',
), "signed count guard")
require_ordered(count_guard, (
    '_=LLVMBuildCondBr(builder,valid,ok_block,recovery_block)',
    'LLVMPositionBuilderAtEnd(builder,ok_block)',
    'return',
    '_=LLVMBuildCondBr(builder,valid,ok_block,fail_block)',
    'LLVMPositionBuilderAtEnd(builder,fail_block)',
    'emit_trap_unreachable(m,ctx,builder)',
    'LLVMPositionBuilderAtEnd(builder,ok_block)',
), "checked recovery and failure continuation")

convert_source = CONVERT.read_text()
index_values = compact(function_section(convert_source, "emit_index_value_pair"))
require_ordered(index_values, (
    "actual:mutableValueType=expression_type(expression,local_scope,fns,structs,generics)",
    "ifactual.kind==TypeKind.Unmodeled:",
    "actual<-ValueType{kind:TypeKind.Signed,bits:64}ifexpression_is_bare_integer_literal(expression)elseexpected",
    "if(emit_expression(expression,actual,local_scope,fns,structs,generics,runtime,m,ctx,builder)canGlobal{Read,Write})issource_value:",
    "target_value:mutableLLVMValueRef=source_value",
    "ifactual.kind!=expected.kindoractual.bits!=expected.bits:",
    "emit_conversion(source_value,actual,expected,structs,ctx,builder)isconverted:",
    "target_value<-converted",
    "returnIndexValuePair{source_value:source_value,target_value:target_value,is_signed:actual.kind==TypeKind.Signed}",
), "source-width index preservation")
conversion_body = compact(function_section(convert_source, "emit_conversion"))
require_ordered(conversion_body, (
    'valuereturniffrom_type.bits==to_type.bits',
    'LLVMBuildTrunc(builder,value,target,"trunc")returnifto_type.bits<from_type.bits',
    'LLVMBuildSExt(builder,value,target,"sext")iffrom_type.kind==TypeKind.SignedelseLLVMBuildZExt(builder,value,target,"zext")',
), "integer index narrowing conversion")
bare_integer_literal = compact(function_section(convert_source, "expression_is_bare_integer_literal"))
if "Expr.IntLit(_,_):returntrue" not in bare_integer_literal or \
        "Expr.Unary(operator,inner,_):returnexpression_is_bare_integer_literal(inner)ifoperator==TokenKind.Plusoroperator==TokenKind.Minuselsefalse" not in bare_integer_literal or \
        "Expr.Paren(inner,_):returnexpression_is_bare_integer_literal(inner)" not in bare_integer_literal:
    raise SystemExit("untyped signed integer literals must retain their i64 source width")
literal_emitter = compact(function_section(LITERALS.read_text(), "emit_expression_literals"))
require_ordered(literal_emitter, (
    "Expr.IntLit(literal_value,_):",
    "ifis_integer_type(expected):",
    "returnLLVMConstInt(llvm_type_of(expected,structs,ctx),literal_value.u64(),1)",
), "integer literal sign extension")
unary_emitter = compact(function_section(UNARY.read_text(), "emit_expression_unary"))
require_ordered(unary_emitter, (
    "operand_type:ValueType=resolve_type(unary_operand,expected,local_scope,fns,structs,generics)",
    "ifunary_operator==TokenKind.Minus:",
    'returnfinish_float_instruction(LLVMBuildFNeg(builder,operand,"fneg"),runtime.fast_math)ifoperand_type.kind==TypeKind.FloatelseLLVMBuildNeg(builder,operand,"neg")',
), "integer unary-minus emission")
require_ordered(index_values, (
    "actual:mutableValueType=expression_type(expression,local_scope,fns,structs,generics)",
    "ifactual.kind==TypeKind.Unmodeled:",
    "actual<-ValueType{kind:TypeKind.Signed,bits:64}ifexpression_is_bare_integer_literal(expression)elseexpected",
    "returnIndexValuePair{source_value:source_value,target_value:target_value,is_signed:actual.kind==TypeKind.Signed}",
), "source-index signedness selection")

guards = compact(function_section(guards_source, "emit_index_bounds_guard"))
if "ifindex_width<=64andLLVMIsAConstantInt(index)isconstant_index:" not in guards or \
        "constant_nonnegative:bool=notindex_is_signedorconstant_index_bits<signed_index_limit" not in guards or \
        "returnifconstant_nonnegativeandconstant_index_bits<extent" not in guards:
    raise SystemExit("fixed-array constant elision must not erase signed checks or wide index bits")
if "comparison_type:LLVMTypeRef=LLVMInt64TypeInContext(ctx)ifindex_width<64elseLLVMTypeOf(index)" not in guards:
    raise SystemExit("fixed-array extent no longer retains its u64 range before comparison")

call_patterns = (
    (CONVERT, "emit_darray_index_address", 'emit_index_bounds_guard(array_slot,array_type,index_values.source_value,index_values.is_signed', '[index_values.target_value]'),
    (CONVERT, "emit_view_index_address", 'emit_count_bounds_guard(index_values.source_value,view_len,index_values.is_signed', '[index_values.target_value]'),
    (CONVERT, "emit_index_address", 'emit_index_bounds_guard(array_slot,array_type,index_values.source_value,index_values.is_signed', 'index_values.target_value]'),
    (INDEX_READ, "emit_expression_index_read", 'emit_count_bounds_guard(view_index_values.source_value,LLVMBuildExtractValue(builder,view_index_agg,1,"view.len"),view_index_values.is_signed', '[view_index_values.target_value]'),
    (INDEX_READ, "emit_expression_index_read", 'emit_count_bounds_guard(ret_view_indices_values.source_value,LLVMBuildExtractValue(builder,ret_view_value,1,"view.len"),ret_view_indices_values.is_signed', '[ret_view_indices_values.target_value]'),
    (INDEX_READ, "emit_expression_index_read", 'emit_count_bounds_guard(chain_slice_index_values.source_value,chain_slice_length,chain_slice_index_values.is_signed', '[chain_slice_index_values.target_value]'),
    (INDEX_READ, "emit_expression_index_read", 'emit_count_bounds_guard(chunk_index_values.source_value,chunk_count,chunk_index_values.is_signed', '[LLVMBuildMul(builder,chunk_index_values.target_value,chunk_len,"chunk.offset")]'),
)
for path, function, guard_fragment, gep_fragment in call_patterns:
    body = compact(function_section(path.read_text(), function))
    require_ordered(body, (guard_fragment, gep_fragment), f"{path.name}:{function} index guard")

# These two access paths use unsigned GEP indexes. Their guards must consume the
# pre-conversion value and signedness tag, or a negative source index can wrap to
# a large unsigned value before the SGE check has a chance to reject it.
darray_index_body = compact(function_section(CONVERT.read_text(), "emit_darray_index_address"))
require_ordered(darray_index_body, (
    "index_type:ValueType=ValueType{kind:TypeKind.Unsigned,bits:structs.target.target_pointer_bits}",
    "darray_index_pair:mutableIndexValuePair?=null",
    "darray_index_pair<-emit_index_value_pair(index_expression,index_type,local_scope,fns,structs,generics,runtime,m,ctx,builder)",
    "ifdarray_index_pairisindex_values:",
    "emit_index_bounds_guard(array_slot,array_type,index_values.source_value,index_values.is_signed",
    "[index_values.target_value]",
), "dynamic-array signed source index before unsigned GEP")
view_store_body = compact(function_section(ASSIGN.read_text(), "emit_assign_to_place"))
require_ordered(view_store_body, (
    "view_assign_index_pair:mutableIndexValuePair?=null",
    "view_assign_index_pair<-emit_index_value_pair(assign_index,ValueType{kind:TypeKind.Unsigned,bits:structs.target.target_pointer_bits},local_scope,fns,structs,generics,runtime,m,ctx,builder)",
    "ifview_assign_index_pairisview_index_values:",
    "emit_count_bounds_guard(view_index_values.source_value,LLVMBuildLoad2(builder,runtime_size_llvm_type(ctx,structs.target.target_pointer_bits),view_len_pointer,\"view.assign.len\"),view_index_values.is_signed",
    "view_gep_indices:mutabledarray[LLVMValueRef]=[view_index_values.target_value]",
    "view_gep_pointer:void&=(&view_gep_indices[0]).cast[void&]canUnsafe.PointerCast",
    "LLVMBuildGEP2(builder,llvm_type_of(view_assign_element,structs,ctx),view_data,view_gep_pointer,1,\"view.assign.elem\")",
), "view-store signed source index before unsigned GEP")

slice_chain_body = compact(function_section(INDEX_READ.read_text(), "emit_expression_index_read"))
require_ordered(slice_chain_body, (
    "Expr.Slice(chain_slice_object,chain_slice_start,chain_slice_end,chain_slice_line):",
    "ifchain_slice_array.kind==TypeKind.Array:",
    "emit_index_value_pair(index_expression,ValueType{kind:TypeKind.Signed,bits:64},local_scope,fns,structs,generics,runtime,m,ctx,builder)",
    'chain_slice_data:LLVMValueRef=LLVMBuildExtractValue(builder,chain_slice_view_value,0,"sliceidx.data")',
    'chain_slice_length:LLVMValueRef=LLVMBuildExtractValue(builder,chain_slice_view_value,1,"sliceidx.len")',
    "emit_count_bounds_guard(chain_slice_index_values.source_value,chain_slice_length,chain_slice_index_values.is_signed,runtime,m,ctx,builder)",
    "chain_slice_gep:mutabledarray[LLVMValueRef]=[chain_slice_index_values.target_value]",
    'LLVMBuildGEP2(builder,chain_slice_element_llvm,chain_slice_data,chain_slice_gep_pointer,1,"sliceidx.ptr")',
), "nested array-slice indexing")

chunk_layout = compact(function_section(STRUCT_REG.read_text(), "synthesize_chunks_exact_view"))
if 'usize_type:ValueType=ValueType{kind:TypeKind.Unsigned,bits:structs.target.target_pointer_bits}' not in chunk_layout or \
        'chunk_names:mutabledarray[sview]=["source","chunk_size","len"]' not in chunk_layout or \
        'chunk_types:mutabledarray[ValueType]=[base_type,usize_type,copied_type(usize_type)]' not in chunk_layout:
    raise SystemExit("ChunksExactView size fields must remain target-sized usize values")
darray_header = compact(function_section(INTERNED_TYPES.read_text(), "darray_llvm_type"))
require_ordered(darray_header, (
    'size_type:LLVMTypeRef=darray_size_type(ctx,structs.target.target_pointer_bits)',
    'fields:mutabledarray[LLVMTypeRef]=[LLVMPointerTypeInContext(ctx,0),size_type,size_type]',
), "target-sized DArray header")
darray_size_type = compact(function_section(INTERNED_TYPES.read_text(), "darray_size_type"))
if 'LLVMInt32TypeInContext(ctx)returniftarget_bits==32' not in darray_size_type or \
        'returnLLVMInt64TypeInContext(ctx)' not in darray_size_type:
    raise SystemExit("DArray field 1 is no longer the target-sized element count")
darray_size_load = compact(function_section(INTERNED_TYPES.read_text(), "darray_load_size_i64"))
require_ordered(darray_size_load, (
    'loaded:LLVMValueRef=LLVMBuildLoad2(builder,darray_size_type(ctx,target_bits),pointer,name)',
    'returndarray_size_value_i64(loaded,ctx,builder,"darray.size.i64")',
), "DArray count load")
darray_size_norm = compact(function_section(INTERNED_TYPES.read_text(), "darray_size_value_i64"))
if 'returnLLVMBuildZExt(builder,value,size_type,name)ifLLVMGetIntTypeWidth(source_type)<64elsevalue' not in darray_size_norm:
    raise SystemExit("DArray count normalization must preserve unsigned usize values")
runtime_size_type = compact(function_section(RUNTIME_DECL.read_text(), "runtime_size_llvm_type"))
if 'LLVMInt32TypeInContext(ctx)returniftarget_bits==32' not in runtime_size_type or \
        'returnLLVMInt64TypeInContext(ctx)' not in runtime_size_type:
    raise SystemExit("runtime usize must use i32 on a 32-bit target and i64 otherwise")
view_llvm_type = compact(function_section(LLVM_TYPES.read_text(), "llvm_type_of"))
if 'view_fields:mutabledarray[LLVMTypeRef]=[LLVMPointerTypeInContext(ctx,0),runtime_size_llvm_type(ctx,structs.target.target_pointer_bits)]' not in view_llvm_type:
    raise SystemExit("DynArrayView length field no longer follows the target usize width")
if 'structDynArrayView:data:mutablevoid&?len:mutableusize' not in compact(COLLECTIONS.read_text()):
    raise SystemExit("the source DynArrayView length field is no longer usize")
view_fallback = compact(function_section(STRUCT_REG.read_text(), "synthesize_view_struct"))
if 'structs.records.field_types.push(ValueType{kind:TypeKind.Unsigned,bits:structs.target.target_pointer_bits})' not in view_fallback or \
        'runtime_size_llvm_type(structs.target.context,structs.target.target_pointer_bits)' not in view_fallback:
    raise SystemExit("synthesized DynArrayView length must match target usize in metadata and LLVM layout")
chunk_constructor = compact(function_section(CALL_NAMED.read_text(), "emit_call_named"))
require_ordered(chunk_constructor, (
    'ifcallee_name=="chunks_exact"andarguments.count==2:',
    'chunks_usize_type:ValueType=ValueType{kind:TypeKind.Unsigned,bits:structs.target.target_pointer_bits}',
    'chunks_len_pair:mutableIndexValuePair?=null',
    'chunks_len_pair<-emit_index_value_pair(arguments[1],chunks_usize_type,local_scope,fns,structs,generics,runtime,m,ctx,builder)',
    'ifchunks_len_pairischunks_len_values:',
    'chunks_len:LLVMValueRef=chunks_len_values.target_value',
    'chunks_total:LLVMValueRef=LLVMBuildExtractValue(builder,chunks_base,1,"chunks.total")',
    'emit_chunks_exact_validation(chunks_len_values.source_value,chunks_len,chunks_total,chunks_len_values.is_signed,m,ctx,builder)',
    'chunks_agg<-LLVMBuildInsertValue(builder,chunks_agg,chunks_base,0,"chunks.base")',
    'chunks_agg<-LLVMBuildInsertValue(builder,chunks_agg,chunks_len,1,"chunks.chunk")',
    'chunks_agg<-LLVMBuildInsertValue(builder,chunks_agg,LLVMBuildUDiv(builder,chunks_total,chunks_len,"chunks.count"),2,"chunks.count.ins")',
), "ChunksExactView count construction")
if "LLVMBuildSDiv(builder,chunks_total,chunks_len" in chunk_constructor:
    raise SystemExit("chunks_exact count must use unsigned division after validation")
chunks_validation = compact(function_section(guards_source, "emit_chunks_exact_validation"))
require_ordered(chunks_validation, (
    'chunk_type:LLVMTypeRef=LLVMTypeOf(chunk_size)',
    'chunk_source_type:LLVMTypeRef=LLVMTypeOf(chunk_size_source)',
    'source_positive:LLVMValueRef=LLVMBuildICmp(builder,LLVMIntPredicate::SGT,chunk_size_source,source_zero,"chunks.size.positive")ifchunk_size_is_signedelseLLVMConstInt(LLVMInt1TypeInContext(ctx),1,0)',
    'target_nonzero:LLVMValueRef=LLVMBuildICmp(builder,LLVMIntPredicate::NE,chunk_size,zero,"chunks.size.nonzero")',
    'fits_target:mutableLLVMValueRef=LLVMConstInt(LLVMInt1TypeInContext(ctx),1,0)',
    'ifLLVMGetIntTypeWidth(chunk_source_type)>LLVMGetIntTypeWidth(chunk_type):',
    'roundtrip:LLVMValueRef=LLVMBuildZExt(builder,chunk_size,chunk_source_type,"chunks.size.roundtrip")',
    'fits_target<-LLVMBuildICmp(builder,LLVMIntPredicate::EQ,roundtrip,chunk_size_source,"chunks.size.fits")',
    'size_valid:LLVMValueRef=LLVMBuildAnd(builder,source_positive,LLVMBuildAnd(builder,target_nonzero,fits_target,"chunks.size.target.valid"),"chunks.size.valid")',
    '_=LLVMBuildCondBr(builder,size_valid,nonzero_block,fail_block)',
    'LLVMPositionBuilderAtEnd(builder,fail_block)',
    'emit_trap_unreachable(m,ctx,builder)',
    'LLVMPositionBuilderAtEnd(builder,nonzero_block)',
    'remainder:LLVMValueRef=LLVMBuildURem(builder,total,chunk_size,"chunks.remainder")',
    'exact:LLVMValueRef=LLVMBuildICmp(builder,LLVMIntPredicate::EQ,remainder,zero,"chunks.divisible")',
    '_=LLVMBuildCondBr(builder,exact,exact_block,fail_block)',
    'LLVMPositionBuilderAtEnd(builder,exact_block)',
), "chunks_exact divisor and divisibility guard")
if "LLVMBuildSDiv" in chunks_validation or "LLVMBuildSRem" in chunks_validation:
    raise SystemExit("chunks_exact validation must use unsigned remainder after the source and target size checks")
chunk_index_body = compact(function_section(INDEX_READ.read_text(), "emit_expression_index_read"))
require_ordered(chunk_index_body, (
    'ifchunk_recv.kind==TypeKind.Structandsynthesized_struct_base_is(structs,chunk_recv,"ChunksExactView"):',
    'chunk_index_pair:mutableIndexValuePair?=null',
    'chunk_index_pair<-emit_index_value_pair(index_expression,ValueType{kind:TypeKind.Unsigned,bits:structs.target.target_pointer_bits},local_scope,fns,structs,generics,runtime,m,ctx,builder)',
    'ifchunk_index_pairischunk_index_values:',
    'chunk_base:LLVMValueRef=LLVMBuildExtractValue(builder,chunk_agg,0,"chunk.base")',
    'chunk_len:LLVMValueRef=LLVMBuildExtractValue(builder,chunk_agg,1,"chunk.len")',
    'chunk_count:LLVMValueRef=LLVMBuildExtractValue(builder,chunk_agg,2,"chunk.count")',
    'emit_count_bounds_guard(chunk_index_values.source_value,chunk_count,chunk_index_values.is_signed,runtime,m,ctx,builder)',
    'chunk_data:LLVMValueRef=LLVMBuildExtractValue(builder,chunk_base,0,"chunk.data")',
    'chunk_offsets:mutabledarray[LLVMValueRef]=[LLVMBuildMul(builder,chunk_index_values.target_value,chunk_len,"chunk.offset")]',
    'chunk_offsets_pointer:void&=(&chunk_offsets[0]).cast[void&]canUnsafe.PointerCast',
    'LLVMBuildGEP2(builder,llvm_type_of(chunk_element,structs,ctx),chunk_data,chunk_offsets_pointer,1,"chunk.at")',
    'chunk_result<-LLVMBuildInsertValue(builder,chunk_result,chunk_at,0,"chunk.view.data")',
    'chunk_result<-LLVMBuildInsertValue(builder,chunk_result,chunk_len,1,"chunk.view.len")',
    'returnchunk_result',
), "ChunksExactView checked indexing")

soa_binder_body = compact(function_section(STRUCT_CHAIN.read_text(), "soa_binder_element_address"))
require_ordered(soa_binder_body, (
    'defsoa_binder_element_address(binder_row:usize,field:sview,structs:mutableStructTable&,runtime:Runtime&,m:LLVMModuleRef,ctx:LLVMContextRef,builder:LLVMBuilderRef)',
    'column_pointer:LLVMValueRef=LLVMBuildStructGEP2(builder,owner_llvm,structs.loops.soa_row_binder_bases[binder_row],column.u32(),"soa.bind.col")',
    'count_pointer:LLVMValueRef=LLVMBuildStructGEP2(builder,darray_llvm_type(structs,ctx),column_pointer,1,"soa.bind.count.ptr")',
    'count:LLVMValueRef=darray_load_size_i64(count_pointer,ctx,builder,"soa.bind.count",structs.target.target_pointer_bits)',
    'at:LLVMValueRef=LLVMBuildLoad2(builder,LLVMInt64TypeInContext(ctx),structs.loops.soa_row_binder_indexes[binder_row],"soa.bind.at")',
    'emit_count_bounds_guard(at,count,true,runtime,m,ctx,builder)',
    'LLVMBuildGEP2(builder,llvm_type_of(element_type,structs,ctx),items,offsets_pointer,1,"soa.bind.elem")',
), "SoA row-binder per-column bounds")

soa_place_body = compact(function_section(PLACE.read_text(), "struct_chain_address"))
require_ordered(soa_place_body, (
    'Expr.Index(soa_row_object,soa_row_index,soa_row_line):',
    'soa_row_column:i64=field_index_of(structs,soa_row_slot,chain_field)',
    'soa_row_index_pair:mutableIndexValuePair?=null',
    'soa_row_index_pair<-emit_index_value_pair(soa_row_index,ValueType{kind:TypeKind.Signed,bits:64},local_scope,fns,structs,generics,runtime,m,ctx,builder)',
    'ifsoa_row_index_pairissoa_row_index_values:',
    'soa_row_at:LLVMValueRef=soa_row_index_values.target_value',
    'soa_row_col_pointer:LLVMValueRef=LLVMBuildStructGEP2(builder,soa_row_llvm,soa_row_base,soa_row_column.u32(),"soa.row.col")',
    'soa_row_count_pointer:LLVMValueRef=LLVMBuildStructGEP2(builder,darray_llvm_type(structs,ctx),soa_row_col_pointer,1,"soa.row.count.ptr")',
    'soa_row_count:LLVMValueRef=darray_load_size_i64(soa_row_count_pointer,ctx,builder,"soa.row.count",structs.target.target_pointer_bits)',
    'emit_count_bounds_guard(soa_row_index_values.source_value,soa_row_count,soa_row_index_values.is_signed,runtime,m,ctx,builder)',
    'soa_row_offsets:mutabledarray[LLVMValueRef]=[soa_row_at]',
    'LLVMBuildGEP2(builder,llvm_type_of(soa_row_element,structs,ctx),soa_row_items,soa_row_offset_pointer,1,"soa.row.elem")',
), "indexed SoA column bounds")

soa_loop_body = compact(function_section(LOOPS.read_text(), "emit_statement_loops"))
require_ordered(soa_loop_body, (
    'soa_iter_count:LLVMValueRef=darray_load_size_i64(LLVMBuildStructGEP2(builder,darray_llvm_type(structs,ctx),soa_iter_col0,1,"soa.iter.count.ptr"),ctx,builder,"soa.iter.count",structs.target.target_pointer_bits)',
    'soa_iter_at:LLVMValueRef=LLVMBuildLoad2(builder,soa_iter_i64,soa_iter_index,"soa.iter.at")',
    '_=LLVMBuildCondBr(builder,LLVMBuildICmp(builder,LLVMIntPredicate::ULT,soa_iter_at,soa_iter_count,"soa.iter.more"),soa_iter_body,soa_iter_done)',
    'LLVMPositionBuilderAtEnd(builder,soa_iter_body)',
), "unsigned SoA row iteration bound")
require_ordered(soa_loop_body, (
    'soa_de_column:LLVMValueRef=LLVMBuildStructGEP2(builder,soa_iter_llvm,soa_iter_base,soa_de_index.u32(),"soa.de.col")',
    'soa_de_count_pointer:LLVMValueRef=LLVMBuildStructGEP2(builder,darray_llvm_type(structs,ctx),soa_de_column,1,"soa.de.count.ptr")',
    'soa_de_count:LLVMValueRef=darray_load_size_i64(soa_de_count_pointer,ctx,builder,"soa.de.count",structs.target.target_pointer_bits)',
    'soa_de_at:LLVMValueRef=LLVMBuildLoad2(builder,soa_iter_i64,soa_iter_index,"soa.de.at")',
    'emit_count_bounds_guard(soa_de_at,soa_de_count,true,runtime,m,ctx,builder)',
    'LLVMBuildGEP2(builder,soa_de_llvm,soa_de_items,soa_de_offset_pointer,1,"soa.de.elem")',
), "destructured SoA per-column bounds")

require_ordered(soa_loop_body, (
    'ce_usize:LLVMTypeRef=runtime_size_llvm_type(ctx,structs.target.target_pointer_bits)',
    'ce_base:LLVMValueRef=LLVMBuildExtractValue(builder,ce_agg,0,"ce.base")',
    'ce_len:LLVMValueRef=LLVMBuildExtractValue(builder,ce_agg,1,"ce.len")',
    'ce_count:LLVMValueRef=LLVMBuildExtractValue(builder,ce_agg,2,"ce.count")',
    'ce_data:LLVMValueRef=LLVMBuildExtractValue(builder,ce_base,0,"ce.data")',
    'ce_index:LLVMValueRef=build_entry_alloca(builder,ce_usize,"ce.i")',
    '_=LLVMBuildStore(builder,LLVMConstInt(ce_usize,0,0),ce_index)',
    'ce_function:LLVMValueRef=LLVMGetBasicBlockParent(LLVMGetInsertBlock(builder))',
    'ce_cond:LLVMBasicBlockRef=LLVMAppendBasicBlockInContext(ctx,ce_function,"ce.cond")',
    'ce_bodyb:LLVMBasicBlockRef=LLVMAppendBasicBlockInContext(ctx,ce_function,"ce.body")',
    'ce_step:LLVMBasicBlockRef=LLVMAppendBasicBlockInContext(ctx,ce_function,"ce.step")',
    'ce_exit:LLVMBasicBlockRef=LLVMAppendBasicBlockInContext(ctx,ce_function,"ce.exit")',
    '_=LLVMBuildBr(builder,ce_cond)',
    'LLVMPositionBuilderAtEnd(builder,ce_cond)',
    'ce_cur:LLVMValueRef=LLVMBuildLoad2(builder,ce_usize,ce_index,"ce.cur")',
    '_=LLVMBuildCondBr(builder,LLVMBuildICmp(builder,LLVMIntPredicate::ULT,ce_cur,ce_count,"ce.more"),ce_bodyb,ce_exit)',
    'LLVMPositionBuilderAtEnd(builder,ce_bodyb)',
    'ce_offsets:mutabledarray[LLVMValueRef]=[LLVMBuildMul(builder,ce_cur,ce_len,"ce.offset")]',
    'ce_offsets_pointer:void&=(&ce_offsets[0]).cast[void&]canUnsafe.PointerCast',
    'LLVMBuildGEP2(builder,llvm_type_of(ce_element,structs,ctx),ce_data,ce_offsets_pointer,1,"ce.at")',
    'ce_chunk<-LLVMBuildInsertValue(builder,ce_chunk,ce_at,0,"ce.chunk.data")',
    'ce_chunk<-LLVMBuildInsertValue(builder,ce_chunk,ce_len,1,"ce.chunk.len")',
    '_=LLVMBuildStore(builder,ce_chunk,ce_bind)',
    'branch_if_open(ce_status,builder,ce_step)',
    'LLVMPositionBuilderAtEnd(builder,ce_step)',
    '_=LLVMBuildStore(builder,LLVMBuildAdd(builder,LLVMBuildLoad2(builder,ce_usize,ce_index,"ce.next.cur"),LLVMConstInt(ce_usize,1,0),"ce.next"),ce_index)',
    '_=LLVMBuildBr(builder,ce_cond)',
), "unsigned ChunksExactView iteration bounds")
if 'ce_i64:LLVMTypeRef=LLVMInt64TypeInContext(ctx)' in soa_loop_body:
    raise SystemExit("ChunksExactView iteration index must match target usize field widths")

soa_valid_body = compact(function_section(CALL_RECEIVER.read_text(), "emit_call_receiver"))
require_ordered(soa_valid_body, (
    'soa_valid_row_pair:mutableIndexValuePair?=null',
    'soa_valid_row_pair<-emit_index_value_pair(arguments[0],ValueType{kind:TypeKind.Signed,bits:64},local_scope,fns,structs,generics,runtime,m,ctx,builder)',
    'ifsoa_valid_row_pairissoa_valid_row_values:',
    'soa_valid_in_bounds:LLVMValueRef=LLVMBuildICmp(builder,LLVMIntPredicate::ULT,soa_valid_row_values.target_value,soa_valid_count,"soa.valid.in_bounds")',
    'ifsoa_valid_row_values.is_signed:',
    'soa_valid_nonnegative:LLVMValueRef=LLVMBuildICmp(builder,LLVMIntPredicate::SGE,soa_valid_row_values.source_value,LLVMConstInt(soa_valid_source_type,0,0),"soa.valid.nonnegative")',
    'returnLLVMBuildAnd(builder,soa_valid_nonnegative,soa_valid_in_bounds,"soa.valid")',
    'returnsoa_valid_in_bounds',
), "SoA rows.valid signed membership")

soa_binder_callers = (
    PLACE,
    ROOT / "src/backend/codegen_stmt_assign_place.elisa",
    ROOT / "src/backend/codegen_expr_calls.elisa",
    ROOT / "src/backend/codegen_stmt_binding_blocks.elisa",
)
soa_binder_call_lines = [
    line for path in soa_binder_callers for line in path.read_text().splitlines()
    if "soa_binder_element_address(" in line
]
if len(soa_binder_call_lines) != 4 or any("runtime, m, ctx, builder" not in line for line in soa_binder_call_lines):
    raise SystemExit("all SoA binder address callsites must thread the checked access context")

backend_sources = sorted((ROOT / "src/backend").rglob("*.elisa"), key=str)
backend_text = "\n".join(path.read_text() for path in backend_sources)
if backend_text.count("emit_count_bounds_guard(") != 11 or \
        backend_text.count("emit_index_bounds_guard(") != 3 or \
        backend_text.count("emit_index_value_pair(") != 12:
    raise SystemExit("backend index-guard callsite inventory changed; extend the proof bindings")

positive_text = POSITIVE.read_text()
expected_positive = {
    "signed_index_guard": "def signed_index_guard(index_nonnegative:bool,unsigned_in_bounds:bool)->bool:\nensure result==(index_nonnegative and unsigned_in_bounds)\nreturn index_nonnegative and unsigned_in_bounds",
    "negative_signed_index_is_rejected": "def negative_signed_index_is_rejected(unsigned_in_bounds:bool)->bool:\nensure result==true\nreturn not signed_index_guard(false,unsigned_in_bounds)",
    "nonnegative_signed_index_keeps_the_count_check": "def nonnegative_signed_index_keeps_the_count_check(unsigned_in_bounds:bool)->bool:\nensure result==true\nreturn signed_index_guard(true,unsigned_in_bounds)==unsigned_in_bounds",
    "unsigned_index_guard_is_exact": "def unsigned_index_guard_is_exact(unsigned_in_bounds:bool)->bool:\nensure result==true\nreturn unsigned_in_bounds==unsigned_in_bounds",
    "index_source_is_signed": "def index_source_is_signed(actual_is_modeled:bool,actual_is_signed:bool,expected_is_signed:bool,untyped_integer_literal:bool)->bool:\nensure result==(actual_is_signed if actual_is_modeled else (untyped_integer_literal or expected_is_signed))\nreturn actual_is_signed if actual_is_modeled else (untyped_integer_literal or expected_is_signed)",
    "untyped_integer_literal_forces_signed_index": "def untyped_integer_literal_forces_signed_index(actual_is_signed:bool,expected_is_signed:bool)->bool:\nrequires not actual_is_signed\nrequires not expected_is_signed\nensure result==true\nreturn index_source_is_signed(false,actual_is_signed,expected_is_signed,true)",
    "nonliteral_unmodeled_index_uses_expected_signedness": "def nonliteral_unmodeled_index_uses_expected_signedness(expected_is_signed:bool)->bool:\nensure result==true\nreturn index_source_is_signed(false,false,expected_is_signed,false)==expected_is_signed",
    "modeled_index_keeps_source_signedness": "def modeled_index_keeps_source_signedness(actual_is_signed:bool,expected_is_signed:bool,untyped_integer_literal:bool)->bool:\nensure result==true\nreturn index_source_is_signed(true,actual_is_signed,expected_is_signed,untyped_integer_literal)==actual_is_signed",
    "soa_row_membership_guard": "def soa_row_membership_guard(index_nonnegative:bool,unsigned_in_bounds:bool)->bool:\nensure result==(index_nonnegative and unsigned_in_bounds)\nreturn index_nonnegative and unsigned_in_bounds",
    "negative_signed_row_id_is_not_valid": "def negative_signed_row_id_is_not_valid(unsigned_in_bounds:bool)->bool:\nensure result==true\nreturn not soa_row_membership_guard(false,unsigned_in_bounds)",
    "negative_untyped_literal_never_passes_index_guard": "def negative_untyped_literal_never_passes_index_guard(untyped_integer_literal:bool,expected_is_signed:bool,unsigned_in_bounds:bool)->bool:\nrequires untyped_integer_literal\nensure result==true\nsource_is_signed:bool=untyped_integer_literal or expected_is_signed\nreturn not signed_index_guard(not source_is_signed,unsigned_in_bounds)",
}
for name, expected in expected_positive.items():
    if compact(function_section(positive_text, name)) != compact(expected):
        raise SystemExit(f"index-guard theorem {name} changed")
negative_text = compact(NEGATIVE.read_text())
if "requiresunsigned_in_boundsensureresult==truereturnsigned_index_guard(false,unsigned_in_bounds)" not in negative_text or \
        "requiresnotexpected_is_signedensureresult==truereturnnotindex_source_is_signed(false,false,expected_is_signed,true)" not in negative_text or \
        "requiresuntyped_integer_literalensureresult==truesource_is_signed:bool=untyped_integer_literalorexpected_is_signedreturnsigned_index_guard(notsource_is_signed,unsigned_in_bounds)" not in negative_text:
    raise SystemExit("false negative-index acceptance control changed")

chunks_positive_text = CHUNKS_POSITIVE.read_text()
chunks_expected = {
    "chunks_exact_guard": "def chunks_exact_guard(size_valid:bool,remainder_is_zero:bool)->bool:\nensure result==(size_valid and remainder_is_zero)\nreturn size_valid and remainder_is_zero",
    "chunks_exact_size_is_valid": "def chunks_exact_size_is_valid(source_size:i64,target_size:usize,is_signed:bool,fits_target:bool)->bool:\nensure result==((not is_signed or source_size>0) and target_size!=0 and fits_target)\nreturn (not is_signed or source_size>0) and target_size!=0 and fits_target",
    "zero_chunk_size_is_rejected": "def zero_chunk_size_is_rejected(remainder_is_zero:bool)->bool:\nensure result==true\nreturn not chunks_exact_guard(chunks_exact_size_is_valid(0,0,true,true),remainder_is_zero)",
    "nonpositive_signed_chunk_size_is_rejected": "def nonpositive_signed_chunk_size_is_rejected(source_size:i64,target_size:usize,fits_target:bool,remainder_is_zero:bool)->bool:\nrequires source_size<=0\nensure result==true\nreturn not chunks_exact_guard(chunks_exact_size_is_valid(source_size,target_size,true,fits_target),remainder_is_zero)",
    "positive_signed_chunk_size_is_accepted": "def positive_signed_chunk_size_is_accepted(source_size:i64,target_size:usize,fits_target:bool)->bool:\nrequires source_size>0 and target_size>0 and fits_target\nensure result==true\nreturn chunks_exact_size_is_valid(source_size,target_size,true,fits_target)",
    "nonzero_unsigned_chunk_size_is_accepted": "def nonzero_unsigned_chunk_size_is_accepted(target_size:usize,fits_target:bool)->bool:\nrequires target_size!=0 and fits_target\nensure result==true\nreturn chunks_exact_size_is_valid(0,target_size,false,fits_target)",
    "wasm32_roundtrip_rejects_high_source_bits": "def wasm32_roundtrip_rejects_high_source_bits(source_size:i64,roundtrip:i64)->bool:\nrequires source_size>4294967295\nrequires roundtrip>=0 and roundtrip<=4294967295\nensure result==true\nreturn roundtrip!=source_size",
    "nondivisible_view_length_is_rejected": "def nondivisible_view_length_is_rejected(size_valid:bool)->bool:\nensure result==true\nreturn not chunks_exact_guard(size_valid,false)",
    "accepted_input_has_both_preconditions": "def accepted_input_has_both_preconditions(size_valid:bool,remainder_is_zero:bool)->bool:\nensure result==true\nreturn chunks_exact_guard(size_valid,remainder_is_zero)==(size_valid and remainder_is_zero)",
    "every_exact_chunk_window_stays_within_length": "def every_exact_chunk_window_stays_within_length(total:usize,chunk_size:usize,count:usize,index:usize)->bool:\nrequires chunk_size>0\nrequires count==total/chunk_size\nrequires index<count\nensure result==true\nreturn index*chunk_size+chunk_size<=total",
    "unsigned_counted_loop_condition_preserves_bound": "def unsigned_counted_loop_condition_preserves_bound(index:usize,count:usize)->bool:\nensure result==(index<count)\nreturn index<count",
}
for name, expected in chunks_expected.items():
    if compact(function_section(chunks_positive_text, name)) != compact(expected):
        raise SystemExit(f"chunks_exact validation theorem {name} changed")
chunks_negative_text = CHUNKS_NEGATIVE.read_text()
chunks_negative_expected = {
    "false_claim_zero_chunk_size_is_accepted": "def false_claim_zero_chunk_size_is_accepted(remainder_is_zero:bool)->bool:\nensure result==true\nreturn chunks_exact_guard(chunks_exact_size_is_valid(0,0,true,true),remainder_is_zero)",
    "false_claim_negative_signed_chunk_size_is_accepted": "def false_claim_negative_signed_chunk_size_is_accepted(source_size:i64,target_size:usize,fits_target:bool,remainder_is_zero:bool)->bool:\nrequires source_size<0\nensure result==true\nreturn chunks_exact_guard(chunks_exact_size_is_valid(source_size,target_size,true,fits_target),remainder_is_zero)",
    "false_claim_nondivisible_input_is_accepted": "def false_claim_nondivisible_input_is_accepted(size_valid:bool)->bool:\nensure result==true\nreturn chunks_exact_guard(size_valid,false)",
    "false_claim_wasm32_high_source_roundtrips": "def false_claim_wasm32_high_source_roundtrips(source_size:i64,roundtrip:i64)->bool:\nrequires source_size>4294967295\nrequires roundtrip>=0 and roundtrip<=4294967295\nensure result==true\nreturn roundtrip==source_size",
    "false_claim_one_past_chunk_is_in_bounds": "def false_claim_one_past_chunk_is_in_bounds(total:usize,chunk_size:usize,index:usize)->bool:\nrequires chunk_size>0\nrequires index==total/chunk_size\nensure result==true\nreturn index*chunk_size+chunk_size<=total",
}
for name, expected in chunks_negative_expected.items():
    if compact(function_section(chunks_negative_text, name)) != compact(expected):
        raise SystemExit(f"chunks_exact false-claim control {name} changed")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("backend index-guard proof requires a strict proof build")

compiler_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
compiler_provenance = Path(str(compiler_product) + ".provenance.json").resolve(strict=True)
llvm_header = Path(subprocess.run([LLVM_CONFIG, "--includedir"], check=True,
                                  capture_output=True, text=True, timeout=15).stdout.strip()) / "llvm-c/Core.h"
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", compiler_product, compiler_provenance,
    Path(__file__), HERE / "proof_product_gate.py", POSITIVE, NEGATIVE,
    CHUNKS_POSITIVE, CHUNKS_NEGATIVE,
    *source_include_closure([POSITIVE, NEGATIVE, CHUNKS_POSITIVE, CHUNKS_NEGATIVE]),
    GUARDS, CONVERT, INDEX_READ, ASSIGN, STRUCT_REG, CALL_NAMED, INTERNED_TYPES,
    RUNTIME_DECL, LLVM_TYPES, COLLECTIONS, LITERALS, UNARY, llvm_header, *backend_sources,
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=60)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    assert report["kernel"]["independent_replay"] is True
    assert report["trust"]["kernel_replayed_certificates"] == report["replay"]["replayed"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["declarations"] == len(positive_names)
assert positive["summary"]["obligations"] == positive["summary"]["proven"] == 26
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "backend index-guard proof report changed across identical runs"

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["declarations"] == len(positive_names) + len(negative_names)
assert negative["summary"]["obligations"] == 34 and negative["summary"]["proven"] == 26
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" and row["status"] == "unknown"
           for row in negative["findings"])

chunks_code, chunks_positive = run(CHUNKS_POSITIVE)
assert chunks_code == 0 and chunks_positive["status"] == chunks_positive["verification_state"] == "proved"
assert chunks_positive["summary"]["declarations"] == 11
assert chunks_positive["summary"]["obligations"] == chunks_positive["summary"]["proven"]
assert not chunks_positive["findings"]
assert chunks_positive == run(CHUNKS_POSITIVE)[1], "chunks_exact proof report changed across identical runs"

chunks_code, chunks_negative = run(CHUNKS_NEGATIVE)
assert chunks_code == 1 and chunks_negative["status"] == "failed"
assert chunks_negative["summary"]["declarations"] == 16
assert chunks_negative["summary"]["proven"] <= chunks_negative["summary"]["obligations"]
assert {row["name"] for row in chunks_negative["findings"]} == {
    "false_claim_zero_chunk_size_is_accepted",
    "false_claim_negative_signed_chunk_size_is_accepted",
    "false_claim_nondivisible_input_is_accepted",
    "false_claim_wasm32_high_source_roundtrips",
    "false_claim_one_past_chunk_is_in_bounds",
}
assert all(row["kind"] == "ensure-unproven" and row["status"] == "unknown"
           for row in chunks_negative["findings"])
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product
print(json.dumps({
    "admitted": True,
    "scope": "signed index nonnegativity plus count bounds across backend array/view GEPs, and nonzero exact chunks_exact construction with unsigned remainder/division",
    "positive_obligations": positive["summary"]["proven"],
    "negative_claim_refused": "false_claim_negative_signed_index_can_pass",
    "chunks_exact_positive_obligations": chunks_positive["summary"]["proven"],
    "chunks_exact_false_claims_refused": sorted(row["name"] for row in chunks_negative["findings"]),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "source_sha256": hashes_before,
}, sort_keys=True))
