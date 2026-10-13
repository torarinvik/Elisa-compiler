"""Bind counted-fill cursor invariants to the stage1 backend implementation."""
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
PRERESERVE = ROOT / "src/backend/codegen_loop_prereserve.elisa"
CONTAINER = ROOT / "src/backend/codegen_container_ops.elisa"
SHAPES = ROOT / "src/backend/codegen_stmt_for_shapes.elisa"
LOOPS = ROOT / "src/backend/codegen_stmt_loops.elisa"
PROOF = HERE / "backend_fast_push_cursor.elisa"
REJECTED = HERE / "backend_fast_push_cursor_rejected.elisa"
POSITIVE = {
    "fast_push_cursor_starts_at_existing_count",
    "fast_push_cursor_advances_by_one",
    "fast_push_cursor_update_stays_within_reserved_end",
    "fast_push_cursor_update_strictly_progresses",
    "fast_push_remaining_work_stays_within_remaining_reservation",
    "fast_push_reserved_extra_fits_u32",
    "fast_push_cursor_final_count_is_exact",
    "fast_push_keeps_public_count_until_exit",
    "fast_push_count_observation_disables_cursor",
}
NEGATIVE = {
    "false_fast_push_cursor_starts_at_zero",
    "false_fast_push_public_count_advances_each_push",
    "false_fast_push_final_count_omits_existing_count",
    "false_fast_push_at_reserved_end_has_room",
    "false_fast_push_maximum_extra_exceeds_u32",
}
PROOF_SHA256 = {
    "fast_push_cursor_starts_at_existing_count": "4a25575b5e45f0f6c9a7e7449e5c5f7ef74c94bb3833d4c5c9370786c247de54",
    "fast_push_cursor_advances_by_one": "ef3dbe6b37064f091ec761f7cee62419b5bd8818ae803030f0021e38f037d769",
    "fast_push_cursor_update_stays_within_reserved_end": "9a9c78633a83a222cd35ceaa5954bb95264f98c9c7c09068ce041d8ebb06b8c8",
    "fast_push_cursor_update_strictly_progresses": "3f33448da04b867a79201efc968a0ef8b234ed00dc88d4d4c68ac1f7df1ea4ae",
    "fast_push_remaining_work_stays_within_remaining_reservation": "64e5fff4cd8e9d9463563e37e180befe71329b3b37d2f7db8a6735dd477f2ecd",
    "fast_push_reserved_extra_fits_u32": "4321bbf0292001b01e7f072156ce49d64b882254d84f8be5e9902697e6b9ec09",
    "fast_push_cursor_final_count_is_exact": "49deb1732dbefdf7881c371e7484662a896de44591440ef417cd33eabd0067fc",
    "fast_push_keeps_public_count_until_exit": "af3446a5632b2191da0b886145b85f65d05362acd9c46cdcbece2866b7a70d29",
    "fast_push_count_observation_disables_cursor": "5989c5f0f79a4663cba270882dd92c032f9b2018f2be04aece50b176f27385af",
    "false_fast_push_cursor_starts_at_zero": "6c7c26411477befbae30c5eadf852b3a2d2a70abf17510517818588c2ae2864f",
    "false_fast_push_public_count_advances_each_push": "c1f4f45ce0d7c3f3c717770825ae6d48dbe91342657273a687aeafe30810b793",
    "false_fast_push_final_count_omits_existing_count": "9e3e4097ff1227a97712f67761b319a3903b8c7dcf862102beca8739b165ff23",
    "false_fast_push_at_reserved_end_has_room": "933d377a531e210b5e25a201cd73657e8383b4f1ca6952aee388c8db304fb8cb",
    "false_fast_push_maximum_extra_exceeds_u32": "db24df8117e999374d703647c3695084c91ba5afaaea725d2c72049eb18ae4fd",
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


def ordered(source: str, function: str, steps: tuple[str, ...]) -> None:
    body = compact(section(source, function))
    cursor = 0
    for step in steps:
        needle = compact(step)
        pos = body.find(needle, cursor)
        if pos < 0:
            raise SystemExit(f"{function} no longer follows the proved cursor transition: {step}")
        cursor = pos + len(needle)


for path in (PRERESERVE, CONTAINER, SHAPES, LOOPS):
    if not path.is_file():
        raise SystemExit(f"missing cursor implementation source: {path}")

prereserve = PRERESERVE.read_text()
container = CONTAINER.read_text()
shapes = SHAPES.read_text()
reserve_body = compact(section(container, "emit_darray_reserve"))
if 'LLVMBuildStructGEP2(builder,header,array_slot,1,' in reserve_body or "count_pointer" in reserve_body:
    raise SystemExit("cursor reuse of the pre-reserve count requires reserve to leave DArray count untouched")
if "constPRERESERVE_CAP:u64=16777216" not in compact(prereserve):
    raise SystemExit("fast-fill proof cap differs from the compiler's bounded loop trip count")
if "constPRERESERVE_MAX_PUSHES:i64=64" not in compact(prereserve):
    raise SystemExit("fast-fill proof push bound differs from the compiler's admitted body bound")
if "constDARRAY_U32_MAX:u64=4294967295" not in compact(container):
    raise SystemExit("fast-fill reserve-width proof lost the target 32-bit usize maximum")
if 16777216 * 64 != 1073741824 or 1073741824 > 4294967295:
    raise SystemExit("fast-fill trip/push product no longer fits even the 32-bit usize maximum")
ordered(prereserve, "emit_loop_prereserve", (
    "pushes: i64 = prereserve_push_count(body, receiver, push_count_budget)",
    "skip <- true if pushes <= 0 or pushes > PRERESERVE_MAX_PUSHES",
    "skip <- true if not skip and not prereserve_body_ok(body, receiver, local_scope, scalar_loop_names, scalar_body_names, fns, structs, generics, runtime.overflow_wrap, proof_budget)",
    "if not skip:",
    'cap: LLVMValueRef = LLVMConstInt(i64_type, PRERESERVE_CAP, 0)',
    'capped: LLVMValueRef = LLVMBuildSelect(builder, LLVMBuildICmp(builder, 36, wide, cap, "prereserve.under.cap"), wide, cap, "prereserve.capped")',
    'trips: LLVMValueRef = LLVMBuildSelect(builder, positive, capped, zero, "prereserve.trips")',
    "if emit_checked_reserve_binary(trips, LLVMConstInt(i64_type, pushes.u64(), 0), true, m, ctx, builder, structs.target.target_pointer_bits) is extra:",
    'current: LLVMValueRef = darray_load_size_i64(count_pointer, ctx, builder, "prereserve.count", structs.target.target_pointer_bits)',
    "if emit_checked_reserve_binary(current, extra, false, m, ctx, builder, structs.target.target_pointer_bits) is needed:",
    "if (emit_darray_reserve(slot, receiver_type, needed, structs, growth_runtime, m, ctx, builder, true) can Global{Read,Write}):",
    "if bound is Expr.IntLit(limit, _) and limit > 0 and limit.u64() <= PRERESERVE_CAP:",
    "fast_push_slots.push(slot)",
    "cursor_budget: mutable usize = PRERESERVE_MAX_ANALYSIS_NODES",
    "if not prereserve_body_reads_darray_count(body, cursor_budget):",
    'items: LLVMValueRef = LLVMBuildLoad2(builder, LLVMPointerTypeInContext(ctx, 0), items_pointer, "fill.items")',
    "cursor_initial: LLVMValueRef = current",
    'cursor_slot: LLVMValueRef = build_entry_alloca(builder, LLVMInt64TypeInContext(ctx), "darray.fill.cursor")',
    "_ = LLVMBuildStore(builder, cursor_initial, cursor_slot)",
    "structs.memory.memory_fast_push_cursors.push(FastPushCursor{array_slot: slot, items: items, count_pointer: count_pointer, cursor_slot: cursor_slot})",
))
ordered(container, "emit_darray_push", (
    "if cursor_slot is push_cursor_slot:",
    'count <- LLVMBuildLoad2(builder, int64_type, push_cursor_slot, "push.cursor")',
    'needed: LLVMValueRef = LLVMBuildAdd(builder, count, LLVMConstInt(int64_type, 1, 0), "push.needed")',
    'slot: LLVMValueRef = LLVMBuildGEP2(builder, llvm_type_of(element_type, structs, ctx), items, indices_pointer, 1, "push.slot")',
    "_ = LLVMBuildStore(builder, pushed_value, slot)",
    "if cursor_slot is updated_cursor_slot:",
    "_ = LLVMBuildStore(builder, needed, updated_cursor_slot)",
))
ordered(shapes, "emit_statement_for_iterable_shapes", (
    'final_count: LLVMValueRef = LLVMBuildLoad2(builder, LLVMInt64TypeInContext(ctx), fast_push_cursor.cursor_slot, "fill.count.final")',
    "darray_store_size(builder, final_count, fast_push_cursor.count_pointer, ctx, structs.target.target_pointer_bits)",
))
ordered(LOOPS.read_text(), "emit_statement_loops", (
    "fast_push_cursor_mark: usize = structs.memory.memory_fast_push_cursors.count",
    "emit_loop_prereserve(for_variables, for_iterable, for_body",
    "while structs.memory.memory_fast_push_cursors.count > fast_push_cursor_mark:",
    "_ = structs.memory.memory_fast_push_cursors.pop()",
))

read_scan = compact(section(prereserve, "prereserve_expr_reads_darray_count"))
for required in (
    'return true if field == "count"',
    "Expr.Call(callee, arguments, _, _):",
    "Expr.Binary(left, _, right, _):",
    "Expr.Unary(_, operand, _) | Expr.Paren(operand, _):",
    "Expr.If(condition, yes, no, _):",
    "Expr.Block(nested, value, _, _):",
    "_:\nreturntrue",
):
    if compact(required) not in read_scan:
        raise SystemExit(f"count-observation scanner lost conservative case: {required}")

proof_names = declarations(PROOF)
if proof_names != POSITIVE or declarations(REJECTED) != NEGATIVE:
    raise SystemExit("fast-push cursor proof inventory changed")
for name, expected in PROOF_SHA256.items():
    owner = PROOF if name in POSITIVE else REJECTED
    actual = hashlib.sha256(compact(section(owner.read_text(), name)).encode()).hexdigest()
    if actual != expected:
        raise SystemExit(f"cursor theorem {name} changed since source binding")
if not REJECTED.read_text().startswith('include "./backend_fast_push_cursor.elisa"'):
    raise SystemExit("cursor false claims must include the positive transition specification")

if args.source_only:
    print(json.dumps({"source_bound": True, "positive": len(POSITIVE), "false_controls": len(NEGATIVE)}))
    raise SystemExit(0)

product = require_current_product(BIN, PROVER)
if product.get("compile_mode") != "strict":
    raise SystemExit("fast-push cursor proof requires a strict Elisa-Proof build")
inputs = list(dict.fromkeys([BIN, BIN.with_name(BIN.name + ".manifest.json"),
    BIN.with_name(BIN.name + ".manifest.json.sha256"), PROVER / "ELISA_COMPILER_REV",
    Path(__file__), HERE / "proof_product_gate.py", PRERESERVE, CONTAINER, SHAPES, LOOPS,
    PROOF, REJECTED, *source_include_closure([PROOF, REJECTED])]))
before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}


def run(path: Path) -> tuple[int, dict]:
    proc = subprocess.run([str(BIN), "--json", str(path)], capture_output=True, text=True, timeout=60)
    return proc.returncode, json.loads(proc.stdout)


code, report = run(PROOF)
assert code == 0 and report["status"] == report["verification_state"] == "proved"
assert report["summary"]["declarations"] == len(POSITIVE)
assert report["summary"]["obligations"] == report["summary"]["proven"]
assert {row["name"] for row in report["declaration_details"] if row.get("verified")} == POSITIVE
negative_code, negative_report = run(REJECTED)
assert negative_code == 1 and negative_report["status"] == "failed"
assert {row["name"] for row in negative_report["findings"]} == NEGATIVE
assert all(row["kind"] == "ensure-unproven" and row["status"] in ("unknown", "disproved")
           for row in negative_report["findings"])
if {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs} != before:
    raise SystemExit("source or proof product changed during replay")
print(json.dumps({"proved": report["summary"]["proven"], "positive_declarations": len(POSITIVE),
                  "false_claims_rejected": sorted(NEGATIVE), "source_bound": True}))
