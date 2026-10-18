"""Replay proofs for packed-store ordinal and NodeKey index lowering."""
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
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
POSITIVE = HERE / "backend_packed_store_index.elisa"
NEGATIVE = HERE / "backend_packed_store_index_rejected.elisa"
INDEX_FIELDS = ROOT / "src/backend/codegen_expr_index_fields.elisa"
DISPATCH = ROOT / "src/backend/codegen_dispatch.elisa"
TYPE_PLACE = ROOT / "src/backend/codegen_expression_type_place.elisa"
ANNOTATION_INDEX = ROOT / "src/backend/codegen_annotation_index.elisa"
LLVM_TYPES = ROOT / "src/backend/codegen_llvm_types.elisa"
VALUE_CALL = ROOT / "src/backend/codegen_call.elisa"
RUNTIME = ROOT / "elisacore_std/stores_core.elisa"
CONTAINER_OPS = ROOT / "src/backend/codegen_container_ops.elisa"
CODEGEN_CALLS = ROOT / "src/backend/codegen_stmt_expr_calls.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(source: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in source.splitlines())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


POSITIVE_NAMES = {
    "packed_store_index_is_direct_handle",
    "packed_store_index_is_ordinal_lookup",
    "packed_store_index_is_declined",
    "node_key_uses_direct_handle_route",
    "integer_literal_i32_uses_ordinal_lookup",
    "nonliteral_signed_i32_uses_direct_handle",
    "integer_literal_i32_does_not_use_direct_handle",
    "nonliteral_other_width_declines",
    "packed_aos_mode_declines",
    "nonpacked_receiver_declines",
    "no_input_can_take_both_packed_store_routes",
    "every_index_is_routed_or_declined",
    "packed_store_ordinal_in_bounds",
    "ordinal_equal_to_count_is_out_of_bounds",
    "empty_store_has_no_nonnegative_ordinal",
    "packed_store_empty_columns_are_aligned",
    "packed_store_global_index_cast_fits_u32",
    "packed_store_next_metadata_count_fits_u32_limit",
    "packed_store_append_preserves_index_alignment",
}
NEGATIVE_NAMES = {
    "a_literal_i32_is_a_direct_key",
    "a_nonliteral_i32_is_an_ordinal",
    "packed_aos_mode_has_an_ordinal_route",
    "a_full_handle_count_can_be_cast_to_u32_without_truncation",
}


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


def validate_source(index_text: str, dispatch_text: str, type_text: str, llvm_text: str,
                    runtime_text: str, container_ops_text: str, codegen_calls_text: str,
                    annotation_text: str, value_call_text: str) -> list[str]:
    errors = []
    try:
        index = compact(function_section(index_text, "emit_expression_index_fields"))
        dispatch = compact(function_section(dispatch_text, "emit_expression"))
        packed_type = compact(function_section(type_text, "expression_type_of_place"))
        annotation_type = compact(function_section(annotation_text, "annotation_index_named_value_type"))
        llvm_type = compact(function_section(llvm_text, "llvm_type_of"))
        value_call = compact(function_section(value_call_text, "emit_call"))
        runtime = compact(function_section(runtime_text, "ctx_packed_store_index_at"))
        initialize = compact(function_section(runtime_text, "ctx_packed_store_state_new"))
        fixed_allocation = compact(function_section(runtime_text, "ctx_packed_store_alloc_fixed_result"))
        sized_allocation = compact(function_section(runtime_text, "ctx_packed_store_alloc_result"))
        push = compact(function_section(container_ops_text, "emit_darray_push"))
        push_call_dispatch = compact(function_section(codegen_calls_text, "emit_statement_expr_calls"))
    except SystemExit as error:
        return [str(error)]

    required_index = (
        "store_ix_is_ordinal:bool=matchstore_ix_expression:Expr.IntLit(_,_):true_:false",
        "store_ix_is_key:bool=store_ix_key_type.kind==TypeKind.Signedandstore_ix_key_type.bits==32",
        "ifstore_ix_type.kind==TypeKind.PackedStoreandruntime.packed_mode!=2andstore_ix_is_keyandnotstore_ix_is_ordinal:",
        "returnemit_expression(store_ix_expression,ValueType{kind:TypeKind.Signed,bits:32},local_scope,fns,structs,generics,runtime,m,ctx,builder)canGlobal{Read,Write}",
        "ifstore_ix_type.kind==TypeKind.PackedStoreandruntime.packed_mode!=2andstore_ix_is_ordinal:",
        "emit_expression(store_ix_expression,ValueType{kind:TypeKind.Unsigned,bits:64},local_scope,fns,structs,generics,runtime,m,ctx,builder)",
        "store_ix_state:LLVMValueRef=LLVMBuildExtractValue(builder,store_ix_value,2,\"packed.store.index.state\")",
        "store_ix_params:mutabledarray[LLVMTypeRef]=[LLVMPointerTypeInContext(ctx,0),LLVMInt64TypeInContext(ctx)]",
        "store_ix_fn_type:LLVMTypeRef=LLVMFunctionType(LLVMInt32TypeInContext(ctx),store_ix_params_ptr,2,0)",
        'declare_or_get_named(m,"ctx_packed_store_index_at",store_ix_fn_type)',
        'returnLLVMBuildCall2(builder,store_ix_fn_type,store_ix_fn,store_ix_args_ptr,2,"packed.store.index")',
    )
    for fragment in required_index:
        if fragment not in index:
            errors.append(f"packed-store lowering no longer contains source-bound route step: {fragment}")

    ordered_index = (
        "store_ix_is_ordinal:bool=matchstore_ix_expression:",
        "store_ix_key_type:ValueType=expression_type(store_ix_expression,local_scope,fns,structs,generics)",
        "store_ix_is_key:bool=",
        "ifstore_ix_type.kind==TypeKind.PackedStoreandruntime.packed_mode!=2andstore_ix_is_keyandnotstore_ix_is_ordinal:",
        "returnemit_expression(store_ix_expression,ValueType{kind:TypeKind.Signed,bits:32}",
        "ifstore_ix_type.kind==TypeKind.PackedStoreandruntime.packed_mode!=2andstore_ix_is_ordinal:",
        'declare_or_get_named(m,"ctx_packed_store_index_at",store_ix_fn_type)',
        'returnLLVMBuildCall2(builder,store_ix_fn_type,store_ix_fn,store_ix_args_ptr,2,"packed.store.index")',
    )
    positions = [index.find(fragment) for fragment in ordered_index]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        errors.append("packed-store ordinal/key classification or emission order changed")
    if index.count("store_ix_type.kind==TypeKind.PackedStore") != 2:
        errors.append("packed-store expression lowering gained an unproved alternate subscript route")
    if index.find("matchexpression:Expr.Index(store_ix_object,store_ix_expression,store_ix_line):") >= index.find(
            "matchexpression:Expr.Index(gref_head,gref_argument,gref_line):"):
        errors.append("packed-store ordinal/key route must precede generic type-argument indexing")

    for fragment in (
        "handled<-true",
        'matchexpression:Expr.Index(store_ix_object,store_ix_expression,store_ix_line):',
        'ifindex_fields_handled:',
        'remember_expression_decline(expression,structs)',
    ):
        if fragment not in index and fragment not in dispatch:
            errors.append(f"packed-store decline path no longer has source-bound handled behavior: {fragment}")
    index_dispatch = dispatch.find("emit_expression_index_fields(")
    handled_dispatch = dispatch.find("ifindex_fields_handled:", index_dispatch)
    decline_dispatch = dispatch.find("remember_expression_decline(expression,structs)", handled_dispatch)
    calls_dispatch = dispatch.find("emit_expression_calls(", handled_dispatch)
    if min(index_dispatch, handled_dispatch, decline_dispatch, calls_dispatch) < 0 or not (
            index_dispatch < handled_dispatch < decline_dispatch < calls_dispatch):
        errors.append("declined index-field expressions no longer stop before call-expression dispatch")

    if ('ValueType{kind:TypeKind.PackedEnum,bits:packed_store_root.u32()}returnif'
            'packed_store_root<structs.packed_enums.packed_names.count' not in packed_type):
        errors.append("packed-store indexing no longer types ordinal lookup results as packed-enum handles")
    if 'ValueType{kind:TypeKind.Signed,bits:32}returnifdense_key_type_name=="dense_key"andcall_arguments.count==2' not in packed_type:
        errors.append("dense_key expressions no longer type as signed i32 NodeKey handles")
    if 'ValueType{kind:TypeKind.Signed,bits:32}returnifcontainer_name=="NodeKey"' not in annotation_type:
        errors.append("NodeKey annotations no longer erase to their signed i32 handle representation")
    if ('ifcalleeisExpr.Ident(dense_key_name,dense_key_line):'
            'ifdense_key_name=="dense_key"andarguments.count==2:'
            'returnemit_expression(arguments[0],ValueType{kind:TypeKind.Signed,bits:32},local_scope,fns,structs,generics,runtime,m,ctx,builder)canGlobal{Read,Write}' not in value_call):
        errors.append("dense_key construction no longer emits its node handle as the NodeKey i32 payload")
    if "TypeKind.PackedEnum:returnLLVMInt32TypeInContext(ctx)" not in llvm_type:
        errors.append("packed-enum handles no longer use the i32 representation returned by packed-store index lookup")

    if "state.handles<-zeroed" not in initialize or "state.indices<-zeroed" not in initialize:
        errors.append("new packed stores no longer begin with aligned empty handle and index tables")
    for label, allocation in (("fixed", fixed_allocation), ("sized", sized_allocation)):
        allocation_steps = (
            'ifstate.handles.count>=PACKED_STORE_MAX_INDEX:panic("packedstoreindexlimitexceeded")',
            "global_index:u32=state.handles.count.u32()",
            "needed_rows:usize=state.handles.count+1",
            "packed_store_ensure_metadata_capacity(a,state,needed_rows)",
            "ina:",
            "state.handles.push(handle)",
            "state.indices.push(global_index)",
        )
        positions = [allocation.find(fragment) for fragment in allocation_steps]
        if any(position < 0 for position in positions) or positions != sorted(positions):
            errors.append(f"{label} packed-store allocation no longer keeps the ordinal and handle tables in lockstep")
        if allocation.count("state.handles.push(handle)") != 1 or allocation.count("state.indices.push(global_index)") != 1:
            errors.append(f"{label} packed-store allocation must append exactly one handle and its matching global index")

    # Source-level `darray.push` preserves the table-count model only if the
    # production emitter stores the element at the old count and commits exactly
    # that count plus one on its successful path.
    push_steps = (
        'count:LLVMValueRef=darray_load_size_i64(count_pointer,ctx,builder,"push.count",structs.target.target_pointer_bits)',
        'enough:LLVMValueRef=LLVMBuildICmp(builder,36,count,capacity,"push.cap.ok")',
        '_=LLVMBuildCondBr(builder,enough,store_block,grow_block)',
        'needed:LLVMValueRef=LLVMBuildAdd(builder,count,LLVMConstInt(int64_type,1,0),"push.needed")',
        'indices:mutabledarray[LLVMValueRef]=[count]',
        'LLVMBuildGEP2(builder,llvm_type_of(element_type,structs,ctx),items,indices_pointer,1,"push.slot")',
        '_=LLVMBuildStore(builder,pushed_value,slot)',
        'darray_store_size(builder,needed,count_pointer,ctx,structs.target.target_pointer_bits)',
        'returntrue',
    )
    push_positions = [push.find(fragment) for fragment in push_steps]
    if any(position < 0 for position in push_positions) or push_positions != sorted(push_positions):
        errors.append("successful darray.push lowering no longer stores at the old count then commits exactly count + 1")
    push_call_steps = (
        'ifpush_type.kind==TypeKind.DArrayandpush_method=="push"andpush_arguments.count==1:',
        'darray_address_of_expr(push_object,local_scope,fns,structs,generics,runtime,m,ctx,builder)',
        'emit_darray_push(push_slot,push_type,push_arguments[0],local_scope,fns,structs,generics,push_growth_runtime,m,ctx,builder)',
        'returnEmitStatus.Open',
        'returnEmitStatus.Declined',
    )
    push_call_start = push_call_dispatch.find(push_call_steps[0])
    push_call_branch = push_call_dispatch[push_call_start:] if push_call_start >= 0 else ""
    call_positions = [push_call_branch.find(fragment) for fragment in push_call_steps]
    if any(position < 0 for position in call_positions) or call_positions != sorted(call_positions):
        errors.append("statement-position darray.push no longer routes through the count-preserving push emitter")

    runtime_steps = (
        "defctx_packed_store_index_at(state_bits:mutablevoid&,index:usize)->u32:",
        "assertstate_bits!=null",
        "state:PackedStoreState&=state_bits.cast[PackedStoreState&]",
        "assertstate.indices.items!=null",
        "assertindex<state.indices.count",
        "indices:u32&=state.indices.items",
        "returnindices[index]",
    )
    positions = [runtime.find(fragment) for fragment in runtime_steps]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        errors.append("runtime packed-store ordinal lookup lost its null, table, or strict index bounds checks")
    return errors


def validate_proof_model() -> None:
    positive_text = POSITIVE.read_text()
    negative_text = NEGATIVE.read_text()
    direct = "is_packed_store and packed_mode != 2 and is_signed_i32 and not is_integer_literal"
    ordinal = "is_packed_store and packed_mode != 2 and is_integer_literal"
    declined = f"not ({direct}) and not ({ordinal})"
    expected_models = {
        "packed_store_index_is_direct_handle": direct,
        "packed_store_index_is_ordinal_lookup": ordinal,
        "packed_store_index_is_declined": declined,
    }
    for name, formula in expected_models.items():
        body = compact(function_section(positive_text, name))
        if f"ensureresult==({compact(formula)})" not in body or f"return{compact(formula)}" not in body:
            raise SystemExit(f"proof model {name} no longer matches its checked route formula")

    witness_returns = {
        "integer_literal_i32_uses_ordinal_lookup": "true and 0 != 2 and true",
        "integer_literal_i32_does_not_use_direct_handle": "not (true and 0 != 2 and true and not true)",
        "nonliteral_signed_i32_uses_direct_handle": "true and 0 != 2 and true and not false",
        "nonliteral_other_width_declines": "not true or 0 == 2 or (not false and not false)",
        "packed_aos_mode_declines": "not true or 2 == 2 or (not true and not true)",
        "nonpacked_receiver_declines": "not false or 0 == 2 or (not true and not true)",
    }
    for name, expression in witness_returns.items():
        body = compact(function_section(positive_text, name))
        if f"ensureresult==true" not in body or f"return{compact(expression)}" not in body:
            raise SystemExit(f"concrete route witness {name} no longer checks its intended case")

    node_key = compact(function_section(positive_text, "node_key_uses_direct_handle_route"))
    if "ensureresult==true" not in node_key or "returnpacked_store_index_is_direct_handle(true,0,false,true)" not in node_key:
        raise SystemExit("NodeKey direct-handle witness no longer instantiates the generic route theorem")

    disjoint = compact(function_section(positive_text, "no_input_can_take_both_packed_store_routes"))
    if ("returnnot((is_packed_storeandpacked_mode!=2andis_signed_i32andnotis_integer_literal)and"
            "(is_packed_storeandpacked_mode!=2andis_integer_literal))") not in disjoint:
        raise SystemExit("route-disjointness theorem no longer proves the source-derived direct and ordinal guards disjoint")
    exhaustive = compact(function_section(positive_text, "every_index_is_routed_or_declined"))
    if ("direct:bool=is_packed_storeandpacked_mode!=2andis_signed_i32andnotis_integer_literal" not in exhaustive or
            "ordinal:bool=is_packed_storeandpacked_mode!=2andis_integer_literal" not in exhaustive or
            "returndirectorordinalor(notdirectandnotordinal)" not in exhaustive):
        raise SystemExit("route-exhaustiveness theorem no longer partitions all cases into route or decline")

    negative_returns = {
        "a_literal_i32_is_a_direct_key": "true and 0 != 2 and true and not true",
        "a_nonliteral_i32_is_an_ordinal": "true and 0 != 2 and false",
        "packed_aos_mode_has_an_ordinal_route": "not (not true or 2 == 2 or (not true and not true))",
        "a_full_handle_count_can_be_cast_to_u32_without_truncation": "4294967295 <= 4294967294",
    }
    for name, expression in negative_returns.items():
        body = compact(function_section(negative_text, name))
        if "ensureresult==true" not in body or f"return{compact(expression)}" not in body:
            raise SystemExit(f"false-claim control {name} no longer contradicts its intended route")

    empty = compact(function_section(positive_text, "packed_store_empty_columns_are_aligned"))
    if "ensureresult==true" not in empty or "return0==0" not in empty:
        raise SystemExit("empty-store base case no longer establishes aligned zero table counts")
    for name, ensures, returned in (
        ("packed_store_global_index_cast_fits_u32", ("requireshandle_count>=0andhandle_count<4294967295",), "returnhandle_count<=4294967294"),
        ("packed_store_next_metadata_count_fits_u32_limit", ("requireshandle_count>=0andhandle_count<4294967295",), "returnhandle_count+1<=4294967295"),
        ("packed_store_append_preserves_index_alignment", (
            "requireshandle_count==index_count", "requiresglobal_index==handle_count",
            "requiresappend_ordinal==index_count", "requireshandle_count>=0andhandle_count<4294967295",
        ), "returnglobal_index==append_ordinalandhandle_count+1==index_count+1"),
    ):
        body = compact(function_section(positive_text, name))
        if not all(fragment in body for fragment in ensures) or "ensureresult==true" not in body or returned not in body:
            raise SystemExit(f"packed-store allocation invariant proof {name} no longer covers its source-bound transition")


index_text = INDEX_FIELDS.read_text()
dispatch_text = DISPATCH.read_text()
type_text = TYPE_PLACE.read_text()
llvm_text = LLVM_TYPES.read_text()
runtime_text = RUNTIME.read_text()
container_ops_text = CONTAINER_OPS.read_text()
codegen_calls_text = CODEGEN_CALLS.read_text()
annotation_text = ANNOTATION_INDEX.read_text()
value_call_text = VALUE_CALL.read_text()
source_errors = validate_source(index_text, dispatch_text, type_text, llvm_text, runtime_text,
                                container_ops_text, codegen_calls_text, annotation_text, value_call_text)
if source_errors:
    raise SystemExit("\n".join(source_errors))
if declarations(POSITIVE) != POSITIVE_NAMES:
    raise SystemExit("packed-store index positive proof inventory changed")
if declarations(NEGATIVE) != NEGATIVE_NAMES or \
        'include "./backend_packed_store_index.elisa"' not in NEGATIVE.read_text():
    raise SystemExit("packed-store index false-claim controls changed")
validate_proof_model()

# Check that the source gate notices the principal unsound route mutations.
mutated_key = index_text.replace("and not store_ix_is_ordinal:", "and store_ix_is_ordinal:", 1)
if mutated_key == index_text or not validate_source(mutated_key, dispatch_text, type_text, llvm_text, runtime_text, container_ops_text, codegen_calls_text, annotation_text, value_call_text):
    raise SystemExit("source gate failed to reject routing ordinal literals through the direct-key path")
mutated_bound = runtime_text.replace("assert index < state.indices.count", "assert index <= state.indices.count", 1)
if mutated_bound == runtime_text or not validate_source(index_text, dispatch_text, type_text, llvm_text, mutated_bound, container_ops_text, codegen_calls_text, annotation_text, value_call_text):
    raise SystemExit("source gate failed to reject an inclusive packed-store index bound")
mutated_dispatch = dispatch_text.replace("if index_fields_handled:", "if false:", 1)
if mutated_dispatch == dispatch_text or not validate_source(index_text, mutated_dispatch, type_text, llvm_text, runtime_text, container_ops_text, codegen_calls_text, annotation_text, value_call_text):
    raise SystemExit("source gate failed to reject a packed-store decline that falls through to call dispatch")
mutated_llvm = llvm_text.replace("return LLVMInt32TypeInContext(ctx)", "return LLVMInt64TypeInContext(ctx)", 1)
if mutated_llvm == llvm_text or not validate_source(index_text, dispatch_text, type_text, mutated_llvm, runtime_text, container_ops_text, codegen_calls_text, annotation_text, value_call_text):
    raise SystemExit("source gate failed to reject a packed-store handle representation mismatch")

mutated_push = container_ops_text.replace(
    'needed: LLVMValueRef = LLVMBuildAdd(builder, count, LLVMConstInt(int64_type, 1, 0), "push.needed")',
    'needed: LLVMValueRef = LLVMBuildAdd(builder, count, LLVMConstInt(int64_type, 2, 0), "push.needed")',
    1,
)
if mutated_push == container_ops_text or not validate_source(index_text, dispatch_text, type_text, llvm_text, runtime_text, mutated_push, codegen_calls_text, annotation_text, value_call_text):
    raise SystemExit("source gate failed to reject a darray.push count increment other than one")

mutated_push_call = codegen_calls_text.replace(
    'emit_darray_push(push_slot, push_type, push_arguments[0], local_scope, fns, structs, generics, push_growth_runtime, m, ctx, builder)',
    'emit_darray_reserve(push_slot, push_type, push_arguments[0], local_scope, fns, structs, generics, push_growth_runtime, m, ctx, builder)',
    1,
)
if mutated_push_call == codegen_calls_text or not validate_source(
        index_text, dispatch_text, type_text, llvm_text, runtime_text, container_ops_text,
        mutated_push_call, annotation_text, value_call_text):
    raise SystemExit("source gate failed to reject bypassing the count-preserving darray.push emitter")

mutated_node_key_type = annotation_text.replace(
    'return ValueType{kind: TypeKind.Signed, bits: 32} if container_name == "NodeKey"',
    'ValueType{kind: TypeKind.Signed, bits: 64} return if container_name == "NodeKey"',
    1,
)
if mutated_node_key_type == annotation_text or not validate_source(
        index_text, dispatch_text, type_text, llvm_text, runtime_text, container_ops_text,
        codegen_calls_text, mutated_node_key_type, value_call_text):
    raise SystemExit("source gate failed to reject changing the erased NodeKey payload width")

mutated_dense_key = value_call_text.replace(
    'emit_expression(arguments[0], ValueType{kind: TypeKind.Signed, bits: 32}, local_scope',
    'emit_expression(arguments[0], ValueType{kind: TypeKind.Signed, bits: 64}, local_scope',
    1,
)
if mutated_dense_key == value_call_text or not validate_source(
        index_text, dispatch_text, type_text, llvm_text, runtime_text, container_ops_text,
        codegen_calls_text, annotation_text, mutated_dense_key):
    raise SystemExit("source gate failed to reject emitting dense_key with a non-i32 handle payload")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("packed-store index proofs require a strict proof build")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV", stage1_product,
    stage1_provenance, Path(__file__), HERE / "proof_product_gate.py", POSITIVE, NEGATIVE,
    INDEX_FIELDS, DISPATCH, TYPE_PLACE, ANNOTATION_INDEX, LLVM_TYPES, VALUE_CALL,
    RUNTIME, CONTAINER_OPS, CODEGEN_CALLS,
    *source_include_closure([POSITIVE, NEGATIVE]),
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=120)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "packed-store index proof report changed across repeated runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert verified == POSITIVE_NAMES

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
findings = {row["name"]: row["kind"] for row in negative["findings"]}
assert findings == {name: "ensure-unproven" for name in NEGATIVE_NAMES}
assert negative["summary"]["unproven"] == len(NEGATIVE_NAMES)
assert negative == run(NEGATIVE)[1], "packed-store false-claim report changed across repeated runs"

assert require_current_product(BIN, PROVER) == manifest, "proof product changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "packed-store NodeKey/ordinal lowering and runtime table bounds",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(NEGATIVE_NAMES),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
