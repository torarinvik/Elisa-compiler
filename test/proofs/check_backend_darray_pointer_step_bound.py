"""Bind the verified pointer cursor step lemma to DArray for-loop lowering."""
import argparse
import json
import os
from pathlib import Path
import subprocess

from proof_product_gate import require_current_product

parser = argparse.ArgumentParser()
parser.add_argument("--source-only", action="store_true")
args = parser.parse_args()
ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve(strict=not args.source_only)
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=not args.source_only)
LOWERING = ROOT / "src/backend/codegen_stmt_for_shapes.elisa"
PROOF = ROOT / "test/proofs/backend_darray_pointer_step_bound.elisa"
REJECTED = ROOT / "test/proofs/backend_darray_pointer_step_bound_rejected.elisa"
source = "".join(LOWERING.read_text().split())
proof = "".join(PROOF.read_text().split())
rejected = "".join(REJECTED.read_text().split())
source_steps = (
    'LLVMBuildICmp(builder,33,remaining_cur,LLVMConstInt(int64_type,0,0),"for.darray.remaining.nonzero")',
    'cursor_next:LLVMValueRef=LLVMBuildGEP2(builder,llvm_type_of(element_type,structs,ctx),cursor,cursor_indices_pointer,1,"for.darray.cursor.next")',
    'remaining_next:LLVMValueRef=LLVMBuildSub(builder,remaining_step,LLVMConstInt(int64_type,1,0),"for.darray.remaining.next")',
)
if any(step not in source for step in source_steps):
    raise SystemExit("pointer-step proof no longer matches the guarded cursor and remaining-count transition")
proof_shape = "defcursor_step_stays_within_snapshot(count:u64,cursor:u64)->bool:requirescursor<countrequirescursor<U64_MAXensureresult==truereturncursor+1<=count"
if proof_shape not in proof:
    raise SystemExit("pointer cursor-step theorem changed its nonwrapping preconditions or postcondition")
rejected_shape = "deffalse_cursor_step_exceeds_snapshot(count:u64,cursor:u64)->bool:requirescursor<countrequirescursor<U64_MAXensureresult==truereturncursor+1>count"
if rejected_shape not in rejected or 'include"./backend_darray_pointer_step_bound.elisa"' not in rejected:
    raise SystemExit("false cursor-step control no longer challenges the admitted snapshot bound")
if args.source_only:
    print(json.dumps({"source_bound": True, "theorem": "cursor_step_stays_within_snapshot", "false_control": "false_cursor_step_exceeds_snapshot"}))
    raise SystemExit(0)
product = require_current_product(BIN, PROVER)
if product.get("compile_mode") != "strict":
    raise SystemExit("pointer cursor-step proof requires a strict Elisa-Proof build")
report = json.loads(subprocess.run([str(BIN), "--json", str(PROOF)], capture_output=True, text=True, timeout=60).stdout)
assert report["status"] == report["verification_state"] == "proved"
assert report["summary"]["proven"] == report["summary"]["obligations"]
assert report["replay"]["gaps"] == 0
assert {row["name"] for row in report["declaration_details"] if row.get("verified")} == {"cursor_step_stays_within_snapshot"}
negative = json.loads(subprocess.run([str(BIN), "--json", str(REJECTED)], capture_output=True, text=True, timeout=60).stdout)
assert negative["status"] == "failed"
assert {row["name"] for row in negative["findings"]} == {"false_cursor_step_exceeds_snapshot"}
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
print(json.dumps({"source_bound": True, "positive_obligations": report["summary"]["proven"], "replay_gaps": 0, "false_control_rejected": True}))
