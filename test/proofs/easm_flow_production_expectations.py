"""Source-bound EASM flow production expectations."""


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

expected_width_policy = """ensure when register:
        "rax" | "rcx" | "rdx" | "rbx" | "rsi" | "rdi" | "rbp" | "rsp" | "r8" | "r9" | "r10" | "r11" | "r12" | "r13" | "r14" | "r15" -> result == ADDRESS_REGISTER_WIDTH_64
        "eax" | "ecx" | "edx" | "ebx" | "esi" | "edi" | "ebp" | "esp" | "r8d" | "r9d" | "r10d" | "r11d" | "r12d" | "r13d" | "r14d" | "r15d" -> result == ADDRESS_REGISTER_WIDTH_32
        _ -> result == ADDRESS_REGISTER_WIDTH_UNKNOWN
    return match register:
        "rax" | "rcx" | "rdx" | "rbx" | "rsi" | "rdi" | "rbp" | "rsp" | "r8" | "r9" | "r10" | "r11" | "r12" | "r13" | "r14" | "r15": ADDRESS_REGISTER_WIDTH_64
        "eax" | "ecx" | "edx" | "ebx" | "esi" | "edi" | "ebp" | "esp" | "r8d" | "r9d" | "r10d" | "r11d" | "r12d" | "r13d" | "r14d" | "r15d": ADDRESS_REGISTER_WIDTH_32
        _: ADDRESS_REGISTER_WIDTH_UNKNOWN"""

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

expected_provenance_propagate = """
return false if target < 0 or target >= entries.count.i64()
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

expected_empty_provenance = """
types: mutable darray[sview] = []
for _ in 0..<16 |types|:
    types.push("")
return ProvenanceFlow{types: types, ambiguous: 0, valid: false}
"""

expected_provenance_equal = """
return false if a.valid != b.valid or a.ambiguous != b.ambiguous or a.types.count != b.types.count
for index in 0..<a.types.count |a, b|:
    return false if a.types[index] != b.types[index]
return true
"""

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
return out if easm_starts(instruction.op, "cmp") or easm_starts(instruction.op, "test") or easm_starts(instruction.op, "push") or easm_starts(instruction.op, "jmp") or easm_starts(instruction.op, "ret")
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
