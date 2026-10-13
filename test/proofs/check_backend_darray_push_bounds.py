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
PRERESERVE = ROOT / "src/backend/codegen_loop_prereserve.elisa"
SIZE_TYPES = ROOT / "src/backend/codegen_interned_types.elisa"
LLVM_C = ROOT / "src/backend/llvm_c.elisa"
POSITIVE = HERE / "backend_darray_push_bounds.elisa"
NEGATIVE = HERE / "backend_darray_push_bounds_rejected.elisa"
POSITIVE_NAMES = {"guarded_count_increment_fits_capacity", "full_capacity_guard_rejects_the_store_path"}
NEGATIVE_NAMES = {"false_full_capacity_has_a_spare_slot", "false_guarded_increment_exceeds_target_capacity"}
PROOF_HASHES = {
    "guarded_count_increment_fits_capacity": "e9a40dae00344a7bc9ad3a15c74184bd959560ae617bd72e6049d29e0d2d0dd2",
    "full_capacity_guard_rejects_the_store_path": "7df7845e15540ae20add2dff2421f5ce987d74ef0cbcb13590db4546aa4fed08",
    "false_full_capacity_has_a_spare_slot": "bc2b7f499fb6640853e768345ae0c7e179bd304a58fbd2ada1033d8c8080de66",
    "false_guarded_increment_exceeds_target_capacity": "e07b9421c6f3f9edc504893442921a7a1bfa6468cd1788457de7c16f3a2de114",
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


container = CONTAINER.read_text()
prereserve = PRERESERVE.read_text()
size_types = SIZE_TYPES.read_text()
llvm_c = compact(LLVM_C.read_text())
maximum = re.search(r"(?m)^\s*const DARRAY_U32_MAX: u64 = (\d+)\s*$", container)
if maximum is None or int(maximum.group(1)) != 4294967295:
    raise SystemExit("push capacity model lost the target usize32 maximum")
if "ULT:i32=36" not in llvm_c:
    raise SystemExit("DArray push capacity comparison no longer uses LLVM unsigned-less-than")
ordered(container, "emit_darray_push", (
    "if not fast_capacity_proven:",
    'capacity: LLVMValueRef = darray_load_size_i64(capacity_pointer, ctx, builder, "push.cap", structs.target.target_pointer_bits)',
    'enough: LLVMValueRef = LLVMBuildICmp(builder, 36, count, capacity, "push.cap.ok")',
    "_ = LLVMBuildCondBr(builder, enough, store_block, grow_block)",
    "if emit_checked_reserve_binary(count, LLVMConstInt(int64_type, 1, 0), false, m, ctx, builder, structs.target.target_pointer_bits) is growth_needed:",
    "LLVMPositionBuilderAtEnd(builder, store_block)",
    'needed: LLVMValueRef = LLVMBuildAdd(builder, count, LLVMConstInt(int64_type, 1, 0), "push.needed")',
    "indices: mutable darray[LLVMValueRef] = [count]",
    'slot: LLVMValueRef = LLVMBuildGEP2(builder, llvm_type_of(element_type, structs, ctx), items, indices_pointer, 1, "push.slot")',
    "_ = LLVMBuildStore(builder, pushed_value, slot)",
))
ordered(prereserve, "emit_loop_prereserve", (
    "if bound is Expr.IntLit(limit, _) and limit > 0 and limit.u64() <= PRERESERVE_CAP:",
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
    Path(__file__), HERE / "proof_product_gate.py", CONTAINER, PRERESERVE, SIZE_TYPES, LLVM_C, POSITIVE,
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
