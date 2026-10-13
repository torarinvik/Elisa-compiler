"""Bind pointer-walk dispatch and countdown proofs to DArray for-loop lowering."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


argument_parser = argparse.ArgumentParser()
argument_parser.add_argument("--source-only", action="store_true",
                             help="check production and proof bindings without running Elisa-Proof")
ARGS = argument_parser.parse_args()
ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=not ARGS.source_only)
LOWERING = ROOT / "src/backend/codegen_stmt_for_shapes.elisa"
TYPE_SIZES = ROOT / "src/backend/codegen_type_sizes.elisa"
ABI_FACTS = ROOT / "src/backend/codegen_abi_facts.elisa"
BENCHMARK = ROOT / "test/bench/codegen_perf/darray_sum.elisa"
POSITIVE = HERE / "backend_darray_pointer_walk.elisa"
NEGATIVE = HERE / "backend_darray_pointer_walk_rejected.elisa"

POSITIVE_SHAPES = {
    "named_darray_binding_source_accepts_local_or_borrowed_darray": """def named_darray_binding_source_accepts_local_or_borrowed_darray(is_named_ident: bool, is_local_darray: bool, is_borrowed_ref_formal: bool, borrowed_target_is_darray: bool) -> bool:
    ensure result == (is_named_ident and (is_local_darray or (is_borrowed_ref_formal and borrowed_target_is_darray)))
    return is_named_ident and (is_local_darray or (is_borrowed_ref_formal and borrowed_target_is_darray))
""",
    "pointer_walk_eligible": """def pointer_walk_eligible(in_darray_branch: bool, named_darray_binding_source: bool, safe_scalar_fold_body: bool, mutable_binding: bool, reversed_iteration: bool, drains_source: bool, fixed_array_source: bool, scalar_element: bool) -> bool:
    ensure result == (in_darray_branch and named_darray_binding_source and safe_scalar_fold_body and not mutable_binding and not reversed_iteration and not drains_source and not fixed_array_source and scalar_element)
    return in_darray_branch and named_darray_binding_source and safe_scalar_fold_body and not mutable_binding and not reversed_iteration and not drains_source and not fixed_array_source and scalar_element
""",
    "dispatch_policy_matches_exact_pointer_walk_condition": """def dispatch_policy_matches_exact_pointer_walk_condition(in_darray_branch: bool, named_darray_binding_source: bool, safe_scalar_fold_body: bool, mutable_binding: bool, reversed_iteration: bool, drains_source: bool, fixed_array_source: bool, scalar_element: bool) -> bool:
    ensure result == true
    return pointer_walk_eligible(in_darray_branch, named_darray_binding_source, safe_scalar_fold_body, mutable_binding, reversed_iteration, drains_source, fixed_array_source, scalar_element) == (in_darray_branch and named_darray_binding_source and safe_scalar_fold_body and not mutable_binding and not reversed_iteration and not drains_source and not fixed_array_source and scalar_element)
""",
    "pointer_walk_requires_a_named_forward_read_only_scalar_darray": """def pointer_walk_requires_a_named_forward_read_only_scalar_darray(in_darray_branch: bool, named_darray_binding_source: bool, safe_scalar_fold_body: bool, mutable_binding: bool, reversed_iteration: bool, drains_source: bool, fixed_array_source: bool, scalar_element: bool) -> bool:
    ensure result == true
    selected: bool = pointer_walk_eligible(in_darray_branch, named_darray_binding_source, safe_scalar_fold_body, mutable_binding, reversed_iteration, drains_source, fixed_array_source, scalar_element)
    return not selected or (in_darray_branch and named_darray_binding_source and safe_scalar_fold_body and not mutable_binding and not reversed_iteration and not drains_source and not fixed_array_source and scalar_element)
""",
    "fixed_array_sources_stay_on_indexed_path": """def fixed_array_sources_stay_on_indexed_path() -> bool:
    ensure result == true
    return not pointer_walk_eligible(true, true, true, false, false, false, true, true)
""",
    "mutable_bindings_stay_on_indexed_path": """def mutable_bindings_stay_on_indexed_path() -> bool:
    ensure result == true
    return not pointer_walk_eligible(true, true, true, true, false, false, false, true)
""",
    "reversed_sources_stay_on_indexed_path": """def reversed_sources_stay_on_indexed_path() -> bool:
    ensure result == true
    return not pointer_walk_eligible(true, true, true, false, true, false, false, true)
""",
    "draining_sources_stay_on_indexed_path": """def draining_sources_stay_on_indexed_path() -> bool:
    ensure result == true
    return not pointer_walk_eligible(true, true, true, false, false, true, false, true)
""",
    "aggregate_elements_stay_on_indexed_path": """def aggregate_elements_stay_on_indexed_path() -> bool:
    ensure result == true
    return not pointer_walk_eligible(true, true, true, false, false, false, false, false)
""",
    "temporary_darray_sources_stay_on_indexed_path": """def temporary_darray_sources_stay_on_indexed_path() -> bool:
    ensure result == true
    return not pointer_walk_eligible(true, false, true, false, false, false, false, true)
""",
    "darray_sum_scalar_fold_is_admitted": """def darray_sum_scalar_fold_is_admitted() -> bool:
    ensure result == true
    return pointer_walk_eligible(true, true, true, false, false, false, false, true)
""",
    "borrowed_darray_ref_formal_is_a_named_binding_source": """def borrowed_darray_ref_formal_is_a_named_binding_source() -> bool:
    ensure result == true
    named_source: bool = named_darray_binding_source_accepts_local_or_borrowed_darray(true, false, true, true)
    return pointer_walk_eligible(true, named_source, true, false, false, false, false, true)
""",
    "empty_snapshot_skips_the_pointer_walk_body": """def empty_snapshot_skips_the_pointer_walk_body() -> bool:
    ensure result == true
    remaining: u64 = 0
    return not (remaining != 0)
""",
    "initial_cursor_and_remaining_represent_the_snapshot_count": """def initial_cursor_and_remaining_represent_the_snapshot_count(count: u64) -> bool:
    ensure result == true
    cursor_steps: u64 = 0
    remaining: u64 = count
    return cursor_steps + remaining == count
""",
    "one_cursor_step_preserves_the_snapshot_count": """def one_cursor_step_preserves_the_snapshot_count(count: u64, cursor_steps: u64) -> bool:
    requires cursor_steps < count
    ensure result == true
    remaining: u64 = count - cursor_steps
    next_cursor_steps: u64 = cursor_steps + 1
    next_remaining: u64 = remaining - 1
    return next_cursor_steps + next_remaining == count
""",
    "cursor_countdown_reaches_the_snapshot_end": """def cursor_countdown_reaches_the_snapshot_end(count: u64, cursor_steps: u64, remaining: u64) -> bool:
    requires cursor_steps <= count and remaining == count - cursor_steps
    decreases remaining
    ensure result == true
    if remaining == 0:
        return cursor_steps == count
    next_cursor_steps: u64 = cursor_steps + 1
    next_remaining: u64 = remaining - 1
    return cursor_countdown_reaches_the_snapshot_end(count, next_cursor_steps, next_remaining)
""",
}
NEGATIVE_SHAPES = {
    "borrowed_ref_to_non_darray_is_eligible": """def borrowed_ref_to_non_darray_is_eligible() -> bool:
    ensure result == true
    return named_darray_binding_source_accepts_local_or_borrowed_darray(true, false, true, false)
""",
    "temporary_ref_source_is_eligible": """def temporary_ref_source_is_eligible() -> bool:
    ensure result == true
    return named_darray_binding_source_accepts_local_or_borrowed_darray(false, false, true, true)
""",
    "fixed_array_source_can_use_pointer_walk": """def fixed_array_source_can_use_pointer_walk() -> bool:
    ensure result == true
    return pointer_walk_eligible(true, true, true, false, false, false, true, true)
""",
    "mutable_binding_can_use_pointer_walk": """def mutable_binding_can_use_pointer_walk() -> bool:
    ensure result == true
    return pointer_walk_eligible(true, true, true, true, false, false, false, true)
""",
    "reversed_iteration_can_use_pointer_walk": """def reversed_iteration_can_use_pointer_walk() -> bool:
    ensure result == true
    return pointer_walk_eligible(true, true, true, false, true, false, false, true)
""",
    "draining_source_can_use_pointer_walk": """def draining_source_can_use_pointer_walk() -> bool:
    ensure result == true
    return pointer_walk_eligible(true, true, true, false, false, true, false, true)
""",
    "aggregate_element_can_use_pointer_walk": """def aggregate_element_can_use_pointer_walk() -> bool:
    ensure result == true
    return pointer_walk_eligible(true, true, true, false, false, false, false, false)
""",
    "temporary_source_can_use_pointer_walk": """def temporary_source_can_use_pointer_walk() -> bool:
    ensure result == true
    return pointer_walk_eligible(true, false, true, false, false, false, false, true)
""",
    "helper_call_body_can_use_pointer_walk": """def helper_call_body_can_use_pointer_walk() -> bool:
    ensure result == true
    return pointer_walk_eligible(true, true, false, false, false, false, false, true)
""",
    "direct_source_write_body_can_use_pointer_walk": """def direct_source_write_body_can_use_pointer_walk() -> bool:
    ensure result == true
    return pointer_walk_eligible(true, true, false, false, false, false, false, true)
""",
    "multi_statement_body_can_use_pointer_walk": """def multi_statement_body_can_use_pointer_walk() -> bool:
    ensure result == true
    return pointer_walk_eligible(true, true, false, false, false, false, false, true)
""",
}


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


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


for path, shapes in ((POSITIVE, POSITIVE_SHAPES), (NEGATIVE, NEGATIVE_SHAPES)):
    if declarations(path) != set(shapes):
        raise SystemExit(f"pointer-walk theorem inventory changed in {path.name}")
    source = path.read_text()
    for name, expected in shapes.items():
        if compact(function_section(source, name)) != compact(expected):
            raise SystemExit(f"pointer-walk theorem changed its exact claim: {name}")
if 'include "./backend_darray_pointer_walk.elisa"' not in NEGATIVE.read_text():
    raise SystemExit("pointer-walk false controls no longer inherit the positive claims")

lowering = LOWERING.read_text()
lowering_compact = compact(lowering)
lowering_body = compact(function_section(lowering, "emit_statement_for_iterable_shapes"))
guard = "pointer_walk:bool=named_darray_sourceandfor_bind==\"\"andnotfor_reversedandnotdrainsandmutable_source_array.kind!=TypeKind.Arrayandloop_scratch_scalar_type(element_type)"
if guard not in lowering_body:
    raise SystemExit("production pointer-walk selection no longer matches its proved dispatch policy")
outer_guard = "ifcontainer_type.kind==TypeKind.DArray:"
if outer_guard not in lowering_body or lowering_body.find(outer_guard) > lowering_body.find(guard):
    raise SystemExit("pointer-walk selection must remain inside the DArray lowering branch")
container_type_binding = "container_type: mutable ValueType = iterable_darray_type(for_source, local_scope, fns, structs, generics)"
if compact(container_type_binding) not in lowering_body or lowering_body.find(compact(container_type_binding)) > lowering_body.find(guard):
    raise SystemExit("pointer-walk dispatch must use the iterable type resolved from the unwrapped source")
type_sizes = compact(TYPE_SIZES.read_text())
if "defdarray_type_behind(local_scope:mutableScope&,name:sview,structs:mutableStructTable&)" not in type_sizes:
    raise SystemExit("named DArray source typing no longer resolves through darray_type_behind")
for fragment in (
    "unmodeled_type()returnifbound.kind!=TypeKind.Ref",
    "target:ValueType=ref_target_of(bound,structs)",
    "targetreturniftarget.kind==TypeKind.DArray",
):
    if fragment not in type_sizes:
        raise SystemExit("borrowed DArray reference no longer resolves to its DArray target")
abi_facts = compact(ABI_FACTS.read_text())
if "defdarray_address_of(local_scope:mutableScope&,name:sview,structs:mutableStructTable&,ctx:LLVMContextRef,builder:LLVMBuilderRef)->LLVMValueRef?" not in abi_facts:
    raise SystemExit("named DArray source address no longer uses darray_address_of")
for fragment in (
    "bound.kind!=TypeKind.Ref",
    "ref_target_of(bound,structs).kind!=TypeKind.DArray",
    'LLVMBuildLoad2(builder,LLVMPointerTypeInContext(ctx,0),bound_slot,"darray.ref")',
):
    if fragment not in abi_facts:
        raise SystemExit("borrowed DArray formal no longer resolves its header pointer")
for fragment in (
    "matchfor_source:Expr.Ident(source_name,_):iffor_variables.count==1.usize()andlookup_slot(local_scope,source_name)islocal_source_slot:named_darray_source<-container_type.kind==TypeKind.DArrayanddarray_pointer_walk_body_safe(for_body,source_name,for_variable,element_type,local_scope)",
    "defdarray_pointer_walk_scalar_expr(",
    "defdarray_pointer_walk_body_safe(",
    "returnfalseifbody.count!=1",
    "Expr.IntLit(_,_)|Expr.FloatLit(_,_)|Expr.BoolLit(_,_):returntrue",
    "Expr.Ident(name,_):returnfalseifname==source_nameifname==element_name:returnloop_scratch_scalar_type(element_type)returnloop_scratch_scalar_type(lookup_type(local_scope,name))",
    "Expr.Paren(inner,_):returndarray_pointer_walk_scalar_expr(inner,source_name,element_name,element_type,local_scope)",
    "Expr.Unary(operator,operand,_):returnfalseifoperator!=TokenKind.Minusandoperator!=TokenKind.Plusandoperator!=TokenKind.Notandoperator!=TokenKind.Tildereturndarray_pointer_walk_scalar_expr(operand,source_name,element_name,element_type,local_scope)",
    "returnfalseifname==source_name",
    "returnloop_scratch_scalar_type(element_type)",
    "loop_scratch_scalar_type(lookup_type(local_scope,name))",
    "returnfalseifoperator!=TokenKind.Minusandoperator!=TokenKind.Plusandoperator!=TokenKind.Notandoperator!=TokenKind.Tilde",
    "returndarray_pointer_walk_scalar_expr(left,source_name,element_name,element_type,local_scope)anddarray_pointer_walk_scalar_expr(right,source_name,element_name,element_type,local_scope)",
    "_:returnfalse",
    "ifbody[0]isStmt.Assign(target,operator,value,_):returnfalseifoperator!=TokenKind.Assignandoperator!=TokenKind.LArrow",
    "iftargetisExpr.Ident(target_name,_):",
    "returnfalseif:target_name==source_nameortarget_name==element_namenot(lookup_slot(local_scope,target_name)istarget_slot)",
    "returnloop_scratch_scalar_type(lookup_type(local_scope,target_name))anddarray_pointer_walk_scalar_expr(value,source_name,element_name,element_type,local_scope)",
    "mutable_source_array.kind!=TypeKind.Array",
    "loop_scratch_scalar_type(element_type)",
    "cursor_slot<-build_entry_alloca(builder,pointer_type,\"for.darray.cursor\")",
    "remaining_slot<-build_entry_alloca(builder,int64_type,\"for.darray.remaining\")",
    "LLVMBuildStore(builder,items_value,cursor_slot)",
    "LLVMBuildStore(builder,count_value,remaining_slot)",
    "LLVMBuildICmp(builder,33,remaining_cur,LLVMConstInt(int64_type,0,0),\"for.darray.remaining.nonzero\")",
    "element_pointer<-LLVMBuildLoad2(builder,pointer_type,cursor_slot,\"for.darray.elem.ptr\")",
    "LLVMBuildGEP2(builder,llvm_type_of(element_type,structs,ctx),cursor,cursor_indices_pointer,1,\"for.darray.cursor.next\")",
    "remaining_next:LLVMValueRef=LLVMBuildSub(builder,remaining_step,LLVMConstInt(int64_type,1,0),\"for.darray.remaining.next\")",
    "LLVMBuildStore(builder,cursor_next,cursor_slot)",
    "LLVMBuildStore(builder,remaining_next,remaining_slot)",
    "loops.continues.push(step_block)",
):
    if compact(fragment) not in lowering_compact:
        raise SystemExit(f"production pointer-walk transition changed or lost a required binding: {fragment}")
pointer_blocks = (
    """if pointer_walk:
    cursor_slot <- build_entry_alloca(builder, pointer_type, "for.darray.cursor")
    remaining_slot <- build_entry_alloca(builder, int64_type, "for.darray.remaining")
    _ = LLVMBuildStore(builder, items_value, cursor_slot)
    _ = LLVMBuildStore(builder, count_value, remaining_slot)
else:
    index_slot <- build_entry_alloca(builder, int64_type, "for.darray.i")""",
    """if pointer_walk:
    remaining_cur: LLVMValueRef = LLVMBuildLoad2(builder, int64_type, remaining_slot, "for.darray.remaining.cur")
    keep_going <- LLVMBuildICmp(builder, 33, remaining_cur, LLVMConstInt(int64_type, 0, 0), "for.darray.remaining.nonzero")
else:
    current <- LLVMBuildLoad2(builder, int64_type, index_slot, "for.darray.cur")""",
    """if pointer_walk:
    element_pointer <- LLVMBuildLoad2(builder, pointer_type, cursor_slot, "for.darray.elem.ptr")
else:
    effective_index: mutable LLVMValueRef = current""",
    """if pointer_walk:
    cursor: LLVMValueRef = LLVMBuildLoad2(builder, pointer_type, cursor_slot, "for.darray.cursor.cur")
    cursor_indices: mutable darray[LLVMValueRef] = [LLVMConstInt(int64_type, 1, 0)]
    cursor_indices_pointer: void& = (&cursor_indices[0]).cast[void&] can Unsafe.PointerCast
    cursor_next: LLVMValueRef = LLVMBuildGEP2(builder, llvm_type_of(element_type, structs, ctx), cursor, cursor_indices_pointer, 1, "for.darray.cursor.next")
    _ = LLVMBuildStore(builder, cursor_next, cursor_slot)
    remaining_step: LLVMValueRef = LLVMBuildLoad2(builder, int64_type, remaining_slot, "for.darray.remaining.step")
    remaining_next: LLVMValueRef = LLVMBuildSub(builder, remaining_step, LLVMConstInt(int64_type, 1, 0), "for.darray.remaining.next")
    _ = LLVMBuildStore(builder, remaining_next, remaining_slot)
else:
    next_index: LLVMValueRef = LLVMBuildAdd(builder, LLVMBuildLoad2(builder, int64_type, index_slot, "for.darray.next.cur"), LLVMConstInt(int64_type, 1, 0), "for.darray.next")""",
)
if any(compact(block) not in lowering_compact for block in pointer_blocks):
    raise SystemExit("pointer-walk initialization, branch, element access, or step moved outside its guarded arm")

benchmark = compact(BENCHMARK.read_text())
if "total<-forxinxs|total|->total:" not in benchmark or "total<-total-(x>>3)" not in benchmark:
    raise SystemExit("the admitted DArray scalar-fold theorem is no longer represented by darray_sum")

source_closure = source_include_closure([POSITIVE, NEGATIVE])
if ARGS.source_only:
    print(json.dumps({
        "source_bound": True,
        "positive_theorems": len(POSITIVE_SHAPES),
        "false_controls": len(NEGATIVE_SHAPES),
        "proof_closure_files": len(source_closure),
    }, sort_keys=True))
    raise SystemExit(0)

product = require_current_product(BIN, PROVER)
if product.get("compile_mode") != "strict":
    raise SystemExit("pointer-walk proof requires a strict proof build")
stage1_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
manifest = BIN.with_name(BIN.name + ".manifest.json")
inputs = list(dict.fromkeys([
    BIN, manifest, manifest.with_name(manifest.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", LOWERING, TYPE_SIZES, ABI_FACTS, POSITIVE, NEGATIVE,
    *source_closure, BENCHMARK,
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def replay(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=60)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"]
    assert report["trust"]["kernel_replayed_certificates"] == report["replay"]["replayed"]
    return process.returncode, report


positive_code, positive = replay(POSITIVE)
assert positive_code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == set(POSITIVE_SHAPES)
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
negative_code, negative = replay(NEGATIVE)
assert negative_code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert {row["name"] for row in negative["findings"]} == set(NEGATIVE_SHAPES)
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
print(json.dumps({
    "admitted": True,
    "scope": "DArray pointer-walk guard and snapshot countdown invariants",
    "positive_theorems": sorted(POSITIVE_SHAPES),
    "false_controls_rejected": sorted(NEGATIVE_SHAPES),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
}, sort_keys=True))
