"""Admit the finite EASM call-liveness proof against a strict Elisa-proof product."""
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
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
POSITIVE = HERE / "easm_call_liveness.elisa"
NEGATIVE = HERE / "easm_call_liveness_rejected.elisa"
MASKS = ROOT / "src/backend/easm_register_masks.elisa"
MODEL = ROOT / "src/backend/easm_model.elisa"
PROVENANCE = ROOT / "src/backend/easm_verify_provenance.elisa"

parser = argparse.ArgumentParser()
parser.add_argument("--source-only", action="store_true",
                    help="check production and proof-fixture bindings without running Elisa-Proof")
ARGS = parser.parse_args()

REGISTER_NAMES = (
    "RAX", "RCX", "RDX", "RBX", "RSI", "RDI", "RBP", "RSP",
    "R8", "R9", "R10", "R11", "R12", "R13", "R14", "R15",
)
REGISTER_INDEX = {name: index for index, name in enumerate(REGISTER_NAMES)}
EXPECTED_DECLARATIONS = {
    "model_call_preserves_register_index",
    "model_call_invalidates_register_index",
    "call_transfer_clears_live_flags",
    "every_register_slot_has_its_exact_call_effect_class",
    "out_of_range_register_indices_have_no_call_effect",
    "rax_is_disjoint_from_the_invalidated_class",
    "rsp_is_disjoint_from_the_invalidated_class",
    "rbx_is_disjoint_from_the_invalidated_class",
    "rbp_is_disjoint_from_the_invalidated_class",
    "r12_is_disjoint_from_the_invalidated_class",
    "r13_is_disjoint_from_the_invalidated_class",
    "r14_is_disjoint_from_the_invalidated_class",
    "r15_is_disjoint_from_the_invalidated_class",
    "xchg_writes_both_register_operands",
    "xchg_flow_transfer_adds_both_operands_to_live_set",
    "xchg_rsp_invalidates_stack_alignment",
    "xchg_rsp_destination_invalidates_stack_alignment",
    "pushq_updates_known_stack_state",
    "popq_register_destination_updates_known_stack_state",
}
FALSE_CLAIMS = {
    "call_invalidates_rax_slot",
    "call_preserves_rcx_slot",
    "call_invalidates_callee_saved_slot",
    "out_of_range_register_index_is_invalidated",
    "call_preserves_live_flags",
    "xchg_can_omit_its_source_register_write",
    "xchg_flow_transfer_can_drop_both_new_live_registers",
    "xchg_rsp_can_preserve_stack_knownness",
    "xchg_rsp_destination_can_preserve_stack_knownness",
    "pushq_can_leave_stack_delta_unchanged",
    "popq_register_destination_can_invalidate_stack_alignment",
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


def return_expression(source: str, name: str) -> str:
    body = proof_body(source, name)
    if "return " not in body:
        raise SystemExit(f"proof function has no return expression: {name}")
    return compact(body.split("return ", 1)[1])


mask_source = MASKS.read_text()
source_mask_bits = {
    name: int(value)
    for name, value in re.findall(r"(?m)^        const (R(?:AX|CX|DX|BX|SI|DI|BP|SP|[0-9]+)): i64 = ([0-9]+)$", mask_source)
}
if set(source_mask_bits) != set(REGISTER_NAMES):
    raise SystemExit("canonical register mask inventory changed")
if any(value <= 0 or value & (value - 1) for value in source_mask_bits.values()):
    raise SystemExit("canonical register masks must remain one-hot")
source_index = {name: value.bit_length() - 1 for name, value in source_mask_bits.items()}
if source_index != REGISTER_INDEX:
    raise SystemExit(f"proof register indices no longer encode the canonical mask bits: {source_index!r}")


def mask_function(name: str) -> tuple[str, str]:
    function = source_body(mask_source, f"def {name}() -> i64:")
    ensures = re.findall(r"(?m)^            ensure result == \((.*)\)$", function)
    returns = re.findall(r"(?m)^            return (.*)$", function)
    if len(ensures) != 1 or len(returns) != 1:
        raise SystemExit(f"mask helper no longer has one exact contract and return: {name}")
    return compact(ensures[0]), compact(returns[0])


def mask_names(expression: str) -> tuple[str, ...]:
    return tuple(re.findall(r"\bR(?:AX|CX|DX|BX|SI|DI|BP|SP|[0-9]+)\b", expression))


invalidation_names = ("RCX", "RDX", "RSI", "RDI", "R8", "R9", "R10", "R11")
caller_saved_names = ("RAX",) + invalidation_names
callee_saved_names = ("RBX", "RBP", "R12", "R13", "R14", "R15")
for helper, expected in (
    ("call_invalidates_live_mask", invalidation_names),
    ("call_clobber_mask", caller_saved_names),
    ("callee_saved_gpr_mask", callee_saved_names),
):
    ensure, returned = mask_function(helper)
    expected_expr = " | ".join(expected)
    if ensure != expected_expr or returned != expected_expr:
        raise SystemExit(f"production `{helper}` mask differs from the source-bound call model")

positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()
model_indices = {
    name: int(value)
    for name, value in re.findall(r"(?m)^const REG_([A-Z0-9]+): i64 = ([0-9]+)$", positive_text)
}
if model_indices != REGISTER_INDEX:
    raise SystemExit("proof register-index table does not cover the canonical one-hot masks")

retained_names = {"RAX", "RSP", *callee_saved_names}
retained_indices = tuple(REGISTER_INDEX[name] for name in REGISTER_NAMES if name in retained_names)
invalidated_indices = tuple(REGISTER_INDEX[name] for name in invalidation_names)
for predicate, expected_names in (
    ("model_call_preserves_register_index", tuple(f"REG_{name}" for name in ("RAX", "RSP", *callee_saved_names))),
    ("model_call_invalidates_register_index", tuple(f"REG_{name}" for name in invalidation_names)),
):
    body = proof_body(positive_text, predicate)
    ensure, returned = body.split("return ", 1)
    expected = " or ".join(f"register_index == {name}" for name in expected_names)
    if compact(ensure).replace("ensure result == ", "", 1).strip().strip("()") != compact(expected):
        raise SystemExit(f"proof classification contract changed for {predicate}")
    if compact(returned) != compact(expected):
        raise SystemExit(f"proof classification body changed for {predicate}")

slot_proof_return = return_expression(positive_text, "every_register_slot_has_its_exact_call_effect_class")
for name, index in REGISTER_INDEX.items():
    if f"REG_{name} == {index}" not in slot_proof_return:
        raise SystemExit(f"finite register proof omits canonical slot {name}")
    expected_class = retained_indices if name in retained_names else invalidated_indices
    expected_membership = " or ".join(f"REG_{name} == {slot}" for slot in expected_class)
    if compact(expected_membership) not in slot_proof_return:
        raise SystemExit(f"finite register proof misclassifies slot {name}")

for name in retained_names:
    theorem = f"{name.lower()}_is_disjoint_from_the_invalidated_class"
    expression = " and ".join(f"REG_{name} != REG_{other}" for other in invalidation_names)
    if return_expression(positive_text, theorem) != compact(expression):
        raise SystemExit(f"retained slot disjointness proof changed for {name}")

for theorem, expression in (
    ("call_invalidates_rax_slot", "REG_RAX == 1 or REG_RAX == 2 or REG_RAX == 4 or REG_RAX == 5 or REG_RAX == 8 or REG_RAX == 9 or REG_RAX == 10 or REG_RAX == 11"),
    ("call_preserves_rcx_slot", "REG_RCX == 0 or REG_RCX == 3 or REG_RCX == 6 or REG_RCX == 7 or REG_RCX == 12 or REG_RCX == 13 or REG_RCX == 14 or REG_RCX == 15"),
    ("call_invalidates_callee_saved_slot", "REG_RBX == 1 or REG_RBX == 2 or REG_RBX == 4 or REG_RBX == 5 or REG_RBX == 8 or REG_RBX == 9 or REG_RBX == 10 or REG_RBX == 11"),
    ("out_of_range_register_index_is_invalidated", "model_call_invalidates_register_index(REG_R15 + 1)"),
):
    if return_expression(negative_text, theorem) != compact(expression):
        raise SystemExit(f"false-claim control changed: {theorem}")

out_of_range_negative = proof_body(negative_text, "out_of_range_register_index_is_invalidated")
expected_out_of_range_negative = """
requires REG_R15 + 1 == 16
ensure result == true
return model_call_invalidates_register_index(REG_R15 + 1)
"""
if compact(out_of_range_negative) != compact(expected_out_of_range_negative):
    raise SystemExit("out-of-range false control no longer targets the first index beyond R15")

out_of_range_positive = proof_body(positive_text, "out_of_range_register_indices_have_no_call_effect")
expected_out_of_range_positive = """
requires register_index < 0 or register_index >= 16
ensure result == true
return not model_call_preserves_register_index(register_index) and
    not model_call_invalidates_register_index(register_index)
"""
if compact(out_of_range_positive) != compact(expected_out_of_range_positive):
    raise SystemExit("out-of-range call-liveness theorem no longer proves both classifications are false")

model_source = MODEL.read_text()
register_bit = source_body(model_source, "def easm_register_bit(register: sview) -> i64:")
expected_register_bit = """
ensure result == EasmRegisterMasks::register_bit(register)
return EasmRegisterMasks::register_bit(register)
"""
if compact(register_bit) != compact(expected_register_bit):
    raise SystemExit("EASM register-bit lookup no longer delegates exactly to the canonical alias map")

written_mask = source_body(model_source, "def easm_written_mask(instruction: Instruction) -> i64:")
expected_written_mask = (
    'if easm_starts(instruction.op, "cmp") or easm_starts(instruction.op, "test") or '
    'easm_starts(instruction.op, "push") or '
    'easm_starts(instruction.op, "call") or easm_starts(instruction.op, "jmp") or '
    'easm_starts(instruction.op, "ret"):\n'
    '                return 0\n'
    '            destination: sview = easm_substitute_operand(easm_last_operand(instruction.text), instruction)\n'
    '            destination_mask: i64 = easm_register_bit(easm_register_operand(destination))\n'
    '            if easm_starts(instruction.op, "xchg"):\n'
    '                source: sview = easm_substitute_operand(easm_first_operand(instruction.text), instruction)\n'
    '                return destination_mask | easm_register_bit(easm_register_operand(source))\n'
    '            return destination_mask\n'
)
if compact(written_mask) != compact(expected_written_mask):
    raise SystemExit("call instructions no longer bypass the ordinary written-register transfer")

xchg_instruction = """
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
written: i64 = Easm::easm_written_mask(instruction)
"""
expected_xchg_positive = """
ensure result == true
""" + xchg_instruction + """
return (
    written == (EasmRegisterMasks::RAX | EasmRegisterMasks::RCX) and
    (written & EasmRegisterMasks::RAX) == EasmRegisterMasks::RAX and
    (written & EasmRegisterMasks::RCX) == EasmRegisterMasks::RCX
)
"""
if compact(proof_body(positive_text, "xchg_writes_both_register_operands")) != compact(expected_xchg_positive):
    raise SystemExit("xchg proof must check the production write mask against both concrete operands")
expected_xchg_negative = """
ensure result == true
""" + xchg_instruction + """
return (written & EasmRegisterMasks::RAX) == 0
"""
if compact(proof_body(negative_text, "xchg_can_omit_its_source_register_write")) != compact(expected_xchg_negative):
    raise SystemExit("xchg false control must challenge omission of the source operand write")
expected_xchg_flow_positive = """
ensure result == true
""" + xchg_instruction.split("written: i64 =", 1)[0] + """
out: Easm::FlowState = Easm::easm_flow_transfer(instruction, incoming)
return (
    out.live == (incoming.live | (EasmRegisterMasks::RAX | EasmRegisterMasks::RCX)) and
    out.flags_live == incoming.flags_live and
    out.stack_delta == incoming.stack_delta and
    out.stack_mod16 == incoming.stack_mod16 and
    out.stack_known == incoming.stack_known and
    out.valid == incoming.valid
)
"""
if compact(proof_body(positive_text, "xchg_flow_transfer_adds_both_operands_to_live_set")) != compact(expected_xchg_flow_positive):
    raise SystemExit("xchg flow theorem must preserve the complete state while adding both writes")
expected_xchg_flow_negative = """
ensure result == true
""" + xchg_instruction.split("written: i64 =", 1)[0] + """
out: Easm::FlowState = Easm::easm_flow_transfer(instruction, incoming)
return out.live == incoming.live
"""
if compact(proof_body(negative_text, "xchg_flow_transfer_can_drop_both_new_live_registers")) != compact(expected_xchg_flow_negative):
    raise SystemExit("xchg flow false control must reject dropping the written registers")

xchg_rsp_instruction = """
instruction: Easm::Instruction = Easm::Instruction{
    op: "xchgq",
    text: "%rsp, %rax",
    line: 1,
    pseudo: false,
    substitution_count: 0,
    substitution0: Easm::Substitution{from: "", replacement: ""},
    substitution1: Easm::Substitution{from: "", replacement: ""},
    substitution2: Easm::Substitution{from: "", replacement: ""},
    substitution3: Easm::Substitution{from: "", replacement: ""}
}
"""
expected_xchg_rsp_positive = """
ensure result == true
""" + xchg_rsp_instruction + """
out: Easm::FlowState = Easm::easm_flow_transfer(instruction, incoming)
return (
    out.live == (incoming.live | (EasmRegisterMasks::RSP | EasmRegisterMasks::RAX)) and
    out.stack_known == false and
    out.stack_mod16 == 0 and
    out.stack_delta == incoming.stack_delta and
    out.flags_live == incoming.flags_live and
    out.valid == incoming.valid
)
"""
if compact(proof_body(positive_text, "xchg_rsp_invalidates_stack_alignment")) != compact(expected_xchg_rsp_positive):
    raise SystemExit("xchg-rsp theorem must prove both writes and fail-closed stack-state invalidation")
expected_xchg_rsp_negative = """
requires incoming.stack_known == true
ensure result == true
""" + xchg_rsp_instruction + """
out: Easm::FlowState = Easm::easm_flow_transfer(instruction, incoming)
return out.stack_known
"""
if compact(proof_body(negative_text, "xchg_rsp_can_preserve_stack_knownness")) != compact(expected_xchg_rsp_negative):
    raise SystemExit("xchg-rsp false control must challenge preservation of known stack state")

xchg_rsp_destination_instruction = xchg_rsp_instruction.replace(
    'text: "%rsp, %rax"', 'text: "%rax, %rsp"'
)
expected_xchg_rsp_destination_positive = """
ensure result == true
""" + xchg_rsp_destination_instruction + """
out: Easm::FlowState = Easm::easm_flow_transfer(instruction, incoming)
return (
    out.live == (incoming.live | (EasmRegisterMasks::RSP | EasmRegisterMasks::RAX)) and
    out.stack_known == false and
    out.stack_mod16 == 0 and
    out.stack_delta == incoming.stack_delta and
    out.flags_live == incoming.flags_live and
    out.valid == incoming.valid
)
"""
if compact(proof_body(positive_text, "xchg_rsp_destination_invalidates_stack_alignment")) != compact(expected_xchg_rsp_destination_positive):
    raise SystemExit("destination-RSP xchg theorem must prove both writes and stack-state invalidation")
expected_xchg_rsp_destination_negative = """
requires incoming.stack_known == true
ensure result == true
""" + xchg_rsp_destination_instruction + """
out: Easm::FlowState = Easm::easm_flow_transfer(instruction, incoming)
return out.stack_known
"""
if compact(proof_body(negative_text, "xchg_rsp_destination_can_preserve_stack_knownness")) != compact(expected_xchg_rsp_destination_negative):
    raise SystemExit("destination-RSP xchg false control must challenge preservation of known stack state")

push_instruction = """
instruction: Easm::Instruction = Easm::Instruction{
    op: "pushq",
    text: "$0",
    line: 1,
    pseudo: false,
    substitution_count: 0,
    substitution0: Easm::Substitution{from: "", replacement: ""},
    substitution1: Easm::Substitution{from: "", replacement: ""},
    substitution2: Easm::Substitution{from: "", replacement: ""},
    substitution3: Easm::Substitution{from: "", replacement: ""}
}
"""
expected_push_positive = """
requires incoming.stack_known == true
requires incoming.stack_delta >= -9223372036854775800
requires incoming.stack_mod16 >= 0 and incoming.stack_mod16 < 16
ensure result == true
""" + push_instruction + """
out: Easm::FlowState = Easm::easm_flow_transfer(instruction, incoming)
return (
    out.live == incoming.live and
    out.stack_delta == incoming.stack_delta - 8 and
    out.stack_mod16 == (incoming.stack_mod16 - 8) % 16 and
    out.stack_known == true and
    out.flags_live == incoming.flags_live and
    out.valid == incoming.valid
)
"""
if compact(proof_body(positive_text, "pushq_updates_known_stack_state")) != compact(expected_push_positive):
    raise SystemExit("push theorem must bind exact depth, alignment, and preserved-flow effects")
expected_push_negative = """
requires incoming.stack_known == true
requires incoming.stack_delta >= -9223372036854775800
requires incoming.stack_mod16 >= 0 and incoming.stack_mod16 < 16
ensure result == true
""" + push_instruction + """
out: Easm::FlowState = Easm::easm_flow_transfer(instruction, incoming)
return out.stack_delta == incoming.stack_delta
"""
if compact(proof_body(negative_text, "pushq_can_leave_stack_delta_unchanged")) != compact(expected_push_negative):
    raise SystemExit("push false control must challenge its word-sized stack-depth decrement")

pop_instruction = """
instruction: Easm::Instruction = Easm::Instruction{
    op: "popq",
    text: "%rax",
    line: 1,
    pseudo: false,
    substitution_count: 0,
    substitution0: Easm::Substitution{from: "", replacement: ""},
    substitution1: Easm::Substitution{from: "", replacement: ""},
    substitution2: Easm::Substitution{from: "", replacement: ""},
    substitution3: Easm::Substitution{from: "", replacement: ""}
}
"""
expected_pop_positive = """
requires incoming.stack_known == true
requires incoming.stack_delta <= 9223372036854775799
requires incoming.stack_mod16 >= 0 and incoming.stack_mod16 < 16
ensure result == true
""" + pop_instruction + """
out: Easm::FlowState = Easm::easm_flow_transfer(instruction, incoming)
return (
    out.live == (incoming.live | EasmRegisterMasks::RAX) and
    out.stack_delta == incoming.stack_delta + 8 and
    out.stack_mod16 == (incoming.stack_mod16 + 8) % 16 and
    out.stack_known == true and
    out.flags_live == incoming.flags_live and
    out.valid == incoming.valid
)
"""
if compact(proof_body(positive_text, "popq_register_destination_updates_known_stack_state")) != compact(expected_pop_positive):
    raise SystemExit("register-pop theorem must prove destination liveness and preserved stack alignment")
expected_pop_negative = """
requires incoming.stack_known == true
requires incoming.stack_delta <= 9223372036854775799
requires incoming.stack_mod16 >= 0 and incoming.stack_mod16 < 16
ensure result == true
""" + pop_instruction + """
out: Easm::FlowState = Easm::easm_flow_transfer(instruction, incoming)
return not out.stack_known
"""
if compact(proof_body(negative_text, "popq_register_destination_can_invalidate_stack_alignment")) != compact(expected_pop_negative):
    raise SystemExit("register-pop false control must challenge preservation of known stack alignment")

stack_pointer_write = source_body(
    model_source,
    "def easm_stack_pointer_write_register(instruction: Instruction) -> sview:",
)
expected_stack_pointer_write = """
destination: sview = easm_substitute_operand(easm_last_operand(instruction.text), instruction)
destination_register: sview = easm_register_operand(destination)
if easm_register_bit(destination_register) == EasmRegisterMasks::RSP:
    return destination_register
if easm_starts(instruction.op, "xchg"):
    source: sview = easm_substitute_operand(easm_first_operand(instruction.text), instruction)
    source_register: sview = easm_register_operand(source)
    return source_register if easm_register_bit(source_register) == EasmRegisterMasks::RSP
return ""
"""
if compact(stack_pointer_write) != compact(expected_stack_pointer_write):
    raise SystemExit("stack-pointer write resolver must detect RSP in either xchg operand")
if compact(source_body(model_source, "def easm_writes_stack_pointer(instruction: Instruction) -> bool:")) != compact(
    "return easm_stack_pointer_write_register(instruction) != \"\""
):
    raise SystemExit("stack-pointer write predicate must delegate to its operand resolver")

flow_transfer = source_body(model_source, "def easm_flow_transfer(instruction: Instruction, incoming: FlowState) -> FlowState:")
ordinary_write = "if written != 0:\n                out.live <- out.live | written"
call_branch = (
    'if easm_starts(instruction.op, "call"):\n'
    '                out.live <- out.live & (~EasmRegisterMasks::call_invalidates_live_mask())\n'
    '                out.flags_live <- false'
)
if "out: mutable FlowState = incoming" not in flow_transfer or "written: i64 = easm_written_mask(instruction)" not in flow_transfer:
    raise SystemExit("flow transfer no longer begins from incoming state and its written-register mask")
stack_invalidation = """
if easm_writes_stack_pointer(instruction) and not stack_write_handled:
    out.stack_known <- false
    out.stack_mod16 <- 0
"""
push_stack_update = """
if easm_starts(instruction.op, "push"):
    out.stack_delta <- out.stack_delta - 8
    out.stack_mod16 <- (out.stack_mod16 - 8) % 16 if out.stack_known
"""
pop_register_update = """
if easm_starts(instruction.op, "pop"):
    pop_destination: sview = easm_register_operand(easm_substitute_operand(easm_last_operand(instruction.text), instruction))
    stack_write_handled <- true
    if easm_register_bit(pop_destination) == EasmRegisterMasks::RSP:
        out.stack_known <- false
        out.stack_mod16 <- 0
    else:
        out.stack_delta <- out.stack_delta + 8
        out.stack_mod16 <- (out.stack_mod16 + 8) % 16 if out.stack_known
"""
if compact(stack_invalidation) not in compact(flow_transfer) or flow_transfer.count("stack_write_handled <- true") != 2:
    raise SystemExit("unhandled stack-pointer writes must invalidate alignment without xchg exceptions")
if compact(push_stack_update) not in compact(flow_transfer):
    raise SystemExit("push transfer must decrement stack depth and rotate known alignment by one word")
if compact(pop_register_update) not in compact(flow_transfer):
    raise SystemExit("pop transfer must distinguish RSP from ordinary register destinations")
if compact(ordinary_write) not in compact(flow_transfer) or compact(call_branch) not in compact(flow_transfer):
    raise SystemExit("call liveness kill moved outside its source-guarded call branch")
if flow_transfer.count("out.live <-") != 2:
    raise SystemExit("call transfer has an additional live-register update outside the modeled steps")
if flow_transfer.index("out.live <- out.live | written") > flow_transfer.index("out.live <- out.live & (~EasmRegisterMasks::call_invalidates_live_mask())"):
    raise SystemExit("call invalidation must occur after the ordinary write transfer")
call_guard = flow_transfer.index('if easm_starts(instruction.op, "call"):')
call_flags_clear = flow_transfer.index("out.flags_live <- false", call_guard)
compare_guard = flow_transfer.index('if easm_starts(instruction.op, "cmp") or easm_starts(instruction.op, "test"):', call_guard)
if not call_guard < call_flags_clear < compare_guard:
    raise SystemExit("call flow transfer no longer clears live flags before the following flag-producing opcode checks")
provenance = PROVENANCE.read_text()
known_op = source_body(provenance, "def easm_known_op(op: sview) -> bool:")
call_spellings = set(re.findall(r'easm_equal\(op, "([^"]+)"\)', known_op))
if {name for name in call_spellings if name.startswith("call")} != {"call", "callq"}:
    raise SystemExit("call-prefix transfer must apply to the exact admitted call/callq operations")

actual_declarations = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", positive_text))
if actual_declarations != EXPECTED_DECLARATIONS:
    raise SystemExit("positive call-liveness proof declarations changed")
negative_declarations = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", negative_text))
if negative_declarations != FALSE_CLAIMS:
    raise SystemExit("call-liveness false-claim controls changed")
if compact("def call_transfer_clears_live_flags(was_live: bool) -> bool: ensure result == false return false") not in compact(positive_text):
    raise SystemExit("call-flags proof no longer models the transfer's unconditional flag clear")
if compact("def call_preserves_live_flags(was_live: bool) -> bool: requires was_live == true ensure result == was_live return false") not in compact(negative_text):
    raise SystemExit("call-flags false claim no longer challenges the unconditional flag clear")

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
    raise SystemExit("EASM call-liveness proof requires a strict proof build")
stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"), PROVER / "ELISA_COMPILER_REV",
    stage1_product, stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
    POSITIVE, NEGATIVE, MASKS, MODEL, PROVENANCE,
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
assert positive["summary"]["obligations"] == positive["summary"]["proven"] == 2 * len(EXPECTED_DECLARATIONS)
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "call-liveness proof report changed across repeated runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert verified == EXPECTED_DECLARATIONS

negative_code, negative = run(NEGATIVE)
assert negative_code == 1 and negative["status"] == "failed"
assert negative["summary"]["obligations"] == positive["summary"]["obligations"] + 2 * len(FALSE_CLAIMS)
assert negative["summary"]["proven"] == negative["summary"]["obligations"] - len(FALSE_CLAIMS)
assert negative["summary"]["unproven"] == len(FALSE_CLAIMS)
assert negative == run(NEGATIVE)[1], "call-liveness false-claim report changed across repeated runs"
assert {(finding["kind"], finding["name"]) for finding in negative["findings"]} == {
    ("ensure-unproven", name) for name in FALSE_CLAIMS
}
flag_preservation_finding = next(
    finding for finding in negative["findings"]
    if finding["name"] == "call_preserves_live_flags"
)
assert flag_preservation_finding["status"] == "disproved"
assert flag_preservation_finding["counterexample_found"]
flag_counterexample = flag_preservation_finding["counterexample"]
assert len(flag_counterexample) == 1
counterexample_condition = flag_counterexample[0]
assert counterexample_condition.get("kind") == "binary"
assert counterexample_condition.get("operator") == "=="
assert counterexample_condition.get("left", {}).get("kind") == "ident"
assert counterexample_condition.get("left", {}).get("name") == "was_live"
assert counterexample_condition.get("right", {}).get("kind") == "bool"
assert counterexample_condition.get("right", {}).get("value") is True, \
    "flag-preservation control must fail on the live-flags input"
assert not FALSE_CLAIMS & {
    row["name"] for row in negative["declaration_details"] if row.get("verified")
}
assert require_current_product(BIN, PROVER) == manifest, "proof-product provenance changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "finite call liveness partition for return, stack, callee-saved, and caller-clobbered registers, out-of-range rejection, and unconditional live-flag reset",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(FALSE_CLAIMS),
    "proof_binary_sha256": hashlib.sha256(BIN.read_bytes()).hexdigest(),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
