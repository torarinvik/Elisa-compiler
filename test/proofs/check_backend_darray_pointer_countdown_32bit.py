"""Bind 32-bit DArray cursor/countdown arithmetic to zero-extended production lengths."""
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
SIZES = ROOT / "src/backend/codegen_interned_types.elisa"
RUNTIME_DECL = ROOT / "src/backend/codegen_runtime_decl.elisa"
LOOPS = ROOT / "src/backend/codegen_stmt_for_shapes_iterable.elisa"
PROOF = ROOT / "test/proofs/backend_darray_pointer_countdown_32bit.elisa"
REJECTED = ROOT / "test/proofs/backend_darray_pointer_countdown_32bit_rejected.elisa"
compact_sizes = "".join(SIZES.read_text().split())
compact_loops = "".join(LOOPS.read_text().split())
compact_proof = "".join(PROOF.read_text().split())
compact_rejected = "".join(REJECTED.read_text().split())
if 'returnLLVMBuildZExt(builder,value,size_type,name)ifLLVMGetIntTypeWidth(source_type)<64elsevalue' not in compact_sizes:
    raise SystemExit("DArray usize lengths must remain zero-extended when widened to i64")
if 'returnLLVMInt32TypeInContext(ctx)iftarget_bits==32returnLLVMInt64TypeInContext(ctx)' not in compact_sizes:
    raise SystemExit("DArray usize must remain exactly 32 or 64 bits on supported targets")
if 'LLVMBuildICmp(builder,33,remaining_cur,LLVMConstInt(int64_type,0,0),"for.darray.remaining.nonzero")' not in compact_loops or \
        'remaining_next:LLVMValueRef=LLVMBuildSub(builder,remaining_step,LLVMConstInt(int64_type,1,0),"for.darray.remaining.next")' not in compact_loops:
    raise SystemExit("DArray pointer loop no longer guards and decrements its remaining-count slot")
required = (
    "constU32_MAX:i64=4294967295",
    "defpointer_walk_countdown_step_decreases(remaining:i64)->bool:requiresremaining>0andremaining<=U32_MAXensureresult==truereturnremaining-1<remaining",
    "defpointer_walk_countdown_next_stays_in_range(remaining:i64)->bool:requiresremaining>0andremaining<=U32_MAXensureresult==truereturnremaining-1>=0andremaining-1<=U32_MAX",
    "defpointer_walk_cursor_step_stays_within_count(count:i64,cursor:i64)->bool:requirescount>=0andcount<=U32_MAXrequirescursor>=0andcursor<countensureresult==truereturncursor+1<=count",
    "defmaximum_u32_cursor_step_reaches_one_past_end()->bool:ensureresult==truereturn(U32_MAX-1)+1==U32_MAX",
    "deffinal_positive_remaining_step_reaches_zero()->bool:ensureresult==truereturn1-1==0",
)
if any(shape not in compact_proof for shape in required):
    raise SystemExit("32-bit countdown proof lost its full-u32 range conditions")
if 'include"./backend_darray_pointer_countdown_32bit.elisa"' not in compact_rejected or \
        "deffalse_one_past_cursor_is_inside_snapshot(count:i64,cursor:i64)->bool:requirescount==U32_MAXrequirescursor==countensureresult==truereturncursor<count" not in compact_rejected:
    raise SystemExit("32-bit countdown false control no longer rejects a one-past-end element access")
if "deffalse_zero_count_has_a_positive_next_count()->bool:ensureresult==truereturn0-1>0" not in compact_rejected:
    raise SystemExit("32-bit countdown false control no longer rejects decrement below the zero boundary")
if args.source_only:
    print(json.dumps({"source_bound": True, "scope": "32-bit usize counts zero-extended to i64", "false_control": "one-past cursor excluded"}))
    raise SystemExit(0)
product = require_current_product(BIN, PROVER)
if product.get("compile_mode") != "strict":
    raise SystemExit("DArray 32-bit countdown proof requires a strict Elisa-Proof build")
report = json.loads(subprocess.run([str(BIN), "--json", str(PROOF)], capture_output=True, text=True, timeout=60).stdout)
assert report["status"] == report["verification_state"] == "proved"
assert report["summary"]["proven"] == report["summary"]["obligations"]
assert report["replay"]["gaps"] == 0
assert {row["name"] for row in report["declaration_details"] if row.get("verified")} == {
    "pointer_walk_countdown_step_decreases", "pointer_walk_cursor_step_stays_within_count",
    "pointer_walk_countdown_next_stays_in_range",
    "maximum_u32_cursor_step_reaches_one_past_end", "final_positive_remaining_step_reaches_zero"}
negative = json.loads(subprocess.run([str(BIN), "--json", str(REJECTED)], capture_output=True, text=True, timeout=60).stdout)
assert negative["status"] == "failed"
assert {finding["name"] for finding in negative["findings"]} == {
    "false_one_past_cursor_is_inside_snapshot", "false_zero_count_has_a_positive_next_count"}
assert all(finding["kind"] == "ensure-unproven" for finding in negative["findings"])
print(json.dumps({"source_bound": True, "positive_obligations": report["summary"]["proven"], "replay_gaps": 0,
                  "false_control_rejected": True}))
