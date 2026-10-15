"""Bind aggregate-copy window barrier proofs to the LLVM rewrite guards."""
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
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=not args.source_only)
SOURCE = ROOT / "src/backend/codegen_aggregate_copies.elisa"
POSITIVE = HERE / "backend_aggregate_copy_barriers.elisa"
SIZE_PROOF = HERE / "backend_aggregate_size_threshold.elisa"
SIZE_NEGATIVE = HERE / "backend_aggregate_size_threshold_rejected.elisa"
EXTRACT_SHAPE = HERE / "backend_aggregate_extract_shape.elisa"
ERASE_UNUSED = HERE / "backend_aggregate_erase_unused.elisa"
VOLATILE_GUARD = HERE / "backend_aggregate_volatile_guard.elisa"
SPLIT_VOLATILE_GUARD = HERE / "backend_aggregate_split_volatile_guard.elisa"
NONEMPTY_USERS = HERE / "backend_aggregate_nonempty_users.elisa"
USER_FILTER = HERE / "backend_aggregate_user_filter.elisa"
FIELD_ALIGNMENT = HERE / "backend_aggregate_field_alignment.elisa"


def compact(text: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in text.splitlines())


def section(text: str, name: str) -> str:
    match = re.search(rf"(?m)^([ \t]*)def {re.escape(name)}\(", text)
    if match is None:
        raise SystemExit(f"missing function {name}")
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}def [A-Za-z_]\w*\(", text[match.end():])
    end = match.end() + following.start() if following else len(text)
    return text[match.start():end]


source = SOURCE.read_text()
clobbers = compact(section(source, "aggregate_copy_window_clobbers"))
required_clobber_fragments = (
    "ifopcode==OPCODE_STORE:",
    "elifopcode==45oropcode==5oropcode==67oropcode==55oropcode==56oropcode==57oropcode==49:",
    "returntrue",
)
if not all(fragment in clobbers for fragment in required_clobber_fragments):
    raise SystemExit("aggregate-copy window no longer rejects stores and call/atomic barriers")

rewrite = compact(section(source, "lower_large_aggregate_store"))
if "aggregate_copy_window_clobbers(value,store,source)" not in rewrite:
    raise SystemExit("large aggregate store rewrite bypasses its clobber-window guard")
for fragment in (
        "returnfalseifLLVMGetVolatile(store)!=0",
        "LLVMGetVolatile(value)!=0",
        "LLVMGetVolatile(outer)!=0"):
    if fragment not in rewrite:
        raise SystemExit(f"aggregate copy rewrite no longer guards volatile accesses: {fragment}")
splitter = compact(section(source, "split_large_aggregate_load"))
if not splitter.startswith("defsplit_large_aggregate_load(") or not splitter.startswith("defsplit_large_aggregate_load(load:LLVMValueRef,builder:LLVMBuilderRef,target_data:LLVMTargetDataRef)->boolcan[Abort.Panic,Memory.Allocate]:returnfalseifLLVMGetVolatile(load)!=0"):
    raise SystemExit("large aggregate load splitter no longer fails closed on volatile loads")
if "returnfalseifusers.count==0" not in splitter:
    raise SystemExit("large aggregate load splitter no longer rejects unused loads")
user_filter_order = (
    "notis_instruction_with_opcode(user,OPCODE_EXTRACT_VALUE)",
    "aggregate_extract_field(user)<0",
    "users.push(user)",
)
positions = [splitter.find(fragment) for fragment in user_filter_order]
if any(position < 0 for position in positions) or positions != sorted(positions):
    raise SystemExit("load splitter no longer filters every use before collecting it")
field_alignment = compact(section(source, "lower_large_aggregate_store"))
if ("field_align:mutableu32=LLVMABIAlignmentOfType(target_data,value_type)" not in field_alignment or
        "field_align<-LLVMGetAlignment(outer)ifLLVMGetAlignment(outer)<field_align" not in field_alignment or
        "LLVMBuildMemMove(builder,destination,store_align,field_pointer,field_align,size)" not in field_alignment or
        "field_align:mutableu32=LLVMABIAlignmentOfType(target_data,field_type)" not in splitter or
        "field_align<-load_alignifload_align<field_align" not in splitter or
        "LLVMSetAlignment(narrow,field_align)" not in splitter):
    raise SystemExit("aggregate field rewrites no longer cap alignment at ABI and source alignment")
large_type = compact(section(source, "is_large_aggregate_type"))
if ("constLARGE_AGGREGATE_BYTES:u64=64" not in compact(source) or
        large_type != compact("""
            def is_large_aggregate_type(ty: LLVMTypeRef, target_data: LLVMTargetDataRef) -> bool:
                kind: u32 = LLVMGetTypeKind(ty)
                return false if kind != 10 and kind != 11
                LLVMABISizeOfType(target_data, ty) > LARGE_AGGREGATE_BYTES
        """)):
    raise SystemExit("aggregate kind and strict size guards changed")
extract_field = compact(section(source, "aggregate_extract_field"))
if ("return-1ifLLVMGetNumIndices(extract)!=1" not in extract_field or
        "return-1ifLLVMGetTypeKind(aggregate_type)!=10" not in extract_field):
    raise SystemExit("aggregate field extractor no longer fails closed on unsupported extract shapes")
erase_unused = compact(section(source, "erase_if_unused"))
if erase_unused != compact("""
    def erase_if_unused(value: LLVMValueRef) -> void:
        if LLVMIsAInstruction(value) is instruction:
            if LLVMGetFirstUse(instruction) != null:
                return
            LLVMInstructionEraseFromParent(instruction)
"""):
    raise SystemExit("aggregate rewrite no longer erases only instructions with no uses")

proof = POSITIVE.read_text()
expected = {
    "aggregate_copy_window_barrier": """
        def aggregate_copy_window_barrier(opcode: u32) -> bool:
            ensure result == (opcode == OPCODE_STORE or opcode == OPCODE_CALL or opcode == OPCODE_INVOKE or opcode == OPCODE_CALLBR or opcode == OPCODE_FENCE or opcode == OPCODE_CMPXCHG or opcode == OPCODE_ATOMICRMW or opcode == OPCODE_VA_ARG)
            return opcode == OPCODE_STORE or opcode == OPCODE_CALL or opcode == OPCODE_INVOKE or opcode == OPCODE_CALLBR or opcode == OPCODE_FENCE or opcode == OPCODE_CMPXCHG or opcode == OPCODE_ATOMICRMW or opcode == OPCODE_VA_ARG
    """,
    "aggregate_copy_store_is_a_window_barrier": """
        def aggregate_copy_store_is_a_window_barrier() -> bool:
            ensure result == true
            return aggregate_copy_window_barrier(OPCODE_STORE)
    """,
    "aggregate_copy_call_and_atomic_operations_are_barriers": """
        def aggregate_copy_call_and_atomic_operations_are_barriers() -> bool:
            ensure result == true
            return aggregate_copy_window_barrier(OPCODE_CALL) and aggregate_copy_window_barrier(OPCODE_INVOKE) and aggregate_copy_window_barrier(OPCODE_CALLBR) and aggregate_copy_window_barrier(OPCODE_FENCE) and aggregate_copy_window_barrier(OPCODE_CMPXCHG) and aggregate_copy_window_barrier(OPCODE_ATOMICRMW) and aggregate_copy_window_barrier(OPCODE_VA_ARG)
    """,
}
size_expected = {
    "aggregate_kind_is_struct_or_array": """
        def aggregate_kind_is_struct_or_array(kind: u32) -> bool:
            ensure result == (kind == STRUCT_TYPE_KIND or kind == ARRAY_TYPE_KIND)
            return kind == STRUCT_TYPE_KIND or kind == ARRAY_TYPE_KIND
    """,
    "aggregate_size_exceeds_threshold": """
        def aggregate_size_exceeds_threshold(size: u64) -> bool:
            ensure result == (size > LARGE_AGGREGATE_BYTES)
            return size > LARGE_AGGREGATE_BYTES
    """,
    "threshold_boundary_is_not_large": """
        def threshold_boundary_is_not_large() -> bool:
            ensure result == false
            return LARGE_AGGREGATE_BYTES > LARGE_AGGREGATE_BYTES
    """,
    "first_byte_above_threshold_is_large": """
        def first_byte_above_threshold_is_large() -> bool:
            ensure result == true
            return LARGE_AGGREGATE_BYTES + 1 > LARGE_AGGREGATE_BYTES
    """,
}
if not proof.startswith('# Conservative instruction barrier model'):
    raise SystemExit("barrier proof lost its purpose header")
for name, shape in expected.items():
    if compact(section(proof, name)) != compact(shape):
        raise SystemExit(f"proof claim {name} changed without source review")
size_proof = SIZE_PROOF.read_text()
size_negative = SIZE_NEGATIVE.read_text()
extract_shape = EXTRACT_SHAPE.read_text()
erase_proof = ERASE_UNUSED.read_text()
volatile_proof = VOLATILE_GUARD.read_text()
split_volatile_proof = SPLIT_VOLATILE_GUARD.read_text()
nonempty_proof = NONEMPTY_USERS.read_text()
user_filter_proof = USER_FILTER.read_text()
alignment_proof = FIELD_ALIGNMENT.read_text()
if not size_proof.startswith('# Scalar components of the large aggregate rewrite'):
    raise SystemExit("size proof no longer documents its scalar guard scope")
for name, shape in size_expected.items():
    if compact(section(size_proof, name)) != compact(shape):
        raise SystemExit(f"proof claim {name} changed without source review")
if (not re.search(r"(?m)^const LARGE_AGGREGATE_BYTES: u64 = 64$", size_negative) or
        compact(section(size_negative, "false_first_byte_above_threshold_is_not_large")) != compact("""
            def false_first_byte_above_threshold_is_not_large() -> bool:
                ensure result == true
                return LARGE_AGGREGATE_BYTES + 1 <= LARGE_AGGREGATE_BYTES
        """)):
    raise SystemExit("size-threshold false control changed its strict-cutoff claim")
if not re.search(r"(?m)^const SINGLE_INDEX: u32 = 1$", extract_shape) or not re.search(r"(?m)^const STRUCT_KIND: u32 = 10$", extract_shape):
    raise SystemExit("extract-shape proof constants no longer match the production guard values")
extract_expected = {
    "aggregate_extract_shape_is_supported": """
        def aggregate_extract_shape_is_supported(index_count: u32, aggregate_kind: u32) -> bool:
            ensure result == (index_count == SINGLE_INDEX and aggregate_kind == STRUCT_KIND)
            return index_count == SINGLE_INDEX and aggregate_kind == STRUCT_KIND
    """,
    "aggregate_extract_rejects_wrong_index_counts": """
        def aggregate_extract_rejects_wrong_index_counts(index_count: u32) -> bool:
            requires index_count != SINGLE_INDEX
            ensure result == false
            return aggregate_extract_shape_is_supported(index_count, STRUCT_KIND)
    """,
    "aggregate_extract_rejects_non_struct_types": """
        def aggregate_extract_rejects_non_struct_types(aggregate_kind: u32) -> bool:
            requires aggregate_kind != STRUCT_KIND
            ensure result == false
            return aggregate_extract_shape_is_supported(SINGLE_INDEX, aggregate_kind)
    """,
}
for name, shape in extract_expected.items():
    if compact(section(extract_shape, name)) != compact(shape):
        raise SystemExit(f"proof claim {name} changed without source review")
erase_expected = {
    "aggregate_instruction_may_be_erased": """
        def aggregate_instruction_may_be_erased(is_instruction: bool, first_use_is_null: bool) -> bool:
            ensure result == (is_instruction and first_use_is_null)
            return is_instruction and first_use_is_null
    """,
    "a_used_instruction_is_never_erased": """
        def a_used_instruction_is_never_erased(first_use_is_null: bool) -> bool:
            requires not first_use_is_null
            ensure result == false
            return aggregate_instruction_may_be_erased(true, first_use_is_null)
    """,
    "a_non_instruction_is_never_erased": """
        def a_non_instruction_is_never_erased(first_use_is_null: bool) -> bool:
            ensure result == false
            return aggregate_instruction_may_be_erased(false, first_use_is_null)
    """,
}
for name, shape in erase_expected.items():
    if compact(section(erase_proof, name)) != compact(shape):
        raise SystemExit(f"proof claim {name} changed without source review")
volatile_expected = {
    "aggregate_copy_may_rewrite": """
        def aggregate_copy_may_rewrite(store_is_volatile: bool, source_is_volatile: bool) -> bool:
            ensure result == (not store_is_volatile and not source_is_volatile)
            return not store_is_volatile and not source_is_volatile
    """,
    "a_volatile_store_is_not_rewritten": """
        def a_volatile_store_is_not_rewritten(source_is_volatile: bool) -> bool:
            ensure result == false
            return aggregate_copy_may_rewrite(true, source_is_volatile)
    """,
    "a_volatile_source_load_is_not_rewritten": """
        def a_volatile_source_load_is_not_rewritten(store_is_volatile: bool) -> bool:
            ensure result == false
            return aggregate_copy_may_rewrite(store_is_volatile, true)
    """,
    "nonvolatile_operands_pass_the_volatile_guard": """
        def nonvolatile_operands_pass_the_volatile_guard() -> bool:
            ensure result == true
            return aggregate_copy_may_rewrite(false, false)
    """,
}
for name, shape in volatile_expected.items():
    if compact(section(volatile_proof, name)) != compact(shape):
        raise SystemExit(f"proof claim {name} changed without source review")
split_volatile_expected = {
    "aggregate_load_may_be_split": """
        def aggregate_load_may_be_split(is_volatile: bool) -> bool:
            ensure result == not is_volatile
            return not is_volatile
    """,
    "a_volatile_aggregate_load_is_not_split": """
        def a_volatile_aggregate_load_is_not_split() -> bool:
            ensure result == false
            return aggregate_load_may_be_split(true)
    """,
    "a_nonvolatile_aggregate_load_passes_the_volatile_guard": """
        def a_nonvolatile_aggregate_load_passes_the_volatile_guard() -> bool:
            ensure result == true
            return aggregate_load_may_be_split(false)
    """,
}
for name, shape in split_volatile_expected.items():
    if compact(section(split_volatile_proof, name)) != compact(shape):
        raise SystemExit(f"proof claim {name} changed without source review")
nonempty_expected = {
    "aggregate_load_has_rewrite_users": """
        def aggregate_load_has_rewrite_users(user_count: usize) -> bool:
            ensure result == (user_count > 0.usize())
            return user_count > 0.usize()
    """,
    "unused_aggregate_load_is_not_split": """
        def unused_aggregate_load_is_not_split() -> bool:
            ensure result == false
            return aggregate_load_has_rewrite_users(0.usize())
    """,
}
for name, shape in nonempty_expected.items():
    if compact(section(nonempty_proof, name)) != compact(shape):
        raise SystemExit(f"proof claim {name} changed without source review")
user_filter_expected = {
    "aggregate_split_user_is_accepted": """
        def aggregate_split_user_is_accepted(is_extract_value: bool, has_resolved_field: bool) -> bool:
            ensure result == (is_extract_value and has_resolved_field)
            return is_extract_value and has_resolved_field
    """,
    "non_extract_user_is_rejected": """
        def non_extract_user_is_rejected(has_resolved_field: bool) -> bool:
            ensure result == false
            return aggregate_split_user_is_accepted(false, has_resolved_field)
    """,
    "unresolved_field_user_is_rejected": """
        def unresolved_field_user_is_rejected(is_extract_value: bool) -> bool:
            ensure result == false
            return aggregate_split_user_is_accepted(is_extract_value, false)
    """,
    "a_valid_extract_user_passes_the_filter": """
        def a_valid_extract_user_passes_the_filter() -> bool:
            ensure result == true
            return aggregate_split_user_is_accepted(true, true)
    """,
}
for name, shape in user_filter_expected.items():
    if compact(section(user_filter_proof, name)) != compact(shape):
        raise SystemExit(f"proof claim {name} changed without source review")
alignment_expected = """
    def conservative_field_alignment(abi_alignment: u32, source_alignment: u32) -> u32:
        ensure result <= abi_alignment
        ensure result <= source_alignment
        return source_alignment if source_alignment < abi_alignment else abi_alignment
"""
if compact(section(alignment_proof, "conservative_field_alignment")) != compact(alignment_expected):
    raise SystemExit("field-alignment theorem no longer bounds the selected alignment")
opcode_bindings = {
    "OPCODE_STORE": "28", "OPCODE_CALL": "45", "OPCODE_INVOKE": "5",
    "OPCODE_CALLBR": "67", "OPCODE_FENCE": "55", "OPCODE_CMPXCHG": "56",
    "OPCODE_ATOMICRMW": "57", "OPCODE_VA_ARG": "49",
}
for name, value in opcode_bindings.items():
    if not re.search(rf"(?m)^const {name}: u32 = {value}$", proof):
        raise SystemExit(f"proof opcode {name} no longer matches LLVM's production discriminator")
for name, value in {"STRUCT_TYPE_KIND": "10", "ARRAY_TYPE_KIND": "11"}.items():
    if not re.search(rf"(?m)^const {name}: u32 = {value}$", size_proof):
        raise SystemExit(f"proof type kind {name} no longer matches LLVM's production discriminator")
if not re.search(r"(?m)^const LARGE_AGGREGATE_BYTES: u64 = 64$", size_proof):
    raise SystemExit("proof threshold no longer matches the production aggregate rewrite")
if 'include "../../src/backend/codegen_aggregate_copies.elisa"' in proof:
    raise SystemExit("proof must use the pure numeric model and bind its opcodes in this checker")

if args.source_only:
    print(json.dumps({"source_bound": True, "positive_theorems": len(expected) + len(size_expected) + len(extract_expected) + len(erase_expected) + len(volatile_expected) + len(split_volatile_expected) + len(nonempty_expected) + len(user_filter_expected) + 1, "false_controls": 1, "production_barriers": 8, "aggregate_kind_cases": 2, "size_threshold_bytes": 64, "extract_shape_guard_theorems": len(extract_expected), "erase_use_guard_theorems": len(erase_expected), "volatile_guard_theorems": len(volatile_expected) + len(split_volatile_expected), "nonempty_use_guard_theorems": len(nonempty_expected), "user_filter_guard_theorems": len(user_filter_expected), "field_alignment_bounds": 2}, sort_keys=True))
    raise SystemExit(0)

product = require_current_product(BIN, PROVER)
if product.get("compile_mode") != "strict":
    raise SystemExit("aggregate-copy barrier proofs require a strict Elisa-Proof build")
closure = source_include_closure([POSITIVE, SIZE_PROOF, SIZE_NEGATIVE, EXTRACT_SHAPE, ERASE_UNUSED, VOLATILE_GUARD, SPLIT_VOLATILE_GUARD, NONEMPTY_USERS, USER_FILTER, FIELD_ALIGNMENT])
inputs = [Path(__file__), HERE / "proof_product_gate.py", SOURCE, POSITIVE, SIZE_PROOF, SIZE_NEGATIVE, EXTRACT_SHAPE, ERASE_UNUSED, VOLATILE_GUARD, SPLIT_VOLATILE_GUARD, NONEMPTY_USERS, USER_FILTER, FIELD_ALIGNMENT, *closure,
          BIN, BIN.with_name(BIN.name + ".manifest.json"), PROVER / "ELISA_COMPILER_REV"]
before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in dict.fromkeys(inputs)}
reports = []
for proof_path in (POSITIVE, SIZE_PROOF, EXTRACT_SHAPE, ERASE_UNUSED, VOLATILE_GUARD, SPLIT_VOLATILE_GUARD, NONEMPTY_USERS, USER_FILTER, FIELD_ALIGNMENT):
    run = subprocess.run([str(BIN), "--json", str(proof_path)], capture_output=True, text=True, timeout=60)
    report = json.loads(run.stdout)
    summary = report.get("summary", {})
    replay = report.get("replay", {})
    if (run.returncode != 0 or report.get("status") != "proved" or
            summary.get("semantic_errors") != 0 or summary.get("unproven") != 0 or
            summary.get("proven") != summary.get("obligations") or
            replay.get("certificates") != replay.get("replayed") or replay.get("gaps") != 0 or
            report.get("trust", {}).get("trusted_assumptions")):
        raise SystemExit(f"aggregate-copy proof replay failed for {proof_path.name}: {summary}")
    reports.append(report)
negative_run = subprocess.run([str(BIN), "--json", str(SIZE_NEGATIVE)], capture_output=True, text=True, timeout=60)
negative = json.loads(negative_run.stdout)
negative_summary = negative.get("summary", {})
negative_replay = negative.get("replay", {})
findings = negative.get("findings", [])
if (negative_run.returncode != 1 or negative.get("status") != "failed" or
        negative_summary.get("semantic_errors") != 0 or negative_summary.get("unproven") != 1 or
        negative_summary.get("finding_count") != 1 or len(findings) != 1 or
        findings[0].get("name") != "false_first_byte_above_threshold_is_not_large" or
        findings[0].get("kind") != "ensure-unproven" or findings[0].get("status") not in ("unknown", "disproved") or
        negative_replay.get("certificates") != negative_replay.get("replayed") or negative_replay.get("gaps") != 0):
    raise SystemExit("inclusive-threshold false control was not isolated and rejected")
if {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in dict.fromkeys(inputs)} != before:
    raise SystemExit("aggregate-copy barrier proof inputs changed during replay")
print(json.dumps({"source_bound": True, "proved": sum(report["summary"]["proven"] for report in reports), "false_controls_rejected": len(findings), "replay_gaps": sum(report["replay"]["gaps"] for report in reports) + negative_replay["gaps"]}, sort_keys=True))
