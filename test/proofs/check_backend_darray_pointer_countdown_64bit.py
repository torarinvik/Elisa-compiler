"""Bind the full-u64 DArray pointer/countdown proof to generated LLVM lowering."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess

from proof_product_gate import require_current_product


ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve()
HERE = Path(__file__).resolve().parent
SOURCE = ROOT / "src/backend/codegen_interned_types.elisa"
LOOP = ROOT / "src/backend/codegen_stmt_for_shapes.elisa"
POSITIVE = HERE / "backend_darray_pointer_countdown_64bit.elisa"
NEGATIVE = HERE / "backend_darray_pointer_countdown_64bit_rejected.elisa"

parser = argparse.ArgumentParser()
parser.add_argument("--source-only", action="store_true")
args = parser.parse_args()

source = "".join(SOURCE.read_text().split())
loop = "".join(LOOP.read_text().split())
proof = "".join(POSITIVE.read_text().split())
negative = "".join(NEGATIVE.read_text().split())

if 'returnLLVMBuildZExt(builder,value,size_type,name)ifLLVMGetIntTypeWidth(source_type)<64elsevalue' not in source:
    raise SystemExit("DArray lengths must preserve all 64 bits and zero-extend narrower usize values")
if 'remaining_next:LLVMValueRef=LLVMBuildSub(builder,remaining_step,LLVMConstInt(int64_type,1,0)' not in loop:
    raise SystemExit("DArray pointer walk must decrement its saved count")
if 'keep_going<-LLVMBuildICmp(builder,33,remaining_cur,LLVMConstInt(int64_type,0,0)' not in loop:
    raise SystemExit("DArray pointer walk must stop exactly when the remaining count reaches zero")
ordered_lowering = (
    'cursor_next:LLVMValueRef=LLVMBuildGEP2(builder,llvm_type_of(element_type,structs,ctx),cursor,cursor_indices_pointer,1,"for.darray.cursor.next")',
    'LLVMBuildStore(builder,cursor_next,cursor_slot)',
    'remaining_step:LLVMValueRef=LLVMBuildLoad2(builder,int64_type,remaining_slot,"for.darray.remaining.step")',
    'remaining_next:LLVMValueRef=LLVMBuildSub(builder,remaining_step,LLVMConstInt(int64_type,1,0),"for.darray.remaining.next")',
    'LLVMBuildStore(builder,remaining_next,remaining_slot)',
)
positions = [loop.find(fragment) for fragment in ordered_lowering]
backedge = loop.find('LLVMBuildBr(builder,head_block)', positions[-1]) if positions[-1] >= 0 else -1
positions.append(backedge)
if any(position < 0 for position in positions) or positions != sorted(positions) or len(set(positions)) != len(positions):
    raise SystemExit("cursor increment and countdown decrement must both precede the pointer-walk back edge")
required = (
    "defpointer_walk_cursor_step_stays_within_count_u64(count:u64,cursor:u64)->bool:requirescursor<countensureresult==truereturncursor+1<=count",
    "defpointer_walk_countdown_step_decreases_u64(remaining:u64)->bool:requiresremaining>0ensureresult==truereturnremaining-1<remaining",
    "defpointer_walk_countdown_step_stays_nonnegative_u64(remaining:u64)->bool:requiresremaining>0ensureresult==truereturnremaining-1>=0",
)
if any(shape not in proof for shape in required):
    raise SystemExit("full-u64 countdown proof lost its cursor or nonwrapping decrement obligations")
negative_shapes = (
    'deffalse_zero_remaining_decrements_to_positive_u64()->bool:ensureresult==truereturn0.u64()-1.u64()>0.u64()',
    "deffalse_cursor_at_end_is_inside_snapshot_u64(count:u64)->bool:requirescount>0ensureresult==truereturncount<count",
)
if 'include"./backend_darray_pointer_countdown_64bit.elisa"' not in negative or any(
        shape not in negative for shape in negative_shapes):
    raise SystemExit("u64 countdown false controls no longer target zero and one-past-end boundaries")

if args.source_only:
    print(json.dumps({"source_bound": True, "scope": "full u64 DArray count domain",
                      "positive_theorems": len(required), "false_controls": len(negative_shapes)}, sort_keys=True))
    raise SystemExit(0)

product = require_current_product(BIN, PROVER)
if product.get("compile_mode") != "strict":
    raise SystemExit("full-u64 DArray countdown proof requires a strict Elisa-Proof build")


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=60)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == {
    "pointer_walk_cursor_step_stays_within_count_u64",
    "pointer_walk_countdown_step_decreases_u64",
    "pointer_walk_countdown_step_stays_nonnegative_u64",
}
code, negative_report = run(NEGATIVE)
assert code == 1 and negative_report["status"] == "failed"
assert {finding["name"] for finding in negative_report["findings"]} == {
    "false_zero_remaining_decrements_to_positive_u64",
    "false_cursor_at_end_is_inside_snapshot_u64",
}
assert all(finding["kind"] == "ensure-unproven" for finding in negative_report["findings"])
print(json.dumps({"source_bound": True, "positive_obligations": positive["summary"]["proven"],
                  "replay_gaps": 0, "false_controls_rejected": len(negative_shapes)}, sort_keys=True))
