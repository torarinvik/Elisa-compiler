"""Bind DArray push capacity arithmetic to the stage1 store and growth paths."""
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
CONTAINER = ROOT / "src/backend/codegen_container_ops.elisa"
CONTAINER_GROWTH = ROOT / "src/backend/codegen_container_ops_darray_growth.elisa"
PRERESERVE = ROOT / "src/backend/codegen_loop_prereserve.elisa"
SIZE_TYPES = ROOT / "src/backend/codegen_interned_types.elisa"
LLVM_C = ROOT / "src/backend/llvm_c.elisa"
POSITIVE = HERE / "backend_darray_push_bounds.elisa"
NEGATIVE = HERE / "backend_darray_push_bounds_rejected.elisa"
POSITIVE_NAMES = {"guarded_count_increment_fits_capacity", "full_capacity_guard_rejects_the_store_path", "guarded_count_increment_fits_target_limit", "push_growth_capacity_covers_needed", "push_growth_overflow_fallback_selects_needed", "empty_push_growth_keeps_seed_when_it_fits", "empty_push_growth_uses_needed_above_seed", "append_growth_step_increases_capacity", "append_growth_overflow_step_meets_bound", "normal_growth_selects_double_when_it_covers_needed", "normal_growth_selects_needed_when_double_is_too_small"}
NEGATIVE_NAMES = {"false_full_capacity_has_a_spare_slot", "false_guarded_increment_exceeds_target_capacity", "false_guarded_increment_exceeds_target_limit", "false_push_growth_capacity_may_fall_short", "false_push_growth_overflow_keeps_wrapped_double", "false_empty_push_growth_seed_is_not_eight", "false_normal_growth_selects_needed_when_double_covers", "false_normal_growth_selects_double_when_double_is_small"}
PROOF_HASHES = {
    "guarded_count_increment_fits_capacity": "e9a40dae00344a7bc9ad3a15c74184bd959560ae617bd72e6049d29e0d2d0dd2",
    "full_capacity_guard_rejects_the_store_path": "7df7845e15540ae20add2dff2421f5ce987d74ef0cbcb13590db4546aa4fed08",
    "guarded_count_increment_fits_target_limit": "a74105f83c28dd35f47abeaa5b59584864ae0b249dffae58588aa3288443b5f6",
    "false_full_capacity_has_a_spare_slot": "bc2b7f499fb6640853e768345ae0c7e179bd304a58fbd2ada1033d8c8080de66",
    "false_guarded_increment_exceeds_target_capacity": "e07b9421c6f3f9edc504893442921a7a1bfa6468cd1788457de7c16f3a2de114",
    "false_guarded_increment_exceeds_target_limit": "4197d3b5b1fff30d5dfe8084f81659ea857b6e7b2b6ea826bb0cd8e6bfdc2fc3",
    "push_growth_capacity_covers_needed": "2216c4cec7ab2ad27892474e60371777b15e4e548996d9f9266a64a72b60ab0e",
    "false_push_growth_capacity_may_fall_short": "bb70caee9dd58586ed7cffe67dbbd456d0be0896f655e7f682863f057794ba9f",
    "push_growth_overflow_fallback_selects_needed": "bd26da2b2a4a0a24f23dcc927c9ba8e17744f9e04c5cd58a41ebe8e89a0cb457",
    "false_push_growth_overflow_keeps_wrapped_double": "aca0b5605a31db1f742ab30ec5b3d81fe14a1c3fc65cfd5304e87c28d4dd244f",
    "empty_push_growth_keeps_seed_when_it_fits": "1cb199e3ef23359940d21bbf62c0b9e5fd6ef9d19f930268ee35be5fa512d4fa",
    "empty_push_growth_uses_needed_above_seed": "3ceacf01a12e39ff1d12a3bfb0f742d3ed8fba13afa76b912bdcc3c96b0887b6",
    "append_growth_step_increases_capacity": "8c034f07afee40b41a3f955e73622f6110f2ebc55a9c7e6ede6b68969a0c8102",
    "append_growth_overflow_step_meets_bound": "6c549cf093726e100fdfe2c60422190aefac60b1367482bc0d14975eac738786",
    "false_empty_push_growth_seed_is_not_eight": "739a89856ccdecf4d06711619a0715c648061f14e1eca1c991332d4219b3ecbf",
    "normal_growth_selects_double_when_it_covers_needed": "299f6717a53cbb0285af3f4b5dacb1f29cc88ad01b3d1b954d84e53943e251ef",
    "normal_growth_selects_needed_when_double_is_too_small": "57a958d53c303fc1423477c5eb8eea16aa82c407b9391eaaf840d84d05a63cf1",
    "false_normal_growth_selects_needed_when_double_covers": "98c25c38ae95c557d1262f5e15431ccc6eb84ad42b741b95b07c34f818f2c5bd",
    "false_normal_growth_selects_double_when_double_is_small": "978913ff98c25b0bec8ed67bddee15a1705478e92faffec7efef1e46ce3db12d",
}


def compact(text: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in text.splitlines())


def section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected one declaration named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


def ordered(source: str, name: str, steps: tuple[str, ...]) -> None:
    body = compact(section(source, name))
    cursor = 0
    for step in steps:
        needle = compact(step)
        position = body.find(needle, cursor)
        if position < 0:
            raise SystemExit(f"{name} no longer follows the checked push transition: {step}")
        cursor = position + len(needle)


container = CONTAINER.read_text() + CONTAINER_GROWTH.read_text()
prereserve = PRERESERVE.read_text()
size_types = SIZE_TYPES.read_text()
llvm_c = compact(LLVM_C.read_text())
maximum = re.search(r"(?m)^\s*const DARRAY_U32_MAX: u64 = (\d+)\s*$", container)
if maximum is None or int(maximum.group(1)) != 4294967295:
    raise SystemExit("push capacity model lost the target usize32 maximum")
if "ULT:i32=36" not in llvm_c:
    raise SystemExit("DArray push capacity comparison no longer uses LLVM unsigned-less-than")
ordered(container, "emit_darray_push", (
    "if fast_cursor.array_slot == array_slot and fast_cursor.direct_index_bound:",
    "direct_range_slot <- fast_cursor.range_counter_slot",
    "direct_range_base <- fast_cursor.base_count",
    "direct_range_bits <- fast_cursor.range_counter_bits",
    "direct_range_signed <- fast_cursor.range_counter_signed",
    "if direct_range_slot is direct_counter_slot and direct_range_base is initial_count:",
    "range_counter_type: LLVMTypeRef = LLVMIntTypeInContext(ctx, direct_range_bits)",
    'range_index_raw: LLVMValueRef = LLVMBuildLoad2(builder, range_counter_type, direct_counter_slot, "push.range.index")',
    "range_index_wide: mutable LLVMValueRef = range_index_raw",
    "if direct_range_bits < 64:",
    'range_index_wide <- LLVMBuildSExt(builder, range_index_raw, int64_type, "push.range.index.wide") if direct_range_signed else LLVMBuildZExt(builder, range_index_raw, int64_type, "push.range.index.wide")',
    "elif direct_range_bits > 64:",
    'range_index_wide <- LLVMBuildTrunc(builder, range_index_raw, int64_type, "push.range.index.narrow")',
    "count <- range_index_wide",
    "elif cursor_slot is push_cursor_slot:",
    'count <- LLVMBuildLoad2(builder, int64_type, push_cursor_slot, "push.cursor")',
    "if not fast_capacity_proven:",
    'capacity: LLVMValueRef = darray_load_size_i64(capacity_pointer, ctx, builder, "push.cap", structs.target.target_pointer_bits)',
    'enough: LLVMValueRef = LLVMBuildICmp(builder, 36, count, capacity, "push.cap.ok")',
    "_ = LLVMBuildCondBr(builder, enough, store_block, grow_block)",
    "if emit_checked_reserve_binary(count, LLVMConstInt(int64_type, 1, 0), false, m, ctx, builder, structs.target.target_pointer_bits) is growth_needed:",
    "LLVMPositionBuilderAtEnd(builder, store_block)",
    "direct_range_indexing: bool = direct_range_slot is direct_counter_slot and direct_range_base is initial_count",
    "needed: mutable LLVMValueRef = LLVMConstInt(int64_type, 0, 0)",
    'needed <- LLVMBuildAdd(builder, count, LLVMConstInt(int64_type, 1, 0), "push.needed") if not direct_range_indexing',
    "indices: mutable darray[LLVMValueRef] = [count]",
    'slot: LLVMValueRef = LLVMBuildGEP2(builder, llvm_type_of(element_type, structs, ctx), items, indices_pointer, 1, "push.slot")',
    "_ = LLVMBuildStore(builder, pushed_value, slot)",
    "if direct_range_indexing:",
    "pass",
    "elif cursor_slot is updated_cursor_slot:",
    "_ = LLVMBuildStore(builder, needed, updated_cursor_slot)",
    "else:",
    "darray_store_size(builder, needed, count_pointer, ctx, structs.target.target_pointer_bits)",
))
ordered(container, "emit_darray_grow_body", (
    "if append_policy:",
    "if emit_overflow_binary(current, LLVMConstInt(int64_type, 2, 0), true, m, ctx, builder, structs.target.target_pointer_bits) is step_doubled:",
    'step_safe: LLVMValueRef = LLVMBuildSelect(builder, step_doubled.overflow, needed, step_doubled.value, "grow.cap.double.safe")',
    'step_empty: LLVMValueRef = LLVMBuildICmp(builder, 32, current, LLVMConstInt(int64_type, 0, 0), "grow.cap.zero")',
    'step_next: LLVMValueRef = LLVMBuildSelect(builder, step_empty, LLVMConstInt(int64_type, 8, 0), step_safe, "grow.cap.base")',
    'LLVMBuildCondBr(builder, LLVMBuildICmp(builder, 36, step_next, needed, "grow.cap.short"), step_block, sized_block)',
))
ordered(container, "emit_darray_grow_body", (
    "if emit_overflow_binary(capacity, LLVMConstInt(int64_type, 2, 0), true, m, ctx, builder, structs.target.target_pointer_bits) is doubled_result:",
    'doubled: LLVMValueRef = LLVMBuildSelect(builder, doubled_result.overflow, needed, doubled_result.value, "push.cap.double.safe")',
    'is_empty: LLVMValueRef = LLVMBuildICmp(builder, 32, capacity, LLVMConstInt(int64_type, 0, 0), "push.cap.zero")',
    'base: LLVMValueRef = LLVMBuildSelect(builder, is_empty, LLVMConstInt(int64_type, 8, 0), doubled, "push.cap.base")',
    'too_small: LLVMValueRef = LLVMBuildICmp(builder, 36, base, needed, "push.cap.lt")',
    'new_capacity <- LLVMBuildSelect(builder, too_small, needed, base, "push.cap.new")',
))
ordered(prereserve, "emit_loop_prereserve", (
    "if bound is Expr.IntLit(limit, _) and limit > 0 and limit.u64() <= trip_cap:",
    "fast_push_slots.push(slot)",
))
size_load = compact(section(size_types, "darray_load_size_i64"))
if ('loaded:LLVMValueRef=LLVMBuildLoad2(builder,darray_size_type(ctx,target_bits),pointer,name)' not in size_load or
        'returndarray_size_value_i64(loaded,ctx,builder,"darray.size.i64")' not in size_load):
    raise SystemExit("push capacity must be loaded as target usize and zero-extended to i64")
ordered(container, "emit_checked_reserve_binary", (
    "if emit_overflow_binary(left, right, multiply, m, ctx, builder, target_bits) is result:",
    "_ = LLVMBuildCondBr(builder, result.overflow, trap_block, continue_block)",
    "emit_trap_unreachable(m, ctx, builder)",
    "return result.value",
))

if declarations(POSITIVE) != POSITIVE_NAMES or declarations(NEGATIVE) != NEGATIVE_NAMES:
    raise SystemExit("DArray push proof declaration inventory changed")
if not NEGATIVE.read_text().startswith('include "./backend_darray_push_bounds.elisa"'):
    raise SystemExit("push false claims must include the positive capacity model")
for name, expected in PROOF_HASHES.items():
    owner = POSITIVE if name in POSITIVE_NAMES else NEGATIVE
    actual = hashlib.sha256(compact(section(owner.read_text(), name)).encode()).hexdigest()
    if actual != expected:
        raise SystemExit(f"DArray push theorem {name} changed since source binding")

if args.source_only:
    print(json.dumps({"source_bound": True, "positive": len(POSITIVE_NAMES), "false_controls": len(NEGATIVE_NAMES),
                      "fast_fill_arithmetic": "eligibility-bound-only"}))
    raise SystemExit(0)

product = require_current_product(BIN, PROVER)
if product.get("compile_mode") != "strict":
    raise SystemExit("DArray push bounds require a strict Elisa-Proof build")
inputs = list(dict.fromkeys([BIN, BIN.with_name(BIN.name + ".manifest.json"),
    BIN.with_name(BIN.name + ".manifest.json.sha256"), PROVER / "ELISA_COMPILER_REV",
    Path(__file__), HERE / "proof_product_gate.py", CONTAINER, CONTAINER_GROWTH, PRERESERVE, SIZE_TYPES, LLVM_C, POSITIVE,
    NEGATIVE, *source_include_closure([POSITIVE, NEGATIVE])]))
before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True, text=True, timeout=60)
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
                  "false_claims_rejected": sorted(NEGATIVE_NAMES), "source_bound": True,
                  "fast_fill_arithmetic": "eligibility-bound-only"}))
