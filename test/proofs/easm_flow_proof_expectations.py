"""Source-bound EASM flow proof expectations."""


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

expected_missing_check = """
missing: i64 = demanded & (~meets[index])
if missing != 0:
    issues.push(Issue{severity: Severity.Error, code: "merge-state-unsound", line: fn.instructions[index].line, message: "merge label carries a register that is not established on every incoming edge; declare a labels contract or write the register on every edge"})
"""

expected_module_compositions = """
for fn in module.functions |module, issues|:
    verify_function_compositions(fn, module.fragments, issues)
"""
