"""Admit the EASM control-flow meet proof against a strict Elisa-proof product."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


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

EXPECTED_DECLARATIONS = {
    "model_join_fact",
    "both_predecessors_keep_a_fact",
    "a_missing_left_fact_is_dropped",
    "a_missing_right_fact_is_dropped",
    "the_join_is_exactly_the_common_fact",
    "the_join_is_commutative",
    "a_true_right_predecessor_reduces_the_join_to_left",
    "a_true_left_predecessor_reduces_the_join_to_right",
    "the_join_is_associative",
    "the_join_is_idempotent",
    "a_join_is_below_its_left_predecessor",
    "a_join_is_below_its_right_predecessor",
    "every_common_lower_fact_is_below_the_join",
    "the_join_is_monotone",
    "flag_facts_merge_by_the_same_common_fact_rule",
    "stack_alignment_is_known_only_when_both_predecessors_agree",
    "an_unknown_or_conflicting_alignment_is_dropped",
    "equal_stack_deltas_are_preserved",
    "unequal_stack_deltas_reset_to_zero",
    "production_flow_equality_is_reflexive",
    "production_flow_equality_is_symmetric",
    "production_flow_equality_is_transitive",
    "production_flow_equality_agrees_on_all_fields",
    "any_target_into_an_empty_flow_table_is_rejected",
    "out_of_range_target_is_a_production_noop",
    "a_second_predecessor_updates_the_production_meet",
    "production_merge_change_reports_meet_or_state_change",
    "a_first_valid_predecessor_initializes_the_production_entry",
    "production_second_predecessor_merge_is_order_independent",
    "production_three_predecessor_merge_is_associative",
    "duplicate_production_predecessor_is_state_idempotent",
    "production_provenance_join_marks_disagreement_ambiguous",
    "a_first_provenance_predecessor_installs_the_production_state",
    "duplicate_provenance_predecessor_is_state_idempotent",
    "production_xchg_swaps_provenance_and_ambiguity",
    "production_call_clears_clobbered_provenance_and_ambiguity",
    "production_implicit_results_clear_written_provenance_and_ambiguity",
    "production_full_width_move_copies_provenance",
    "production_partial_move_clears_destination_provenance",
    "production_partial_exchange_clears_both_carriers",
}
FALSE_CLAIMS = {
    "one_sided_fact_survives_a_join",
    "equal_flow_states_can_disagree_on_live_flags",
    "a_second_predecessor_can_keep_one_sided_live_flags",
    "a_first_valid_predecessor_can_leave_the_entry_invalid",
    "reversing_two_valid_predecessors_can_change_the_merge",
    "different_grouping_can_change_a_three_predecessor_merge",
    "a_duplicate_predecessor_can_change_the_production_state",
    "a_negative_target_can_mutate_a_nonempty_flow_table",
    "a_target_equal_to_the_entry_count_can_mutate_the_flow_table",
    "production_change_can_ignore_a_meet_only_change",
    "a_conflicting_provenance_join_can_remain_precise",
    "a_first_provenance_predecessor_can_leave_the_empty_entry",
    "a_duplicate_provenance_predecessor_can_change_the_state",
    "production_xchg_can_keep_the_old_carriers_in_place",
    "production_call_can_keep_a_clobbered_carrier",
    "production_cpuid_can_keep_rax_provenance",
    "production_partial_move_can_copy_a_pointer_carrier",
    "production_partial_exchange_can_preserve_old_carriers",
}

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

expected_returns = {
    "both_predecessors_keep_a_fact": "left and right",
    "a_missing_left_fact_is_dropped": "not (left and right)",
    "a_missing_right_fact_is_dropped": "not (left and right)",
    "the_join_is_exactly_the_common_fact": "(left and right) == (not (not left or not right))",
    "the_join_is_commutative": "(left and right) == (right and left)",
    "a_true_right_predecessor_reduces_the_join_to_left": "(not left or (left and right)) and (not (left and right) or left)",
    "a_true_left_predecessor_reduces_the_join_to_right": "(not right or (left and right)) and (not (left and right) or right)",
    "the_join_is_associative": "((first and second) and third) == (first and (second and third))",
    "a_join_is_below_its_left_predecessor": "not (left and right) or left",
    "a_join_is_below_its_right_predecessor": "not (left and right) or right",
    "every_common_lower_fact_is_below_the_join": "not lower or (left and right)",
    "the_join_is_monotone": "not (first and second) or (larger_first and larger_second)",
    "an_unknown_or_conflicting_alignment_is_dropped": "not (left_known and right_known and same_alignment)",
}
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
expected_width_policy = """ensure when register:
        "rax" | "rcx" | "rdx" | "rbx" | "rsi" | "rdi" | "rbp" | "rsp" | "r8" | "r9" | "r10" | "r11" | "r12" | "r13" | "r14" | "r15" -> result == ADDRESS_REGISTER_WIDTH_64
        "eax" | "ecx" | "edx" | "ebx" | "esi" | "edi" | "ebp" | "esp" | "r8d" | "r9d" | "r10d" | "r11d" | "r12d" | "r13d" | "r14d" | "r15d" -> result == ADDRESS_REGISTER_WIDTH_32
        _ -> result == ADDRESS_REGISTER_WIDTH_UNKNOWN
    return match register:
        "rax" | "rcx" | "rdx" | "rbx" | "rsi" | "rdi" | "rbp" | "rsp" | "r8" | "r9" | "r10" | "r11" | "r12" | "r13" | "r14" | "r15": ADDRESS_REGISTER_WIDTH_64
        "eax" | "ecx" | "edx" | "ebx" | "esi" | "edi" | "ebp" | "esp" | "r8d" | "r9d" | "r10d" | "r11d" | "r12d" | "r13d" | "r14d" | "r15d": ADDRESS_REGISTER_WIDTH_32
        _: ADDRESS_REGISTER_WIDTH_UNKNOWN"""
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
expected_slot_map = """bit: i64 = easm_register_bit(register)
    return match bit:
        1: 0
        2: 1
        4: 2
        8: 3
        16: 4
        32: 5
        64: 6
        128: 7
        256: 8
        512: 9
        1024: 10
        2048: 11
        4096: 12
        8192: 13
        16384: 14
        32768: 15
        _: -1"""
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
expected_implicit_result_body = """
ensure op == "cpuid" implies result == cpuid_write_mask()
ensure op == "rdtsc" implies result == rdtsc_write_mask()
ensure op != "cpuid" and op != "rdtsc" implies result == 0
if op == "cpuid":
    return cpuid_write_mask()
if op == "rdtsc":
    return rdtsc_write_mask()
return 0
"""
if compact(implicit_result_body) != compact(expected_implicit_result_body):
    raise SystemExit("defined-result mask must agree with the proved CPUID/RDTSC write sets and be empty otherwise")

model_source = MODEL.read_text()
propagate = source_body(
    model_source,
    "def easm_propagate_flow(target: i64, incoming: FlowState, entries: mutable darray[FlowState]&, meets: mutable darray[i64]&, counts: mutable darray[i64]&) -> bool:",
)
expected_propagate = """
if target < 0 or target >= entries.count.i64():
    return false
changed: mutable bool = false
if counts[target.usize()] == 0:
    meets[target.usize()] <- incoming.live
    counts[target.usize()] <- 1
else:
    new_meet: i64 = meets[target.usize()] & incoming.live
    changed <- true if new_meet != meets[target.usize()]
    meets[target.usize()] <- new_meet
    counts[target.usize()] <- counts[target.usize()] + 1
if not entries[target.usize()].valid:
    entries[target.usize()] <- incoming
    return true
current: FlowState = entries[target.usize()]
joined: FlowState = current
joined.live <- current.live & incoming.live
joined.flags_live <- current.flags_live and incoming.flags_live
joined.stack_known <- current.stack_known and incoming.stack_known and current.stack_mod16 == incoming.stack_mod16
joined.stack_mod16 <- current.stack_mod16 if joined.stack_known else 0
joined.stack_delta <- current.stack_delta if current.stack_delta == incoming.stack_delta else 0
changed <- true if not easm_flow_equal(current, joined)
entries[target.usize()] <- joined
return changed
"""
if compact(propagate) != compact(expected_propagate):
    raise SystemExit("flow propagation changed; recheck first-predecessor handling and common-fact meet placement")

provenance_propagate = source_body(
    model_source,
    "def easm_provenance_flow_propagate(target: i64, incoming: ProvenanceFlow, entries: mutable darray[ProvenanceFlow]&, counts: mutable darray[i64]&) -> bool:",
)
expected_provenance_propagate = """
false return if target < 0 or target >= entries.count.i64()
if not entries[target.usize()].valid:
    entries[target.usize()] <- incoming
    counts[target.usize()] <- 1
    return true
current: ProvenanceFlow = entries[target.usize()]
joined: ProvenanceFlow = current
joined.valid <- true
for index in 0..<joined.types.count |index, joined, current, incoming|:
    if current.types[index] != incoming.types[index]:
        joined.ambiguous <- joined.ambiguous | (1 << index.i64())
        joined.types[index] <- ""
    if (current.ambiguous & (1 << index.i64())) != 0 or (incoming.ambiguous & (1 << index.i64())) != 0:
        joined.ambiguous <- joined.ambiguous | (1 << index.i64())
counts[target.usize()] <- counts[target.usize()] + 1
changed: bool = not easm_provenance_flow_equal(current, joined)
entries[target.usize()] <- joined
return changed
"""
if compact(provenance_propagate) != compact(expected_provenance_propagate):
    raise SystemExit("provenance-flow propagation changed; recheck conflict ambiguity and first-predecessor handling")

empty_provenance = source_body(model_source, "def easm_empty_provenance_flow() -> ProvenanceFlow:")
expected_empty_provenance = """
types: mutable darray[sview] = []
for _ in 0..<16 |types|:
    types.push("")
return ProvenanceFlow{types: types, ambiguous: 0, valid: false}
"""
if compact(empty_provenance) != compact(expected_empty_provenance):
    raise SystemExit("empty provenance state must keep 16 empty carrier slots and clear validity/ambiguity")
provenance_equal = source_body(model_source, "def easm_provenance_flow_equal(a: ProvenanceFlow, b: ProvenanceFlow) -> bool:")
expected_provenance_equal = """
false return if a.valid != b.valid or a.ambiguous != b.ambiguous or a.types.count != b.types.count
for index in 0..<a.types.count |a, b|:
    false return if a.types[index] != b.types[index]
return true
"""
if compact(provenance_equal) != compact(expected_provenance_equal):
    raise SystemExit("provenance equality must include validity, ambiguity, shape, and every carrier slot")
provenance_transfer = source_body(
    model_source,
    "def easm_provenance_flow_transfer(instruction: Instruction, incoming: ProvenanceFlow) -> ProvenanceFlow:",
)
xchg_transfer_prefix = provenance_transfer.split("out return if destination_slot < 0", 1)[0]
expected_xchg_transfer_prefix = """
out: mutable ProvenanceFlow = incoming
implicit_clobbers: mutable i64 = EasmRegisterMasks::implicit_result_write_mask(instruction.op)
if easm_starts(instruction.op, "call"):
    implicit_clobbers <- EasmRegisterMasks::call_clobber_mask()
if implicit_clobbers != 0:
    for slot in 0..<out.types.count |slot, out, implicit_clobbers|:
        bit: i64 = 1 << slot.i64()
        if (implicit_clobbers & bit) != 0:
            out.types[slot] <- ""
    out.ambiguous <- out.ambiguous & (~implicit_clobbers)
    return out
out return if easm_starts(instruction.op, "cmp") or easm_starts(instruction.op, "test") or easm_starts(instruction.op, "push") or easm_starts(instruction.op, "jmp") or easm_starts(instruction.op, "ret")
destination_operand: sview = easm_substitute_operand(easm_last_operand(instruction.text), instruction)
source: sview = easm_substitute_operand(easm_first_operand(instruction.text), instruction)
destination: sview = easm_register_operand(destination_operand)
source_register: sview = easm_register_operand(source)
destination_slot: i64 = easm_provenance_slot(destination)
source_slot: i64 = easm_provenance_slot(source_register)
op: sview = instruction.op
destination_width: i64 = EasmAddressWidthPolicy::address_register_width(destination)
source_width: i64 = EasmAddressWidthPolicy::address_register_width(source_register)
if easm_starts(instruction.op, "xchg"):
    full_width_exchange: bool = destination_width == EasmAddressWidthPolicy::ADDRESS_REGISTER_WIDTH_64 and source_width == EasmAddressWidthPolicy::ADDRESS_REGISTER_WIDTH_64 and (op == "xchgq" or op == "xchg")
    if full_width_exchange and source_slot >= 0 and destination_slot >= 0:
        source_type: sview = out.types[source_slot.usize()]
        destination_type: sview = out.types[destination_slot.usize()]
        source_ambiguous: bool = (out.ambiguous & (1 << source_slot)) != 0
        destination_ambiguous: bool = (out.ambiguous & (1 << destination_slot)) != 0
        source_mask: i64 = 1 << source_slot
        destination_mask: i64 = 1 << destination_slot
        out.types[source_slot.usize()] <- destination_type
        out.types[destination_slot.usize()] <- source_type
        out.ambiguous <- out.ambiguous & (~(source_mask | destination_mask))
        out.ambiguous <- out.ambiguous | source_mask if destination_ambiguous
        out.ambiguous <- out.ambiguous | destination_mask if source_ambiguous
    else:
        if source_slot >= 0:
            out.types[source_slot.usize()] <- ""
            out.ambiguous <- out.ambiguous & (~(1 << source_slot))
        if destination_slot >= 0:
            out.types[destination_slot.usize()] <- ""
            out.ambiguous <- out.ambiguous & (~(1 << destination_slot))
    return out
"""
if compact(xchg_transfer_prefix) != compact(expected_xchg_transfer_prefix):
    raise SystemExit("provenance xchg transfer must snapshot then swap both carrier types and ambiguity bits")

expected_production_call = """
requires incoming.valid == true and incoming.types.count == 16
ensure result == true
instruction: Easm::Instruction = Easm::Instruction{
    op: "callq",
    text: "target",
    line: 1,
    pseudo: false,
    substitution_count: 0,
    substitution0: Easm::Substitution{from: "", replacement: ""},
    substitution1: Easm::Substitution{from: "", replacement: ""},
    substitution2: Easm::Substitution{from: "", replacement: ""},
    substitution3: Easm::Substitution{from: "", replacement: ""}
}
call_clobbers: i64 = EasmRegisterMasks::call_clobber_mask()
out: Easm::ProvenanceFlow = Easm::easm_provenance_flow_transfer(instruction, incoming)
return (
    out.valid == incoming.valid and
    out.types.count == incoming.types.count and
    out.ambiguous == (incoming.ambiguous & (~call_clobbers)) and
    (forall slot in 0..<16:
        (((call_clobbers & (1 << slot.i64())) != 0) implies
            out.types[slot] == "" and (out.ambiguous & (1 << slot.i64())) == 0) and
        (((call_clobbers & (1 << slot.i64())) == 0) implies
            out.types[slot] == incoming.types[slot] and
                (out.ambiguous & (1 << slot.i64())) == (incoming.ambiguous & (1 << slot.i64())))
    )
)
"""
if compact(proof_body(positive_text, "production_call_clears_clobbered_provenance_and_ambiguity")) != compact(expected_production_call):
    raise SystemExit("production call theorem must check every clobbered and preserved carrier and ambiguity slot")
expected_implicit_results = """
requires incoming.valid == true and incoming.types.count == 16
requires op == "cpuid" or op == "rdtsc"
ensure result == true
instruction: Easm::Instruction = Easm::Instruction{
    op: op,
    text: "",
    line: 1,
    pseudo: false,
    substitution_count: 0,
    substitution0: Easm::Substitution{from: "", replacement: ""},
    substitution1: Easm::Substitution{from: "", replacement: ""},
    substitution2: Easm::Substitution{from: "", replacement: ""},
    substitution3: Easm::Substitution{from: "", replacement: ""}
}
implicit_writes: i64 = EasmRegisterMasks::cpuid_write_mask() if op == "cpuid" else EasmRegisterMasks::rdtsc_write_mask()
out: Easm::ProvenanceFlow = Easm::easm_provenance_flow_transfer(instruction, incoming)
return (
    out.valid == incoming.valid and
    out.types.count == incoming.types.count and
    out.ambiguous == (incoming.ambiguous & (~implicit_writes)) and
    (forall slot in 0..<16:
        (((implicit_writes & (1 << slot.i64())) != 0) implies
            out.types[slot] == "" and (out.ambiguous & (1 << slot.i64())) == 0) and
        (((implicit_writes & (1 << slot.i64())) == 0) implies
            out.types[slot] == incoming.types[slot] and
                (out.ambiguous & (1 << slot.i64())) == (incoming.ambiguous & (1 << slot.i64())))
    )
)
"""
if compact(proof_body(positive_text, "production_implicit_results_clear_written_provenance_and_ambiguity")) != compact(expected_implicit_results):
    raise SystemExit("production CPUID/RDTSC theorem must check all defined implicit result slots")

expected_full_width_move = """
requires incoming.valid == true and incoming.types.count == 16
ensure result == true
instruction: Easm::Instruction = Easm::Instruction{
    op: "movq",
    text: "%rax, %rcx",
    line: 1,
    pseudo: false,
    substitution_count: 0,
    substitution0: Easm::Substitution{from: "", replacement: ""},
    substitution1: Easm::Substitution{from: "", replacement: ""},
    substitution2: Easm::Substitution{from: "", replacement: ""},
    substitution3: Easm::Substitution{from: "", replacement: ""}
}
out: Easm::ProvenanceFlow = Easm::easm_provenance_flow_transfer(instruction, incoming)
return (
    out.valid == incoming.valid and
    out.types.count == incoming.types.count and
    out.types[1] == incoming.types[0] and
    out.ambiguous == ((incoming.ambiguous & (~EasmRegisterMasks::RCX)) | (EasmRegisterMasks::RCX if (incoming.ambiguous & EasmRegisterMasks::RAX) != 0 else 0)) and
    (forall slot in 0..<16:
        (slot == 1 or out.types[slot] == incoming.types[slot]) and
        (slot == 1 or (out.ambiguous & (1 << slot.i64())) == (incoming.ambiguous & (1 << slot.i64())))
    )
)
"""
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
expected_partial_exchange = """
requires incoming.valid == true and incoming.types.count == 16
ensure result == true
instruction: Easm::Instruction = Easm::Instruction{
    op: "xchgl",
    text: "%eax, %ecx",
    line: 1,
    pseudo: false,
    substitution_count: 0,
    substitution0: Easm::Substitution{from: "", replacement: ""},
    substitution1: Easm::Substitution{from: "", replacement: ""},
    substitution2: Easm::Substitution{from: "", replacement: ""},
    substitution3: Easm::Substitution{from: "", replacement: ""}
}
out: Easm::ProvenanceFlow = Easm::easm_provenance_flow_transfer(instruction, incoming)
cleared: i64 = EasmRegisterMasks::RAX | EasmRegisterMasks::RCX
return (
    out.valid == incoming.valid and
    out.types.count == incoming.types.count and
    out.types[0] == "" and out.types[1] == "" and
    out.ambiguous == (incoming.ambiguous & (~cleared)) and
    (forall slot in 2..<16:
        out.types[slot] == incoming.types[slot] and
        (out.ambiguous & (1 << slot.i64())) == (incoming.ambiguous & (1 << slot.i64()))
    )
)
"""
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
expected_flag_difference = """
left: Easm::FlowState = Easm::FlowState{
    live: 0,
    stack_delta: 0,
    stack_mod16: 8,
    stack_known: true,
    flags_live: false,
    valid: true
}
right: Easm::FlowState = Easm::FlowState{
    live: 0,
    stack_delta: 0,
    stack_mod16: 8,
    stack_known: true,
    flags_live: true,
    valid: true
}
ensure result == true
return Easm::easm_flow_equal(left, right)
"""
if compact(proof_body(negative_text, "equal_flow_states_can_disagree_on_live_flags")) != compact(expected_flag_difference):
    raise SystemExit("flow-equality false control must differ only in live flags")
expected_empty_flow_table = """
ensure result == true
entries: mutable darray[Easm::FlowState] = []
meets: mutable darray[i64] = []
counts: mutable darray[i64] = []
changed: bool = Easm::easm_propagate_flow(target, incoming, entries, meets, counts)
return (
    not changed and
    entries.count == 0 and
    meets.count == 0 and
    counts.count == 0
)
"""
if compact(proof_body(positive_text, "any_target_into_an_empty_flow_table_is_rejected")) != compact(expected_empty_flow_table):
    raise SystemExit("empty flow-table proof must call the production bounds guard without indexing")
expected_second_predecessor = """
requires current.valid == true and incoming.valid == true
ensure result == true
entries: mutable darray[Easm::FlowState] = [current]
meets: mutable darray[i64] = [current.live]
counts: mutable darray[i64] = [1]
changed: bool = Easm::easm_propagate_flow(0, incoming, entries, meets, counts)
joined: Easm::FlowState = entries[0]
return (
    changed == (not Easm::easm_flow_equal(current, joined)) and
    counts[0] == 2 and
    meets[0] == (current.live & incoming.live) and
    joined.valid == true and
    joined.live == (current.live & incoming.live) and
    joined.flags_live == (current.flags_live and incoming.flags_live) and
    joined.stack_known == (current.stack_known and incoming.stack_known and current.stack_mod16 == incoming.stack_mod16) and
    joined.stack_mod16 == (current.stack_mod16 if joined.stack_known else 0) and
    joined.stack_delta == (current.stack_delta if current.stack_delta == incoming.stack_delta else 0)
)
"""
if compact(proof_body(positive_text, "a_second_predecessor_updates_the_production_meet")) != compact(expected_second_predecessor):
    raise SystemExit("second-predecessor proof must assert every field of the production flow meet")
expected_one_sided_flags = """
requires current_flags and not incoming_flags
ensure result == true
current: Easm::FlowState = Easm::FlowState{
    live: 0,
    stack_delta: 0,
    stack_mod16: 8,
    stack_known: true,
    flags_live: current_flags,
    valid: true
}
incoming: Easm::FlowState = Easm::FlowState{
    live: 0,
    stack_delta: 0,
    stack_mod16: 8,
    stack_known: true,
    flags_live: incoming_flags,
    valid: true
}
entries: mutable darray[Easm::FlowState] = [current]
meets: mutable darray[i64] = [current.live]
counts: mutable darray[i64] = [1]
changed: bool = Easm::easm_propagate_flow(0, incoming, entries, meets, counts)
return changed and entries[0].flags_live
"""
if compact(proof_body(negative_text, "a_second_predecessor_can_keep_one_sided_live_flags")) != compact(expected_one_sided_flags):
    raise SystemExit("one-sided flags control must call the production merge with opposing concrete facts")
expected_first_predecessor = """
requires incoming.valid == true
ensure result == true
invalid: Easm::FlowState = Easm::FlowState{
    live: 0,
    stack_delta: 0,
    stack_mod16: 0,
    stack_known: false,
    flags_live: false,
    valid: false
}
entries: mutable darray[Easm::FlowState] = [invalid]
meets: mutable darray[i64] = [-1]
counts: mutable darray[i64] = [0]
changed: bool = Easm::easm_propagate_flow(0, incoming, entries, meets, counts)
installed: Easm::FlowState = entries[0]
return (
    changed and
    counts[0] == 1 and
    meets[0] == incoming.live and
    Easm::easm_flow_equal(installed, incoming)
)
"""
if compact(proof_body(positive_text, "a_first_valid_predecessor_initializes_the_production_entry")) != compact(expected_first_predecessor):
    raise SystemExit("first-predecessor theorem must bind incoming state installation and initial meet facts")
expected_invalid_entry_control = """
invalid: Easm::FlowState = Easm::FlowState{
    live: 0,
    stack_delta: 0,
    stack_mod16: 0,
    stack_known: false,
    flags_live: false,
    valid: false
}
incoming: Easm::FlowState = Easm::FlowState{
    live: EasmRegisterMasks::RAX,
    stack_delta: 24,
    stack_mod16: 0,
    stack_known: true,
    flags_live: true,
    valid: true
}
entries: mutable darray[Easm::FlowState] = [invalid]
meets: mutable darray[i64] = [-1]
counts: mutable darray[i64] = [0]
changed: bool = Easm::easm_propagate_flow(0, incoming, entries, meets, counts)
ensure result == true
return changed and not entries[0].valid
"""
if compact(proof_body(negative_text, "a_first_valid_predecessor_can_leave_the_entry_invalid")) != compact(expected_invalid_entry_control):
    raise SystemExit("first-predecessor false control must challenge installation into an invalid slot")
expected_order_independence = """
requires first.valid == true and second.valid == true
ensure result == true
invalid: Easm::FlowState = Easm::FlowState{
    live: 0,
    stack_delta: 0,
    stack_mod16: 0,
    stack_known: false,
    flags_live: false,
    valid: false
}
left_entries: mutable darray[Easm::FlowState] = [invalid]
left_meets: mutable darray[i64] = [0]
left_counts: mutable darray[i64] = [0]
right_entries: mutable darray[Easm::FlowState] = [invalid]
right_meets: mutable darray[i64] = [0]
right_counts: mutable darray[i64] = [0]
first_left_change: bool = Easm::easm_propagate_flow(0, first, left_entries, left_meets, left_counts)
second_left_change: bool = Easm::easm_propagate_flow(0, second, left_entries, left_meets, left_counts)
first_right_change: bool = Easm::easm_propagate_flow(0, second, right_entries, right_meets, right_counts)
second_right_change: bool = Easm::easm_propagate_flow(0, first, right_entries, right_meets, right_counts)
left: Easm::FlowState = left_entries[0]
right: Easm::FlowState = right_entries[0]
return (
    first_left_change and
    first_right_change and
    second_left_change == (not Easm::easm_flow_equal(first, left)) and
    second_right_change == (not Easm::easm_flow_equal(second, right)) and
    left_counts[0] == 2 and right_counts[0] == 2 and
    left_meets[0] == (first.live & second.live) and
    right_meets[0] == (second.live & first.live) and
    Easm::easm_flow_equal(left, right)
)
"""
if compact(proof_body(positive_text, "production_second_predecessor_merge_is_order_independent")) != compact(expected_order_independence):
    raise SystemExit("commutativity proof must run production propagation in both predecessor orders")
expected_order_control = """
invalid: Easm::FlowState = Easm::FlowState{
    live: 0,
    stack_delta: 0,
    stack_mod16: 0,
    stack_known: false,
    flags_live: false,
    valid: false
}
first: Easm::FlowState = Easm::FlowState{
    live: EasmRegisterMasks::RAX,
    stack_delta: 8,
    stack_mod16: 0,
    stack_known: true,
    flags_live: true,
    valid: true
}
second: Easm::FlowState = Easm::FlowState{
    live: EasmRegisterMasks::RCX,
    stack_delta: 16,
    stack_mod16: 8,
    stack_known: true,
    flags_live: false,
    valid: true
}
left_entries: mutable darray[Easm::FlowState] = [invalid]
left_meets: mutable darray[i64] = [0]
left_counts: mutable darray[i64] = [0]
right_entries: mutable darray[Easm::FlowState] = [invalid]
right_meets: mutable darray[i64] = [0]
right_counts: mutable darray[i64] = [0]
Easm::easm_propagate_flow(0, first, left_entries, left_meets, left_counts)
Easm::easm_propagate_flow(0, second, left_entries, left_meets, left_counts)
Easm::easm_propagate_flow(0, second, right_entries, right_meets, right_counts)
Easm::easm_propagate_flow(0, first, right_entries, right_meets, right_counts)
left: Easm::FlowState = left_entries[0]
right: Easm::FlowState = right_entries[0]
ensure result == true
return not Easm::easm_flow_equal(left, right)
"""
if compact(proof_body(negative_text, "reversing_two_valid_predecessors_can_change_the_merge")) != compact(expected_order_control):
    raise SystemExit("order-dependence false control must run the same concrete predecessors in reverse orders")
expected_three_way_associativity = """
requires first.valid == true and second.valid == true and third.valid == true
ensure result == true
invalid: Easm::FlowState = Easm::FlowState{
    live: 0,
    stack_delta: 0,
    stack_mod16: 0,
    stack_known: false,
    flags_live: false,
    valid: false
}
left_entries: mutable darray[Easm::FlowState] = [invalid]
left_meets: mutable darray[i64] = [0]
left_counts: mutable darray[i64] = [0]
Easm::easm_propagate_flow(0, first, left_entries, left_meets, left_counts)
Easm::easm_propagate_flow(0, second, left_entries, left_meets, left_counts)
Easm::easm_propagate_flow(0, third, left_entries, left_meets, left_counts)
bc_entries: mutable darray[Easm::FlowState] = [invalid]
bc_meets: mutable darray[i64] = [0]
bc_counts: mutable darray[i64] = [0]
Easm::easm_propagate_flow(0, second, bc_entries, bc_meets, bc_counts)
Easm::easm_propagate_flow(0, third, bc_entries, bc_meets, bc_counts)
bc: Easm::FlowState = bc_entries[0]
right_entries: mutable darray[Easm::FlowState] = [first]
right_meets: mutable darray[i64] = [first.live]
right_counts: mutable darray[i64] = [1]
Easm::easm_propagate_flow(0, bc, right_entries, right_meets, right_counts)
left: Easm::FlowState = left_entries[0]
right: Easm::FlowState = right_entries[0]
return (
    left_counts[0] == 3 and
    bc_counts[0] == 2 and
    right_counts[0] == 2 and
    left_meets[0] == ((first.live & second.live) & third.live) and
    right_meets[0] == (first.live & bc.live) and
    left.valid == true and
    left.live == ((first.live & second.live) & third.live) and
    left.flags_live == ((first.flags_live and second.flags_live) and third.flags_live) and
    left.stack_known == (first.stack_known and second.stack_known and third.stack_known and first.stack_mod16 == second.stack_mod16 and second.stack_mod16 == third.stack_mod16) and
    left.stack_mod16 == (first.stack_mod16 if left.stack_known else 0) and
    left.stack_delta == (first.stack_delta if first.stack_delta == second.stack_delta and second.stack_delta == third.stack_delta else 0) and
    Easm::easm_flow_equal(left, right)
)
"""
if compact(proof_body(positive_text, "production_three_predecessor_merge_is_associative")) != compact(expected_three_way_associativity):
    raise SystemExit("three-predecessor associativity proof must compare sequential and nested production merges")
expected_duplicate_idempotence = """
requires incoming.valid == true
requires incoming.stack_known or incoming.stack_mod16 == 0
ensure result == true
entries: mutable darray[Easm::FlowState] = [incoming]
meets: mutable darray[i64] = [incoming.live]
counts: mutable darray[i64] = [1]
changed: bool = Easm::easm_propagate_flow(0, incoming, entries, meets, counts)
after: Easm::FlowState = entries[0]
return (
    not changed and
    counts[0] == 2 and
    meets[0] == incoming.live and
    Easm::easm_flow_equal(after, incoming)
)
"""
if compact(proof_body(positive_text, "duplicate_production_predecessor_is_state_idempotent")) != compact(expected_duplicate_idempotence):
    raise SystemExit("duplicate-predecessor idempotence proof must check the production state and change result")
expected_provenance_join = """
requires slot < 16
ensure result == true
left_types: mutable darray[sview] = []
right_types: mutable darray[sview] = []
for index in 0..<16 |index, left_types, right_types|:
    left_types.push(left_type if index == slot else "")
    right_types.push(right_type if index == slot else "")
slot_mask: i64 = 1 << slot.i64()
left: Easm::ProvenanceFlow = Easm::ProvenanceFlow{
    types: left_types,
    ambiguous: slot_mask if left_ambiguous else 0,
    valid: true
}
right: Easm::ProvenanceFlow = Easm::ProvenanceFlow{
    types: right_types,
    ambiguous: slot_mask if right_ambiguous else 0,
    valid: true
}
entries: mutable darray[Easm::ProvenanceFlow] = [left]
counts: mutable darray[i64] = [1]
changed: bool = Easm::easm_provenance_flow_propagate(0, right, entries, counts)
joined: Easm::ProvenanceFlow = entries[0]
expected_type: sview = left_type if left_type == right_type else ""
expected_ambiguous: bool = left_ambiguous or right_ambiguous or left_type != right_type
return (
    joined.valid == true and
    joined.types.count == 16 and
    joined.types[slot] == expected_type and
    joined.ambiguous == (slot_mask if expected_ambiguous else 0) and
    counts[0] == 2 and
    changed == (not Easm::easm_provenance_flow_equal(left, joined))
)
"""
if compact(proof_body(positive_text, "production_provenance_join_marks_disagreement_ambiguous")) != compact(expected_provenance_join):
    raise SystemExit("provenance-flow theorem must specify the production carrier/ambiguity join")
expected_first_provenance = """
requires incoming.valid == true and incoming.types.count == 16
ensure result == true
empty: Easm::ProvenanceFlow = Easm::easm_empty_provenance_flow()
entries: mutable darray[Easm::ProvenanceFlow] = [empty]
counts: mutable darray[i64] = [0]
changed: bool = Easm::easm_provenance_flow_propagate(0, incoming, entries, counts)
installed: Easm::ProvenanceFlow = entries[0]
return (
    changed and
    counts[0] == 1 and
    entries.count == 1 and
    Easm::easm_provenance_flow_equal(installed, incoming)
)
"""
if compact(proof_body(positive_text, "a_first_provenance_predecessor_installs_the_production_state")) != compact(expected_first_provenance):
    raise SystemExit("first provenance predecessor proof must check exact installation and count initialization")
expected_duplicate_provenance = """
requires incoming.valid == true and incoming.types.count == 16
ensure result == true
entries: mutable darray[Easm::ProvenanceFlow] = [incoming]
counts: mutable darray[i64] = [1]
changed: bool = Easm::easm_provenance_flow_propagate(0, incoming, entries, counts)
after: Easm::ProvenanceFlow = entries[0]
return (
    not changed and
    counts[0] == 2 and
    Easm::easm_provenance_flow_equal(after, incoming)
)
"""
if compact(proof_body(positive_text, "duplicate_provenance_predecessor_is_state_idempotent")) != compact(expected_duplicate_provenance):
    raise SystemExit("duplicate provenance theorem must check all slots, equality, and the change result")
expected_production_xchg = """
ensure result == true
incoming_types: mutable darray[sview] = []
for _ in 0..<16 |incoming_types|:
    incoming_types.push("")
incoming_types[0] <- source_type
incoming_types[1] <- destination_type
source_mask: i64 = 1
destination_mask: i64 = 2
incoming: Easm::ProvenanceFlow = Easm::ProvenanceFlow{
    types: incoming_types,
    ambiguous: (source_mask if source_ambiguous else 0) | (destination_mask if destination_ambiguous else 0),
    valid: true
}
instruction: Easm::Instruction = Easm::Instruction{
    op: "xchgq",
    text: "%rax, %rcx",
    line: 1,
    pseudo: false,
    substitution_count: 0,
    substitution0: Easm::Substitution{from: "", replacement: ""},
    substitution1: Easm::Substitution{from: "", replacement: ""},
    substitution2: Easm::Substitution{from: "", replacement: ""},
    substitution3: Easm::Substitution{from: "", replacement: ""}
}
out: Easm::ProvenanceFlow = Easm::easm_provenance_flow_transfer(instruction, incoming)
return (
    out.valid == true and
    out.types.count == 16 and
    out.types[0] == destination_type and
    out.types[1] == source_type and
    out.ambiguous == ((source_mask if destination_ambiguous else 0) | (destination_mask if source_ambiguous else 0)) and
    (forall untouched in 2..<16: out.types[untouched] == "" and (out.ambiguous & (1 << untouched.i64())) == 0)
)
"""
if compact(proof_body(positive_text, "production_xchg_swaps_provenance_and_ambiguity")) != compact(expected_production_xchg):
    raise SystemExit("production xchg theorem must verify both carrier and ambiguity swaps through easm_provenance_flow_transfer")
expected_out_of_range_noop = """
requires target < 0 or target >= 1
ensure result == true
entries: mutable darray[Easm::FlowState] = [state]
meets: mutable darray[i64] = [prior_meet]
counts: mutable darray[i64] = [prior_count]
changed: bool = Easm::easm_propagate_flow(target, state, entries, meets, counts)
after: Easm::FlowState = entries[0]
return (
    not changed and
    entries.count == 1 and meets.count == 1 and counts.count == 1 and
    Easm::easm_flow_equal(after, state) and
    meets[0] == prior_meet and counts[0] == prior_count
)
"""
if compact(proof_body(positive_text, "out_of_range_target_is_a_production_noop")) != compact(expected_out_of_range_noop):
    raise SystemExit("out-of-range target theorem must check every production flow table remains unchanged")
expected_changed_contract = """
requires current.valid == true and incoming.valid == true
ensure result == true
entries: mutable darray[Easm::FlowState] = [current]
meets: mutable darray[i64] = [prior_meet]
counts: mutable darray[i64] = [1]
changed: bool = Easm::easm_propagate_flow(0, incoming, entries, meets, counts)
joined: Easm::FlowState = entries[0]
return (
    counts[0] == 2 and
    meets[0] == (prior_meet & incoming.live) and
    joined.valid == true and
    joined.live == (current.live & incoming.live) and
    joined.flags_live == (current.flags_live and incoming.flags_live) and
    joined.stack_known == (current.stack_known and incoming.stack_known and current.stack_mod16 == incoming.stack_mod16) and
    joined.stack_mod16 == (current.stack_mod16 if joined.stack_known else 0) and
    joined.stack_delta == (current.stack_delta if current.stack_delta == incoming.stack_delta else 0) and
    changed == (meets[0] != prior_meet or not Easm::easm_flow_equal(current, joined))
)
"""
if compact(proof_body(positive_text, "production_merge_change_reports_meet_or_state_change")) != compact(expected_changed_contract):
    raise SystemExit("production changed-result theorem must include both meet and FlowState changes")
expected_three_way_control = """
invalid: Easm::FlowState = Easm::FlowState{
    live: 0,
    stack_delta: 0,
    stack_mod16: 0,
    stack_known: false,
    flags_live: false,
    valid: false
}
first: Easm::FlowState = Easm::FlowState{
    live: EasmRegisterMasks::RAX,
    stack_delta: 7,
    stack_mod16: 8,
    stack_known: true,
    flags_live: true,
    valid: true
}
second: Easm::FlowState = Easm::FlowState{
    live: EasmRegisterMasks::RCX,
    stack_delta: 8,
    stack_mod16: 8,
    stack_known: true,
    flags_live: false,
    valid: true
}
third: Easm::FlowState = Easm::FlowState{
    live: EasmRegisterMasks::RDX,
    stack_delta: 8,
    stack_mod16: 0,
    stack_known: true,
    flags_live: true,
    valid: true
}
left_entries: mutable darray[Easm::FlowState] = [invalid]
left_meets: mutable darray[i64] = [0]
left_counts: mutable darray[i64] = [0]
Easm::easm_propagate_flow(0, first, left_entries, left_meets, left_counts)
Easm::easm_propagate_flow(0, second, left_entries, left_meets, left_counts)
Easm::easm_propagate_flow(0, third, left_entries, left_meets, left_counts)
bc_entries: mutable darray[Easm::FlowState] = [invalid]
bc_meets: mutable darray[i64] = [0]
bc_counts: mutable darray[i64] = [0]
Easm::easm_propagate_flow(0, second, bc_entries, bc_meets, bc_counts)
Easm::easm_propagate_flow(0, third, bc_entries, bc_meets, bc_counts)
bc: Easm::FlowState = bc_entries[0]
right_entries: mutable darray[Easm::FlowState] = [first]
right_meets: mutable darray[i64] = [first.live]
right_counts: mutable darray[i64] = [1]
Easm::easm_propagate_flow(0, bc, right_entries, right_meets, right_counts)
left: Easm::FlowState = left_entries[0]
right: Easm::FlowState = right_entries[0]
ensure result == true
return not Easm::easm_flow_equal(left, right)
"""
if compact(proof_body(negative_text, "different_grouping_can_change_a_three_predecessor_merge")) != compact(expected_three_way_control):
    raise SystemExit("three-predecessor false control must challenge the actual nested production merge")
expected_duplicate_control = """
incoming: Easm::FlowState = Easm::FlowState{
    live: EasmRegisterMasks::RAX,
    stack_delta: 24,
    stack_mod16: 8,
    stack_known: true,
    flags_live: true,
    valid: true
}
entries: mutable darray[Easm::FlowState] = [incoming]
meets: mutable darray[i64] = [incoming.live]
counts: mutable darray[i64] = [1]
changed: bool = Easm::easm_propagate_flow(0, incoming, entries, meets, counts)
after: Easm::FlowState = entries[0]
ensure result == true
return changed or not Easm::easm_flow_equal(after, incoming)
"""
if compact(proof_body(negative_text, "a_duplicate_predecessor_can_change_the_production_state")) != compact(expected_duplicate_control):
    raise SystemExit("duplicate-predecessor false control must contradict the production idempotence claim")
expected_bad_target_controls = {
    "a_negative_target_can_mutate_a_nonempty_flow_table": "-1",
    "a_target_equal_to_the_entry_count_can_mutate_the_flow_table": "1",
}
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
expected_meet_only_control = """
state: Easm::FlowState = Easm::FlowState{
    live: EasmRegisterMasks::RAX,
    stack_delta: 24,
    stack_mod16: 8,
    stack_known: true,
    flags_live: true,
    valid: true
}
entries: mutable darray[Easm::FlowState] = [state]
meets: mutable darray[i64] = [EasmRegisterMasks::RAX | EasmRegisterMasks::RCX]
counts: mutable darray[i64] = [1]
changed: bool = Easm::easm_propagate_flow(0, state, entries, meets, counts)
after: Easm::FlowState = entries[0]
ensure result == true
return changed == (not Easm::easm_flow_equal(state, after))
"""
if compact(proof_body(negative_text, "production_change_can_ignore_a_meet_only_change")) != compact(expected_meet_only_control):
    raise SystemExit("meet-only false control must show that changed is not just FlowState inequality")
expected_conflicting_provenance_control = """
left_types: mutable darray[sview] = ["i64*"]
right_types: mutable darray[sview] = ["f64*"]
left: Easm::ProvenanceFlow = Easm::ProvenanceFlow{
    types: left_types,
    ambiguous: 0,
    valid: true
}
right: Easm::ProvenanceFlow = Easm::ProvenanceFlow{
    types: right_types,
    ambiguous: 0,
    valid: true
}
entries: mutable darray[Easm::ProvenanceFlow] = [left]
counts: mutable darray[i64] = [1]
Easm::easm_provenance_flow_propagate(0, right, entries, counts)
joined: Easm::ProvenanceFlow = entries[0]
ensure result == true
return joined.ambiguous == 0 and joined.types[0] == "i64*"
"""
if compact(proof_body(negative_text, "a_conflicting_provenance_join_can_remain_precise")) != compact(expected_conflicting_provenance_control):
    raise SystemExit("provenance false control must reject retaining a precise carrier across disagreement")
expected_first_provenance_control = """
incoming: mutable Easm::ProvenanceFlow = Easm::easm_empty_provenance_flow()
incoming.types[0] <- "i64*"
incoming.valid <- true
entries: mutable darray[Easm::ProvenanceFlow] = [Easm::easm_empty_provenance_flow()]
counts: mutable darray[i64] = [0]
changed: bool = Easm::easm_provenance_flow_propagate(0, incoming, entries, counts)
installed: Easm::ProvenanceFlow = entries[0]
ensure result == true
return not changed or counts[0] != 1 or not installed.valid or not Easm::easm_provenance_flow_equal(installed, incoming)
"""
if compact(proof_body(negative_text, "a_first_provenance_predecessor_can_leave_the_empty_entry")) != compact(expected_first_provenance_control):
    raise SystemExit("first-provenance false control must challenge the production sentinel installation")
expected_duplicate_provenance_control = """
requires incoming.valid == true and incoming.types.count == 16
entries: mutable darray[Easm::ProvenanceFlow] = [incoming]
counts: mutable darray[i64] = [1]
changed: bool = Easm::easm_provenance_flow_propagate(0, incoming, entries, counts)
after: Easm::ProvenanceFlow = entries[0]
ensure result == true
return changed or not Easm::easm_provenance_flow_equal(after, incoming)
"""
if compact(proof_body(negative_text, "a_duplicate_provenance_predecessor_can_change_the_state")) != compact(expected_duplicate_provenance_control):
    raise SystemExit("duplicate provenance false control must oppose production idempotence")
expected_production_xchg_control = """
incoming_types: mutable darray[sview] = []
for _ in 0..<16 |incoming_types|:
    incoming_types.push("")
incoming_types[0] <- "i64*"
incoming_types[1] <- "f64*"
incoming: Easm::ProvenanceFlow = Easm::ProvenanceFlow{
    types: incoming_types,
    ambiguous: 1,
    valid: true
}
instruction: Easm::Instruction = Easm::Instruction{
    op: "xchgq",
    text: "%rax, %rcx",
    line: 1,
    pseudo: false,
    substitution_count: 0,
    substitution0: Easm::Substitution{from: "", replacement: ""},
    substitution1: Easm::Substitution{from: "", replacement: ""},
    substitution2: Easm::Substitution{from: "", replacement: ""},
    substitution3: Easm::Substitution{from: "", replacement: ""}
}
out: Easm::ProvenanceFlow = Easm::easm_provenance_flow_transfer(instruction, incoming)
ensure result == true
return out.types[0] == "i64*" and out.types[1] == "f64*" and out.ambiguous == 1
"""
if compact(proof_body(negative_text, "production_xchg_can_keep_the_old_carriers_in_place")) != compact(expected_production_xchg_control):
    raise SystemExit("production xchg false control must challenge swapping the old carriers")
expected_production_call_control = """
requires incoming.valid == true and incoming.types.count == 16 and incoming.types[0] != ""
requires (incoming.ambiguous & EasmRegisterMasks::RAX) == 0
ensure result == true
instruction: Easm::Instruction = Easm::Instruction{
    op: "callq",
    text: "target",
    line: 1,
    pseudo: false,
    substitution_count: 0,
    substitution0: Easm::Substitution{from: "", replacement: ""},
    substitution1: Easm::Substitution{from: "", replacement: ""},
    substitution2: Easm::Substitution{from: "", replacement: ""},
    substitution3: Easm::Substitution{from: "", replacement: ""}
}
out: Easm::ProvenanceFlow = Easm::easm_provenance_flow_transfer(instruction, incoming)
return out.types[0] == incoming.types[0]
"""
if compact(proof_body(negative_text, "production_call_can_keep_a_clobbered_carrier")) != compact(expected_production_call_control):
    raise SystemExit("production call false control must challenge clobbering the incoming RAX carrier")
expected_cpuid_control = """
requires incoming.valid == true and incoming.types.count == 16 and incoming.types[0] != ""
requires (incoming.ambiguous & EasmRegisterMasks::RAX) == 0
ensure result == true
instruction: Easm::Instruction = Easm::Instruction{
    op: "cpuid",
    text: "",
    line: 1,
    pseudo: false,
    substitution_count: 0,
    substitution0: Easm::Substitution{from: "", replacement: ""},
    substitution1: Easm::Substitution{from: "", replacement: ""},
    substitution2: Easm::Substitution{from: "", replacement: ""},
    substitution3: Easm::Substitution{from: "", replacement: ""}
}
out: Easm::ProvenanceFlow = Easm::easm_provenance_flow_transfer(instruction, incoming)
return out.types[0] == incoming.types[0]
"""
if compact(proof_body(negative_text, "production_cpuid_can_keep_rax_provenance")) != compact(expected_cpuid_control):
    raise SystemExit("CPUID false control must challenge clearing its implicit RAX result")
expected_partial_move_control = """
requires incoming.valid == true and incoming.types.count == 16 and incoming.types[0] != ""
ensure result == true
instruction: Easm::Instruction = Easm::Instruction{
    op: "movl",
    text: "%eax, %ecx",
    line: 1,
    pseudo: false,
    substitution_count: 0,
    substitution0: Easm::Substitution{from: "", replacement: ""},
    substitution1: Easm::Substitution{from: "", replacement: ""},
    substitution2: Easm::Substitution{from: "", replacement: ""},
    substitution3: Easm::Substitution{from: "", replacement: ""}
}
out: Easm::ProvenanceFlow = Easm::easm_provenance_flow_transfer(instruction, incoming)
return out.types[1] == incoming.types[0]
"""
if compact(proof_body(negative_text, "production_partial_move_can_copy_a_pointer_carrier")) != compact(expected_partial_move_control):
    raise SystemExit("partial move false control must challenge pointer copying from a 32-bit alias")
expected_partial_exchange_control = """
requires incoming.valid == true and incoming.types.count == 16 and incoming.types[0] != "" and incoming.types[1] != ""
ensure result == true
instruction: Easm::Instruction = Easm::Instruction{
    op: "xchgl",
    text: "%eax, %ecx",
    line: 1,
    pseudo: false,
    substitution_count: 0,
    substitution0: Easm::Substitution{from: "", replacement: ""},
    substitution1: Easm::Substitution{from: "", replacement: ""},
    substitution2: Easm::Substitution{from: "", replacement: ""},
    substitution3: Easm::Substitution{from: "", replacement: ""}
}
out: Easm::ProvenanceFlow = Easm::easm_provenance_flow_transfer(instruction, incoming)
return out.types[0] == incoming.types[0] and out.types[1] == incoming.types[1]
"""
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
expected_iteration = """
for round_index in 0..<(count + 1) |round_index, entries, meets, incoming_counts, fn, issues|:
    changed: mutable bool = false
    for index in 0..<count |index, entries, meets, incoming_counts, fn, issues, changed|:
        continue if not entries[index].valid
        instruction: Instruction = fn.instructions[index]
        state: FlowState = easm_flow_transfer(instruction, entries[index])
        if easm_starts(instruction.op, "j"):
            target: sview = easm_substitute_operand(easm_last_operand(instruction.text), instruction)
            if target.len > 0 and target[0] != 37:
                changed <- easm_propagate_flow(easm_label_index(fn.instructions, target), state, entries, meets, incoming_counts) or changed
            if easm_is_terminator(instruction.op):
                continue
        if not easm_is_terminator(instruction.op) and index + 1 < count:
            changed <- easm_propagate_flow(index.i64() + 1, state, entries, meets, incoming_counts) or changed
    break if not changed
"""
if compact(iteration_start + iteration) != compact(expected_iteration):
    raise SystemExit("fixed-point traversal must propagate branch targets and fallthrough through the proved join before convergence")
if "continue if fn.instructions[index].op != \"label\" or incoming_counts[index] == 0" not in verify_merges:
    raise SystemExit("post-fixpoint liveness validation must inspect every reachable label block")
expected_missing_check = """
missing: i64 = demanded & (~meets[index])
if missing != 0:
    issues.push(Issue{severity: Severity.Error, code: "merge-state-unsound", line: fn.instructions[index].line, message: "merge label carries a register that is not established on every incoming edge; declare a labels contract or write the register on every edge"})
"""
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
expected_module_compositions = """
for fn in module.functions |module, issues|:
    verify_function_compositions(fn, module.fragments, issues)
"""
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
