"""Admit the EASM control-flow meet proof against a strict Elisa-proof product."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure
from easm_flow_production_expectations import (
    EXPECTED_DECLARATIONS,
    FALSE_CLAIMS,
    expected_returns,
    expected_width_policy,
    expected_slot_map,
    expected_implicit_result_body,
    expected_propagate,
    expected_provenance_propagate,
    expected_empty_provenance,
    expected_provenance_equal,
    expected_xchg_transfer_prefix,
    expected_production_call,
    expected_implicit_results,
    expected_full_width_move,
    expected_partial_exchange,
)
from easm_flow_proof_expectations import (
    expected_flag_difference,
    expected_empty_flow_table,
    expected_second_predecessor,
    expected_one_sided_flags,
    expected_first_predecessor,
    expected_order_independence,
    expected_three_way_associativity,
    expected_duplicate_idempotence,
    expected_provenance_join,
    expected_first_provenance,
    expected_duplicate_provenance,
    expected_production_xchg,
    expected_out_of_range_noop,
    expected_changed_contract,
    expected_iteration,
    expected_missing_check,
    expected_module_compositions,
)
from easm_flow_false_claim_expectations import (
    expected_invalid_entry_control,
    expected_order_control,
    expected_three_way_control,
    expected_duplicate_control,
    expected_bad_target_controls,
    expected_meet_only_control,
    expected_conflicting_provenance_control,
    expected_first_provenance_control,
    expected_duplicate_provenance_control,
    expected_production_xchg_control,
    expected_production_call_control,
    expected_cpuid_control,
    expected_partial_move_control,
    expected_partial_exchange_control,
)


ROOT = Path(__file__).resolve().parents[2]
PROVER = ROOT.parent / "elisa-proof"
HERE = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument("--source-only", action="store_true",
                    help="check source and fixture bindings without invoking Elisa-Proof")
ARGS = parser.parse_args()
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=not ARGS.source_only)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
POSITIVE = HERE / "easm_flow_join.elisa"
NEGATIVE = HERE / "easm_flow_join_rejected.elisa"
MASKS = ROOT / "src/backend/easm_register_masks.elisa"
MODEL = ROOT / "src/backend/easm_model.elisa"
MEMORY = ROOT / "src/backend/easm_verify_memory.elisa"
WIDTH_POLICY = ROOT / "src/backend/easm_address_width_policy.elisa"
PROVENANCE = ROOT / "src/backend/easm_verify_provenance.elisa"
VERIFY_FUNCTION = ROOT / "src/backend/easm_verify_function.elisa"
REGISTER_NAMES = ("RAX", "RCX", "RDX", "RBX", "RSI", "RDI", "RBP", "RSP", "R8", "R9", "R10", "R11", "R12", "R13", "R14", "R15")
EXPECTED_MASKS = {name: 1 << bit for bit, name in enumerate(REGISTER_NAMES)}


if not __debug__:
    raise SystemExit("run without Python -O")


def compact(value: str) -> str:
    return " ".join(value.split())


def source_body(source: str, signature: str) -> str:
    if signature not in source:
        raise SystemExit(f"missing production function: {signature}")
    return source.split(signature, 1)[1].split("\n        def ", 1)[0]


def proof_body(source: str, name: str) -> str:
    signature = f"def {name}("
    if signature not in source:
        raise SystemExit(f"missing proof function: {name}")
    return source.split(signature, 1)[1].split("\ndef ", 1)[0].split(":\n", 1)[1]


def returned_expression(source: str, name: str) -> str:
    body = proof_body(source, name)
    if "return " not in body:
        raise SystemExit(f"proof function has no return expression: {name}")
    return compact(body.split("return ", 1)[1])


positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()
model_body = proof_body(positive_text, "model_join_fact")
if compact(model_body) != compact("ensure result == (left and right)\n    return left and right"):
    raise SystemExit("Boolean meet model must state and compute the conjunction of predecessor facts")
if compact(proof_body(positive_text, "flag_facts_merge_by_the_same_common_fact_rule")) != compact(
    "ensure result == (left and right)\n    return left and right"
):
    raise SystemExit("flag meet model must state and compute conjunction")

for theorem, expected in expected_returns.items():
    if returned_expression(positive_text, theorem) != compact(expected):
        raise SystemExit(f"join theorem changed: {theorem}")
if compact(proof_body(positive_text, "the_join_is_idempotent")) != compact(
    "ensure result == true\n    return model_join_fact(fact, fact) == fact"
):
    raise SystemExit("idempotence proof must apply the verified meet model to equal predecessor facts")
if compact(proof_body(positive_text, "stack_alignment_is_known_only_when_both_predecessors_agree")) != compact(
    "ensure result == (left_known and right_known and same_alignment)\n    return left_known and right_known and same_alignment"
):
    raise SystemExit("stack alignment join must require both known predecessor facts and equal alignment")
if compact(proof_body(positive_text, "equal_stack_deltas_are_preserved")) != compact(
    "requires left == right\n    ensure result == true\n    return (left if left == right else 0) == left"
):
    raise SystemExit("equal stack deltas must be retained by the join")
if compact(proof_body(positive_text, "unequal_stack_deltas_reset_to_zero")) != compact(
    "requires left != right\n    ensure result == true\n    return (left if left == right else 0) == 0"
):
    raise SystemExit("unequal stack deltas must be reset by the join")
for theorem, required in (
    ("both_predecessors_keep_a_fact", "requires left and right"),
    ("a_missing_left_fact_is_dropped", "requires not left"),
    ("a_missing_right_fact_is_dropped", "requires not right"),
    ("every_common_lower_fact_is_below_the_join", "requires (not lower or left) and (not lower or right)"),
    ("the_join_is_monotone", "requires (not first or larger_first) and (not second or larger_second)"),
    ("a_true_right_predecessor_reduces_the_join_to_left", "requires right"),
    ("a_true_left_predecessor_reduces_the_join_to_right", "requires left"),
    ("an_unknown_or_conflicting_alignment_is_dropped", "requires not left_known or not right_known or not same_alignment"),
    ("equal_stack_deltas_are_preserved", "requires left == right"),
    ("unequal_stack_deltas_reset_to_zero", "requires left != right"),
):
    if compact(required) not in compact(proof_body(positive_text, theorem)):
        raise SystemExit(f"join theorem lost its premise: {theorem}")
if compact(proof_body(negative_text, "one_sided_fact_survives_a_join")) != compact(
    "requires not left and right\n    ensure result == true\n    return left"
):
    raise SystemExit("negative one-sided predecessor control changed")

mask_source = MASKS.read_text()
register_masks = {
    name: int(value)
    for name, value in re.findall(r"(?m)^        const (R(?:AX|CX|DX|BX|SI|DI|BP|SP|[0-9]+)): i64 = ([0-9]+)$", mask_source)
}
if register_masks != EXPECTED_MASKS:
    raise SystemExit("flow-join proof requires the exact, distinct canonical 16-bit register fact domain")
width_policy = WIDTH_POLICY.read_text()
if compact(source_body(width_policy, "def address_register_width(register: sview) -> i64:")) != compact(expected_width_policy):
    raise SystemExit("provenance-width proof requires the canonical exact 32/64/unknown register partition")
for declaration in (
    "const ADDRESS_REGISTER_WIDTH_UNKNOWN: i64 = 0",
    "const ADDRESS_REGISTER_WIDTH_32: i64 = 32",
    "const ADDRESS_REGISTER_WIDTH_64: i64 = 64",
):
    if compact(declaration) not in compact(width_policy):
        raise SystemExit(f"provenance-width proof requires the exact width tag {declaration}")
register_bit_source = compact(source_body(mask_source, "def register_bit(register: sview) -> i64:"))
for alias_group, bit in (("\"rax\" | \"eax\" | \"ax\" | \"al\"", "RAX"), ("\"rcx\" | \"ecx\" | \"cx\" | \"cl\"", "RCX")):
    if f"{alias_group} -> result == {bit}" not in register_bit_source or f"{alias_group}: {bit}" not in register_bit_source:
        raise SystemExit(f"partial-register provenance proof requires canonical {bit} alias identity")
slot_map = compact(source_body(MODEL.read_text(), "def easm_provenance_slot(register: sview) -> i64:"))
if compact(slot_map) != compact(expected_slot_map):
    raise SystemExit("partial-register transfer proof requires the production alias-to-slot projection")
call_clobber_body = source_body(mask_source, "def call_clobber_mask() -> i64:")
expected_call_clobber_body = "ensure result == (RAX | RCX | RDX | RSI | RDI | R8 | R9 | R10 | R11)\nreturn RAX | RCX | RDX | RSI | RDI | R8 | R9 | R10 | R11"
if compact(call_clobber_body) != compact(expected_call_clobber_body):
    raise SystemExit("call provenance proof requires the production caller-saved register mask")
for helper, expression in (
    ("cpuid_write_mask", "RAX | RBX | RCX | RDX"),
    ("rdtsc_write_mask", "RAX | RDX"),
):
    body = source_body(mask_source, f"def {helper}() -> i64:")
    expected = f"ensure result == ({expression})\nreturn {expression}"
    if compact(body) != compact(expected):
        raise SystemExit(f"implicit-result provenance proof requires the exact {helper} register mask")
implicit_result_body = source_body(mask_source, "def implicit_result_write_mask(op: sview) -> i64:")
if compact(implicit_result_body) != compact(expected_implicit_result_body):
    raise SystemExit("defined-result mask must agree with the proved CPUID/RDTSC write sets and be empty otherwise")

model_source = MODEL.read_text()
propagate = source_body(
    model_source,
    "def easm_propagate_flow(target: i64, incoming: FlowState, entries: mutable darray[FlowState]&, meets: mutable darray[i64]&, counts: mutable darray[i64]&) -> bool:",
)
if compact(propagate) != compact(expected_propagate):
    raise SystemExit("flow propagation changed; recheck first-predecessor handling and common-fact meet placement")

provenance_propagate = source_body(
    model_source,
    "def easm_provenance_flow_propagate(target: i64, incoming: ProvenanceFlow, entries: mutable darray[ProvenanceFlow]&, counts: mutable darray[i64]&) -> bool:",
)
if compact(provenance_propagate) != compact(expected_provenance_propagate):
    raise SystemExit("provenance-flow propagation changed; recheck conflict ambiguity and first-predecessor handling")

empty_provenance = source_body(model_source, "def easm_empty_provenance_flow() -> ProvenanceFlow:")
if compact(empty_provenance) != compact(expected_empty_provenance):
    raise SystemExit("empty provenance state must keep 16 empty carrier slots and clear validity/ambiguity")
provenance_equal = source_body(model_source, "def easm_provenance_flow_equal(a: ProvenanceFlow, b: ProvenanceFlow) -> bool:")
if compact(provenance_equal) != compact(expected_provenance_equal):
    raise SystemExit("provenance equality must include validity, ambiguity, shape, and every carrier slot")
provenance_transfer = source_body(
    model_source,
    "def easm_provenance_flow_transfer(instruction: Instruction, incoming: ProvenanceFlow) -> ProvenanceFlow:",
)
xchg_transfer_prefix = provenance_transfer.split("return out if destination_slot < 0", 1)[0]
if compact(xchg_transfer_prefix) != compact(expected_xchg_transfer_prefix):
    raise SystemExit("provenance xchg transfer must snapshot then swap both carrier types and ambiguity bits")

if compact(proof_body(positive_text, "production_call_clears_clobbered_provenance_and_ambiguity")) != compact(expected_production_call):
    raise SystemExit("production call theorem must check every clobbered and preserved carrier and ambiguity slot")
if compact(proof_body(positive_text, "production_implicit_results_clear_written_provenance_and_ambiguity")) != compact(expected_implicit_results):
    raise SystemExit("production CPUID/RDTSC theorem must check all defined implicit result slots")

if compact(proof_body(positive_text, "production_full_width_move_copies_provenance")) != compact(expected_full_width_move):
    raise SystemExit("full-width move theorem must quantify over all carriers and ambiguity bits")
expected_partial_move = expected_full_width_move.replace('op: "movq"', 'op: "movl"').replace('text: "%rax, %rcx"', 'text: "%eax, %ecx"').replace(
    "out.types[1] == incoming.types[0]", 'out.types[1] == ""'
).replace(
    "out.ambiguous == ((incoming.ambiguous & (~EasmRegisterMasks::RCX)) | (EasmRegisterMasks::RCX if (incoming.ambiguous & EasmRegisterMasks::RAX) != 0 else 0))",
    "out.ambiguous == (incoming.ambiguous & (~EasmRegisterMasks::RCX))",
)
if compact(proof_body(positive_text, "production_partial_move_clears_destination_provenance")) != compact(expected_partial_move):
    raise SystemExit("partial move theorem must clear only the destination carrier and ambiguity")
if compact(proof_body(positive_text, "production_partial_exchange_clears_both_carriers")) != compact(expected_partial_exchange):
    raise SystemExit("partial exchange theorem must clear both affected aliases and preserve other slots")

flow_equal = source_body(model_source, "def easm_flow_equal(a: FlowState, b: FlowState) -> bool:")
expected_flow_equal = "return a.valid == b.valid and a.live == b.live and a.stack_delta == b.stack_delta and a.stack_mod16 == b.stack_mod16 and a.stack_known == b.stack_known and a.flags_live == b.flags_live"
if compact(flow_equal) != compact(expected_flow_equal):
    raise SystemExit("flow fixed-point equality must observe both merged fact fields")
for theorem, expected in (
    (
        "production_flow_equality_is_reflexive",
        "ensure result == true\nreturn Easm::easm_flow_equal(state, state)",
    ),
    (
        "production_flow_equality_is_symmetric",
        "ensure result == true\nreturn Easm::easm_flow_equal(left, right) == Easm::easm_flow_equal(right, left)",
    ),
    (
        "production_flow_equality_is_transitive",
        "requires Easm::easm_flow_equal(first, second)\nrequires Easm::easm_flow_equal(second, third)\nensure result == true\nreturn Easm::easm_flow_equal(first, third)",
    ),
    (
        "production_flow_equality_agrees_on_all_fields",
        "requires Easm::easm_flow_equal(left, right)\nensure result == true\nreturn ( left.valid == right.valid and left.live == right.live and left.stack_delta == right.stack_delta and left.stack_mod16 == right.stack_mod16 and left.stack_known == right.stack_known and left.flags_live == right.flags_live )",
    ),
):
    if compact(proof_body(positive_text, theorem)) != compact(expected):
        raise SystemExit(f"production flow-equality theorem changed: {theorem}")
if compact(proof_body(negative_text, "equal_flow_states_can_disagree_on_live_flags")) != compact(expected_flag_difference):
    raise SystemExit("flow-equality false control must differ only in live flags")
if compact(proof_body(positive_text, "any_target_into_an_empty_flow_table_is_rejected")) != compact(expected_empty_flow_table):
    raise SystemExit("empty flow-table proof must call the production bounds guard without indexing")
if compact(proof_body(positive_text, "a_second_predecessor_updates_the_production_meet")) != compact(expected_second_predecessor):
    raise SystemExit("second-predecessor proof must assert every field of the production flow meet")
if compact(proof_body(negative_text, "a_second_predecessor_can_keep_one_sided_live_flags")) != compact(expected_one_sided_flags):
    raise SystemExit("one-sided flags control must call the production merge with opposing concrete facts")
if compact(proof_body(positive_text, "a_first_valid_predecessor_initializes_the_production_entry")) != compact(expected_first_predecessor):
    raise SystemExit("first-predecessor theorem must bind incoming state installation and initial meet facts")
if compact(proof_body(negative_text, "a_first_valid_predecessor_can_leave_the_entry_invalid")) != compact(expected_invalid_entry_control):
    raise SystemExit("first-predecessor false control must challenge installation into an invalid slot")
if compact(proof_body(positive_text, "production_second_predecessor_merge_is_order_independent")) != compact(expected_order_independence):
    raise SystemExit("commutativity proof must run production propagation in both predecessor orders")
if compact(proof_body(negative_text, "reversing_two_valid_predecessors_can_change_the_merge")) != compact(expected_order_control):
    raise SystemExit("order-dependence false control must run the same concrete predecessors in reverse orders")
if compact(proof_body(positive_text, "production_three_predecessor_merge_is_associative")) != compact(expected_three_way_associativity):
    raise SystemExit("three-predecessor associativity proof must compare sequential and nested production merges")
if compact(proof_body(positive_text, "duplicate_production_predecessor_is_state_idempotent")) != compact(expected_duplicate_idempotence):
    raise SystemExit("duplicate-predecessor idempotence proof must check the production state and change result")
if compact(proof_body(positive_text, "production_provenance_join_marks_disagreement_ambiguous")) != compact(expected_provenance_join):
    raise SystemExit("provenance-flow theorem must specify the production carrier/ambiguity join")
if compact(proof_body(positive_text, "a_first_provenance_predecessor_installs_the_production_state")) != compact(expected_first_provenance):
    raise SystemExit("first provenance predecessor proof must check exact installation and count initialization")
if compact(proof_body(positive_text, "duplicate_provenance_predecessor_is_state_idempotent")) != compact(expected_duplicate_provenance):
    raise SystemExit("duplicate provenance theorem must check all slots, equality, and the change result")
if compact(proof_body(positive_text, "production_xchg_swaps_provenance_and_ambiguity")) != compact(expected_production_xchg):
    raise SystemExit("production xchg theorem must verify both carrier and ambiguity swaps through easm_provenance_flow_transfer")
if compact(proof_body(positive_text, "out_of_range_target_is_a_production_noop")) != compact(expected_out_of_range_noop):
    raise SystemExit("out-of-range target theorem must check every production flow table remains unchanged")
if compact(proof_body(positive_text, "production_merge_change_reports_meet_or_state_change")) != compact(expected_changed_contract):
    raise SystemExit("production changed-result theorem must include both meet and FlowState changes")
if compact(proof_body(negative_text, "different_grouping_can_change_a_three_predecessor_merge")) != compact(expected_three_way_control):
    raise SystemExit("three-predecessor false control must challenge the actual nested production merge")
if compact(proof_body(negative_text, "a_duplicate_predecessor_can_change_the_production_state")) != compact(expected_duplicate_control):
    raise SystemExit("duplicate-predecessor false control must contradict the production idempotence claim")
for theorem, bad_target in expected_bad_target_controls.items():
    expected_bad_target = f"""
state: Easm::FlowState = Easm::FlowState{{
    live: EasmRegisterMasks::RAX,
    stack_delta: 24,
    stack_mod16: 8,
    stack_known: true,
    flags_live: true,
    valid: true
}}
entries: mutable darray[Easm::FlowState] = [state]
meets: mutable darray[i64] = [state.live]
counts: mutable darray[i64] = [1]
changed: bool = Easm::easm_propagate_flow({bad_target}, state, entries, meets, counts)
after: Easm::FlowState = entries[0]
ensure result == true
return changed or not Easm::easm_flow_equal(after, state) or meets[0] != state.live or counts[0] != 1
"""
    if compact(proof_body(negative_text, theorem)) != compact(expected_bad_target):
        raise SystemExit(f"out-of-range false control does not exercise target {bad_target}")
if compact(proof_body(negative_text, "production_change_can_ignore_a_meet_only_change")) != compact(expected_meet_only_control):
    raise SystemExit("meet-only false control must show that changed is not just FlowState inequality")
if compact(proof_body(negative_text, "a_conflicting_provenance_join_can_remain_precise")) != compact(expected_conflicting_provenance_control):
    raise SystemExit("provenance false control must reject retaining a precise carrier across disagreement")
if compact(proof_body(negative_text, "a_first_provenance_predecessor_can_leave_the_empty_entry")) != compact(expected_first_provenance_control):
    raise SystemExit("first-provenance false control must challenge the production sentinel installation")
if compact(proof_body(negative_text, "a_duplicate_provenance_predecessor_can_change_the_state")) != compact(expected_duplicate_provenance_control):
    raise SystemExit("duplicate provenance false control must oppose production idempotence")
if compact(proof_body(negative_text, "production_xchg_can_keep_the_old_carriers_in_place")) != compact(expected_production_xchg_control):
    raise SystemExit("production xchg false control must challenge swapping the old carriers")
if compact(proof_body(negative_text, "production_call_can_keep_a_clobbered_carrier")) != compact(expected_production_call_control):
    raise SystemExit("production call false control must challenge clobbering the incoming RAX carrier")
if compact(proof_body(negative_text, "production_cpuid_can_keep_rax_provenance")) != compact(expected_cpuid_control):
    raise SystemExit("CPUID false control must challenge clearing its implicit RAX result")
if compact(proof_body(negative_text, "production_partial_move_can_copy_a_pointer_carrier")) != compact(expected_partial_move_control):
    raise SystemExit("partial move false control must challenge pointer copying from a 32-bit alias")
if compact(proof_body(negative_text, "production_partial_exchange_can_preserve_old_carriers")) != compact(expected_partial_exchange_control):
    raise SystemExit("partial exchange false control must challenge invalidation of both 32-bit aliases")
if 'include "../../src/backend/easm_model.elisa"' not in positive_text or \
        'include "./easm_flow_join.elisa"' not in negative_text:
    raise SystemExit("flow-equality theorems must include the production model and its bound control fixture")

provenance_source = PROVENANCE.read_text()
verify_merges = source_body(
    provenance_source,
    "def verify_control_flow_merges(fn: Function, issues: mutable darray[Issue]&) -> void:",
)
iteration_start = "for round_index in 0..<(count + 1)"
post_iteration = "for index in 0..<count |index, entries, meets, incoming_counts, fn, issues|:"
if iteration_start not in verify_merges or post_iteration not in verify_merges:
    raise SystemExit("control-flow verifier no longer has a bounded propagation loop and merge-consumer pass")
iteration = verify_merges.split(iteration_start, 1)[1].split(post_iteration, 1)[0]
if compact(iteration_start + iteration) != compact(expected_iteration):
    raise SystemExit("fixed-point traversal must propagate branch targets and fallthrough through the proved join before convergence")
if "continue if fn.instructions[index].op != \"label\" or incoming_counts[index] == 0" not in verify_merges:
    raise SystemExit("post-fixpoint liveness validation must inspect every reachable label block")
if compact(expected_missing_check) not in compact(verify_merges):
    raise SystemExit("merge validation must check demanded registers against the all-predecessor meet")

verify_function_source = VERIFY_FUNCTION.read_text()
function_compositions = source_body(
    verify_function_source,
    "def verify_function_compositions(fn: Function, fragments: darray[Function]&, issues: mutable darray[Issue]&):",
)
if compact(function_compositions).count("verify_control_flow_merges(fn, issues)") != 1:
    raise SystemExit("function verification must invoke the source-bound control-flow merge analysis exactly once")
module_compositions = source_body(
    verify_function_source,
    "def verify_module_compositions(module: Module, issues: mutable darray[Issue]&):",
)
if compact(module_compositions) != compact(expected_module_compositions):
    raise SystemExit("module verification must apply the merge checker to every function")
module_verify = source_body(
    verify_function_source,
    "def verify_module(module: Module) -> darray[Issue]:",
)
module_verify_positions = [
    compact(module_verify).find(compact(fragment))
    for fragment in (
        "verify_module_fragments(module, issues)",
        "verify_module_compositions(module, issues)",
        "return issues",
    )
]
if any(position < 0 for position in module_verify_positions) or module_verify_positions != sorted(module_verify_positions):
    raise SystemExit("module verification must reach the per-function control-flow merge check before returning issues")

actual_declarations = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", positive_text))
if actual_declarations != EXPECTED_DECLARATIONS:
    raise SystemExit("positive flow-join proof declarations changed")
negative_declarations = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", negative_text))
if negative_declarations != FALSE_CLAIMS:
    raise SystemExit("flow-join false-claim control changed")

source_closure = source_include_closure([POSITIVE, NEGATIVE])
if ARGS.source_only:
    print(json.dumps({
        "source_bound": True,
        "positive_theorems": len(EXPECTED_DECLARATIONS),
        "false_claim_controls": len(FALSE_CLAIMS),
        "source_closure_files": len(source_closure),
    }, sort_keys=True))
    raise SystemExit(0)

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("EASM flow-join proof requires a strict proof build")
stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"), PROVER / "ELISA_COMPILER_REV",
    stage1_product, stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
    *(HERE / name for name in ("easm_flow_production_expectations.py", "easm_flow_proof_expectations.py", "easm_flow_false_claim_expectations.py")),
    POSITIVE, NEGATIVE, MASKS, MODEL, MEMORY, WIDTH_POLICY, PROVENANCE, VERIFY_FUNCTION,
]
inputs.extend(source_include_closure([POSITIVE, NEGATIVE]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                            text=True, timeout=60)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


positive_code, positive = run(POSITIVE)
assert positive_code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "flow-join report changed across repeated runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert verified == EXPECTED_DECLARATIONS

negative_code, negative = run(NEGATIVE)
assert negative_code == 1 and negative["status"] == "failed"
assert negative["summary"]["unproven"] == len(FALSE_CLAIMS)
assert negative == run(NEGATIVE)[1], "flow-join false-claim report changed across repeated runs"
findings_by_name = {finding["name"]: finding for finding in negative["findings"]}
assert set(findings_by_name) == FALSE_CLAIMS
assert all(finding["kind"] == "ensure-unproven" and finding["status"] in {"unknown", "disproved"}
           for finding in findings_by_name.values())
assert not FALSE_CLAIMS & {row["name"] for row in negative["declaration_details"] if row.get("verified")}
one_sided_finding = findings_by_name["one_sided_fact_survives_a_join"]
assert one_sided_finding["status"] == "disproved"
assert one_sided_finding["counterexample_found"]
counterexample = one_sided_finding["counterexample"]
assert len(counterexample) == 2

def matches_boolean_input(condition: dict, name: str, value: bool) -> bool:
    return (
        condition.get("kind") == "binary"
        and condition.get("operator") == "=="
        and condition.get("left", {}).get("kind") == "ident"
        and condition.get("left", {}).get("name") == name
        and condition.get("right", {}).get("kind") == "bool"
        and condition.get("right", {}).get("value") is value
    )

assert matches_boolean_input(counterexample[0], "left", False)
assert matches_boolean_input(counterexample[1], "right", True), \
    "one-sided-fact control must expose left=false and right=true"
assert "one_sided_fact_survives_a_join" not in {
    row["name"] for row in negative["declaration_details"] if row.get("verified")
}
assert require_current_product(BIN, PROVER) == manifest, "proof-product provenance changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "register liveness, flag facts, stack alignment, and call-clobbered provenance at EASM control-flow joins",
    "positive_obligations": positive["summary"]["proven"],
    "false_claim_rejected_with_counterexample": "one_sided_fact_survives_a_join",
    "proof_binary_sha256": hashlib.sha256(BIN.read_bytes()).hexdigest(),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
