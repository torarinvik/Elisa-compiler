"""Source-bound EASM flow false claim expectations."""


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

expected_bad_target_controls = {
    "a_negative_target_can_mutate_a_nonempty_flow_table": "-1",
    "a_target_equal_to_the_entry_count_can_mutate_the_flow_table": "1",
}

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

expected_duplicate_provenance_control = """
requires incoming.valid == true and incoming.types.count == 16
entries: mutable darray[Easm::ProvenanceFlow] = [incoming]
counts: mutable darray[i64] = [1]
changed: bool = Easm::easm_provenance_flow_propagate(0, incoming, entries, counts)
after: Easm::ProvenanceFlow = entries[0]
ensure result == true
return changed or not Easm::easm_provenance_flow_equal(after, incoming)
"""

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
