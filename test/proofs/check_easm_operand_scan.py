"""Admit EASM operand parsing, operand-form checks, and conditional-target validation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure
from easm_operand_expectations import (
    expected_result_type,
    classifier_groups,
    expected_operand_arity,
    expected_mrs_form,
    expected_exact_register,
    expected_direct_target,
    role_expectations,
    required_label_lookup,
    positive_names,
    negative_names,
    scan_decl,
    expected_positive,
    expected_negative,
)


from source_guard_compat import expand_return_if_blocks
ROOT = Path(__file__).resolve().parents[2]
PROVER = ROOT.parent / "elisa-proof"
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve()
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
POSITIVE = HERE / "easm_operand_scan.elisa"
NEGATIVE = HERE / "easm_operand_scan_rejected.elisa"
POLICY = ROOT / "src/backend/easm_operand_scan.elisa"
INSTRUCTION_SCAN = ROOT / "src/backend/easm_operand_scan_instruction.elisa"
TEXT_SCAN = ROOT / "src/backend/easm_text_scan.elisa"
ENV = ROOT / "src/backend/codegen_env.elisa"
PROVENANCE = ROOT / "src/backend/easm_verify_provenance.elisa"
FUNCTION = ROOT / "src/backend/easm_verify_function.elisa"
MEMORY = ROOT / "src/backend/easm_verify_memory.elisa"
MODEL = ROOT / "src/backend/easm_model.elisa"
MASKS = ROOT / "src/backend/easm_register_masks.elisa"

parser = argparse.ArgumentParser()
parser.add_argument("--source-only", action="store_true",
                    help="check source and fixture bindings without invoking Elisa-Proof")
ARGS = parser.parse_args()

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(source: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in expand_return_if_blocks(source).splitlines())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)(?:ghost[ \t]+)?def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}(?:@|(?:ghost[ \t]+)?def )", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def function_body(source: str, name: str) -> str:
    section = function_section(source, name)
    colon = section.find(":\n")
    if colon < 0:
        raise SystemExit(f"could not find body of {name}")
    return section[colon + 2:]


def proof_body(source: str, name: str) -> str:
    return compact(function_body(source, name))


policy = POLICY.read_text()
instruction_scan = INSTRUCTION_SCAN.read_text()
if compact(expected_result_type) not in compact(policy):
    raise SystemExit("operand scanner lost its named instruction-scan result")
text_scan = TEXT_SCAN.read_text()
find_byte = compact(function_section(text_scan, "find_byte"))
for required in (
    "ensure result <= text.len",
    "ensure result == text.len or text[result] == needle",
    "ensure (forall candidate in 0..<result: text[candidate] != needle)",
    "while index < text.len",
    "invariant (forall candidate in 0..<index: text[candidate] != needle)",
    "return index if text[index] == needle",
):
    if compact(required) not in find_byte:
        raise SystemExit(f"single-byte scanner lost its first-match proof: {required}")
expected_policy_inventory = {
    "needs_arity_rejection", "is_zero_operand_instruction", "is_one_operand_instruction", "is_two_operand_instruction",
    "is_shift_instruction", "operand_arity_supported", "is_aarch64_mrs_form", "exact_register_form", "is_direct_control_target",
    "rejects_unmodeled_operand_form", "rejects_return_immediate", "rejects_unresolved_conditional_target", "first_operand_byte",
    "next_top_level_separator", "invalid_scan_result", "empty_scan_result", "scan_instruction",
}
actual_policy_inventory = set(re.findall(r"(?m)^\s*def ([A-Za-z_][A-Za-z0-9_]*)\(", policy + "\n" + instruction_scan))
if actual_policy_inventory != expected_policy_inventory:
    raise SystemExit("operand scanner declaration inventory changed")
if policy.count('include "./easm_operand_scan_instruction.elisa"') != 1:
    raise SystemExit("operand scanner must include its instruction scanner exactly once")

expected_arity = """
def needs_arity_rejection(operand_count: usize) -> bool:
    ensure result == (operand_count > MAX_MODELED_OPERAND_COUNT)
    return operand_count > MAX_MODELED_OPERAND_COUNT
"""
if compact(function_section(policy, "needs_arity_rejection")) != compact(expected_arity):
    raise SystemExit("operand arity policy no longer rejects exactly counts above the modeled limit")

for name, required in {
    "invalid_scan_result": (
        "requires start <= text_length",
        "ensure result.start == start",
        "ensure result.count == 0",
        "ensure result.first_separator == text_length and result.last_separator == text_length",
        "ensure not result.has_address_group",
        "ensure result.address_open == text_length and result.address_close == text_length",
        "ensure not result.valid",
        "return InstructionScanResult{start: start, count: 0, first_separator: text_length, last_separator: text_length, has_address_group: false, address_open: text_length, address_close: text_length, valid: false}",
    ),
    "empty_scan_result": (
        "ensure result.start == text_length",
        "ensure result.count == 0",
        "ensure result.first_separator == text_length and result.last_separator == text_length",
        "ensure not result.has_address_group",
        "ensure result.address_open == text_length and result.address_close == text_length",
        "ensure result.valid",
        "return InstructionScanResult{start: text_length, count: 0, first_separator: text_length, last_separator: text_length, has_address_group: false, address_open: text_length, address_close: text_length, valid: true}",
    ),
}.items():
    section = compact(function_section(policy, name))
    if any(compact(fragment) not in section for fragment in required):
        raise SystemExit(f"{name} no longer constructs its canonical instruction-scan sentinel")

for name, groups in classifier_groups.items():
    mnemonics = tuple(mnemonic for group in groups for mnemonic in group)
    expression = " or ".join(f'op == "{mnemonic}"' for mnemonic in mnemonics)
    expected = f"""
def {name}(op: sview) -> bool:
    ensure result == ( {expression} )
    return ( {expression} )
"""
    if compact(function_section(policy, name)) != compact(expected):
        raise SystemExit(f"{name} changed from its specified closed opcode set")

if compact(function_section(policy, "operand_arity_supported")) != compact(expected_operand_arity):
    raise SystemExit("instruction operand arity no longer matches the closed operation inventory")
zero_operand_mnemonics = tuple(mnemonic for group in classifier_groups["is_zero_operand_instruction"] for mnemonic in group)
known_op = compact(function_section(PROVENANCE.read_text(), "easm_known_op"))
if any(f'easm_equal(op,"{mnemonic}")' not in known_op for mnemonic in zero_operand_mnemonics):
    raise SystemExit("zero-operand classifier includes an opcode outside the production known-op set")

if compact(function_section(policy, "is_aarch64_mrs_form")) != compact(expected_mrs_form):
    raise SystemExit("AArch64 MRS policy must accept only cntvct_el0 and canonical X0-X30/XZR registers")

expected_unmodeled_form = """
def rejects_unmodeled_operand_form(operand_present: bool, memory_address: bool, register_operand: bool, immediate_operand: bool, direct_control_target: bool) -> bool:
    ensure result == (
        operand_present and not memory_address and not register_operand and
        not immediate_operand and not direct_control_target
    )
    return operand_present and not memory_address and not register_operand and not immediate_operand and not direct_control_target
"""
if compact(function_section(policy, "rejects_unmodeled_operand_form")) != compact(expected_unmodeled_form):
    raise SystemExit("production bare-operand rejection no longer matches its proved Boolean policy")
if compact(function_section(policy, "rejects_return_immediate")) != compact("""
def rejects_return_immediate(op: sview, immediate_operand: bool) -> bool:
    ensure result == (immediate_operand and (op == "ret" or op == "retq"))
    return immediate_operand and (op == "ret" or op == "retq")
"""):
    raise SystemExit("return-immediate rejection no longer matches its stack-adjustment policy")
if compact(function_section(policy, "rejects_unresolved_conditional_target")) != compact("""
def rejects_unresolved_conditional_target(is_conditional_jump: bool, target_is_local: bool, direct_control_capability: bool, relocation_symbol_capability: bool) -> bool:
    ensure result == (
        is_conditional_jump and not target_is_local and
        not direct_control_capability and not relocation_symbol_capability
    )
    return is_conditional_jump and not target_is_local and not direct_control_capability and not relocation_symbol_capability
"""):
    raise SystemExit("conditional branch fail-closed policy no longer requires a local target or explicit authorization")

if compact(function_section(policy, "exact_register_form")) != compact(expected_exact_register):
    raise SystemExit("register syntax classification must consume the whole direct or indirect register token")
if compact(function_section(policy, "is_direct_control_target")) != compact(expected_direct_target):
    raise SystemExit("direct control-target classifier no longer matches its exact target syntax and opcode set")

scanner = compact(function_section(instruction_scan, "scan_instruction"))
if compact("def scan_instruction(text: sview) -> InstructionScanResult:") not in scanner:
    raise SystemExit("instruction scan must return its named result record")
for required in (
    "first_space: i64 = EasmTextScan::first_space(text)",
    "assert first_space >= 0 and first_space <= text_length.i64()",
    "first_space_offset: usize = first_space.usize()",
    "assert first_space_offset <= text_length",
    "start: usize = first_operand_byte(text, first_space_offset)",
    "open_relative: usize = EasmTextScan::find_byte(operands, ASCII_LEFT_PAREN)",
    "close_relative: usize = EasmTextScan::find_byte(operands, ASCII_RIGHT_PAREN)",
    "return empty_scan_result(text_length)",
    "return invalid_scan_result(text_length, start)",
    "if close_relative < open_relative: return invalid_scan_result(text_length, start)",
    "if close_relative >= operands.len: return invalid_scan_result(text_length, start)",
    "close <- start + close_relative",
    "EasmTextScan::find_byte(address_contents, ASCII_LEFT_PAREN) < address_contents.len",
    "EasmTextScan::find_byte(trailing, ASCII_LEFT_PAREN) < trailing.len",
    "EasmTextScan::find_byte(trailing, ASCII_RIGHT_PAREN) < trailing.len",
    "assert start <= open",
    "assert open < close",
    "assert close < text_length",
    "assert text[open] == ASCII_LEFT_PAREN",
    "assert text[close] == ASCII_RIGHT_PAREN",
    "assert forall candidate in open + SCAN_STEP..<close: text[candidate] != ASCII_LEFT_PAREN and text[candidate] != ASCII_RIGHT_PAREN",
    "assert forall candidate in close + SCAN_STEP..<text_length: text[candidate] != ASCII_LEFT_PAREN and text[candidate] != ASCII_RIGHT_PAREN",
    "assert open == text_length",
    "assert close == text_length",
    "assert forall candidate in start..<text_length: text[candidate] != ASCII_LEFT_PAREN and text[candidate] != ASCII_RIGHT_PAREN",
    "first_separator: usize = next_top_level_separator(text, start, has_address, open, close)",
    "second_separator: usize = next_top_level_separator(text, first_separator + SCAN_STEP, has_address, open, close)",
    "many_scan: InstructionScanResult = InstructionScanResult{start: start, count: TOO_MANY_OPERANDS_SENTINEL, first_separator: first_separator, last_separator: second_separator, has_address_group: has_address, address_open: open, address_close: close, valid: true}",
    "assert single_scan.start == start",
    "assert single_scan.count == 1",
    "assert single_scan.first_separator == text_length",
    "assert single_scan.last_separator == text_length",
    "assert single_scan.has_address_group == has_address",
    "assert single_scan.address_open == open",
    "assert single_scan.address_close == close",
    "assert not single_scan.valid or single_scan.count != 1 or ( single_scan.first_separator == text.len and single_scan.last_separator == text.len",
    "return single_scan",
    "assert two_scan.start == start",
    "assert two_scan.count == 2",
    "assert two_scan.first_separator == first_separator",
    "assert two_scan.last_separator == first_separator",
    "assert two_scan.has_address_group == has_address",
    "assert two_scan.address_open == open",
    "assert two_scan.address_close == close",
    "assert not two_scan.valid or two_scan.count != 2 or ( two_scan.first_separator < text.len and two_scan.first_separator == two_scan.last_separator",
    "return two_scan",
    "assert many_scan.start == start",
    "assert many_scan.count == TOO_MANY_OPERANDS_SENTINEL",
    "assert many_scan.first_separator == first_separator",
    "assert many_scan.last_separator == second_separator",
    "assert many_scan.has_address_group == has_address",
    "assert many_scan.address_open == open",
    "assert many_scan.address_close == close",
    "assert not many_scan.valid or many_scan.count != TOO_MANY_OPERANDS_SENTINEL or ( many_scan.first_separator < many_scan.last_separator and many_scan.last_separator < text.len",
    "return many_scan",
    "ensure result.valid or ( result.count == 0 and result.first_separator == text.len and result.last_separator == text.len and not result.has_address_group and result.address_open == text.len and result.address_close == text.len )",
    "ensure result.valid and not result.has_address_group implies ( forall candidate in result.start..<text.len: text[candidate] != ASCII_LEFT_PAREN and text[candidate] != ASCII_RIGHT_PAREN )",
    "ensure result.valid and result.has_address_group implies ( forall candidate in result.start..<result.address_open: text[candidate] != ASCII_LEFT_PAREN and text[candidate] != ASCII_RIGHT_PAREN )",
    "ensure result.valid and result.has_address_group implies ( forall candidate in result.address_open + SCAN_STEP..<result.address_close: text[candidate] != ASCII_LEFT_PAREN and text[candidate] != ASCII_RIGHT_PAREN )",
    "ensure result.valid and result.has_address_group implies ( forall candidate in result.address_close + SCAN_STEP..<text.len: text[candidate] != ASCII_LEFT_PAREN and text[candidate] != ASCII_RIGHT_PAREN )",
    "ensure result.valid and result.count == 0 implies ( result.start == text.len and result.first_separator == text.len and result.last_separator == text.len and not result.has_address_group and result.address_open == text.len and result.address_close == text.len )",
    "ensure result.valid and result.count == 1 implies ( result.first_separator == text.len and result.last_separator == text.len and result.start < text.len and first_operand_byte(text[result.start:text.len], 0.usize()) < (text[result.start:text.len]).len and next_top_level_separator(text, result.start, result.has_address_group, result.address_open, result.address_close) == text.len )",
    "ensure result.valid and result.count == 2 implies ( result.first_separator < text.len and result.first_separator == result.last_separator and result.first_separator == next_top_level_separator(text, result.start, result.has_address_group, result.address_open, result.address_close) and next_top_level_separator(text, result.first_separator + SCAN_STEP, result.has_address_group, result.address_open, result.address_close) == text.len",
    "ensure result.valid and result.count == TOO_MANY_OPERANDS_SENTINEL implies ( result.first_separator < result.last_separator and result.last_separator < text.len and result.first_separator == next_top_level_separator(text, result.start, result.has_address_group, result.address_open, result.address_close) and result.last_separator == next_top_level_separator(text, result.first_separator + SCAN_STEP, result.has_address_group, result.address_open, result.address_close)",
):
    if compact(required) not in scanner:
        raise SystemExit(f"operand scanner lost fail-closed grouping logic: {required}")
first_operand_scan = compact(function_section(policy, "first_operand_byte"))
for required in (
    "requires from <= text.len",
    "ensure result >= from and result <= text.len",
    "ensure result == text.len or (text[result] != ASCII_SPACE and text[result] != ASCII_TAB)",
    "ensure (forall candidate in from..<result: text[candidate] == ASCII_SPACE or text[candidate] == ASCII_TAB)",
    "suffix: sview = text[from:text_length]",
    "bounds: (start: usize, end: usize) = EasmTextScan::trim_bounds(suffix)",
    "offset: usize = bounds.start",
    "assert from + offset <= text_length",
    "return from + offset",
):
    if compact(required) not in first_operand_scan:
        raise SystemExit("leading-whitespace scanner no longer refines the bounded trim span")
next_separator = compact(function_section(policy, "next_top_level_separator"))
for required in (
    "ensure result >= from",
    "result >= from and text[result] == ASCII_COMMA",
    "forall candidate in from..<result",
    "if from == text_length: return text_length",
    "EasmTextScan::find_byte(suffix, ASCII_COMMA)",
    "EasmTextScan::find_byte(before_address, ASCII_COMMA)",
    "EasmTextScan::find_byte(after_address, ASCII_COMMA)",
    "return found_before",
    "return found_after",
    "return text_length",
):
    if compact(required) not in next_separator:
        raise SystemExit(f"top-level separator search lost its bounded first-match composition: {required}")

environment = ENV.read_text()
if environment.index('include "easm_text_scan.elisa"') > environment.index('include "easm_operand_scan.elisa"') or \
        environment.index('include "easm_operand_scan.elisa"') > environment.index('include "easm_verify_provenance.elisa"'):
    raise SystemExit("operand scanner must be imported before its verifier consumers")

expected_first = """
def easm_first_operand(text: sview) -> sview:
    scan: EasmOperandScan::InstructionScanResult = EasmOperandScan::scan_instruction(text)
    if not scan.valid or scan.count == 0:
        return ""
    if scan.first_separator < text.len:
        return easm_trim(text[scan.start:scan.first_separator])
    return easm_trim(text[scan.start:text.len])
"""
expected_last = """
def easm_last_operand(text: sview) -> sview:
    scan: EasmOperandScan::InstructionScanResult = EasmOperandScan::scan_instruction(text)
    if not scan.valid or scan.count == 0:
        return ""
    if scan.last_separator < text.len:
        return easm_trim(text[scan.last_separator + 1.usize():text.len])
    return easm_trim(text[scan.start:text.len])
"""
if compact(function_section(PROVENANCE.read_text(), "easm_first_operand")) != compact(expected_first):
    raise SystemExit("first-operand parsing no longer uses the proved top-level separator scan")
if compact(function_section(PROVENANCE.read_text(), "easm_last_operand")) != compact(expected_last):
    raise SystemExit("last-operand parsing no longer uses the proved top-level separator scan")

instruction_check = function_section(FUNCTION.read_text(), "verify_function_instructions")
instruction_code = compact(instruction_check)
arity_check = compact("if unsupported_operands: issues.push(Issue{severity: Severity.Error, code: \"unsupported-operands\", line: inst.line, message: \"instruction operand shape is outside the verified EASM model\"}) continue")
if arity_check not in instruction_code:
    raise SystemExit("instruction verification must reject unsupported operand counts and roles on executable instructions")
if instruction_code.index(compact("if operand_scan.valid and operand_scan.count > 0 and operand_scan.count <= EasmOperandScan::MAX_MODELED_OPERAND_COUNT")) > instruction_code.index(arity_check):
    raise SystemExit("operand roles must be checked only after their source and destination slices have been extracted")
if compact("unsupported_operands: mutable bool = not operand_scan.valid or EasmOperandScan::needs_arity_rejection(operand_scan.count)") not in instruction_code:
    raise SystemExit("invalid scans and excessive operand counts must fail before opcode-specific role checks")
arity_role_check = "unsupported_operands <- not EasmOperandScan::operand_arity_supported(inst.op, operand_scan.count) unsupported_operands <- not easm_instruction_operand_roles_supported(inst.op, operand_scan.count, source_operand, destination_operand) if not unsupported_operands"
if compact(arity_role_check) not in instruction_code:
    raise SystemExit("opcode role checks must short-circuit after an unsupported arity")
if instruction_code.index("needs_arity_rejection(operand_scan.count)") > instruction_code.index(compact("capability: sview = easm_required_capability(inst.op)")):
    raise SystemExit("operand arity rejection must precede all per-instruction effect analysis")
for required in (
    "if operand_scan.valid and operand_scan.count > 0 and operand_scan.count <= EasmOperandScan::MAX_MODELED_OPERAND_COUNT: source_end: usize = operand_scan.first_separator if operand_scan.first_separator < inst.text.len else inst.text.len",
    "source_operand <- easm_substitute_operand(easm_trim(inst.text[operand_scan.start:source_end]), inst)",
    "destination_start: usize = operand_scan.last_separator + 1.usize() if operand_scan.last_separator < inst.text.len else operand_scan.start",
    "destination_operand <- easm_substitute_operand(easm_trim(inst.text[destination_start:inst.text.len]), inst)",
    "unmodeled_operand <- true if operand_scan.count == 2 and source_memory_operand and destination_memory_operand",
    "unmodeled_operand <- true if is_lea and (operand_scan.count != 2 or not source_memory_operand or not lea_destination_is_direct_register)",
    "not EasmOperandScan::operand_arity_supported(inst.op, operand_scan.count)",
    "not easm_instruction_operand_roles_supported(inst.op, operand_scan.count, source_operand, destination_operand)",
    "operand: sview = source_operand if operand_index == 0 else destination_operand",
    "is_final_operand: bool = operand_index == 1 or operand_scan.count == 1",
    "register_operand: bool = EasmOperandScan::exact_register_form(operand, parsed_register)",
    "immediate_operand: bool = operand[0] == EasmOperandScan::ASCII_DOLLAR",
    "direct_target: bool = EasmOperandScan::is_direct_control_target(inst.op, operand, is_final_operand)",
    "EasmOperandScan::rejects_unmodeled_operand_form(",
    "EasmOperandScan::rejects_return_immediate(inst.op, immediate_operand)",
    'code: "unsupported-operand-form"',
):
    if compact(required) not in instruction_code:
        raise SystemExit(f"instruction validation lost an operand-form guard: {required}")
if instruction_code.index("unsupported-operand-form") > instruction_code.index(compact("capability: sview = easm_required_capability(inst.op)")):
    raise SystemExit("operand-form rejection must precede all per-instruction effect analysis")
role_source = FUNCTION.read_text()
for helper, expected_fragment in role_expectations.items():
    if compact(expected_fragment) not in compact(function_section(role_source, helper)):
        raise SystemExit(f"instruction role validation changed its {helper} register/operand rule")
role_body = compact(function_section(role_source, "easm_instruction_operand_roles_supported"))
for expected_fragment in (
    "if (op == \"inc\" or op == \"incq\" or op == \"dec\" or op == \"decq\" or op == \"neg\" or op == \"negq\" or op == \"not\" or op == \"notq\"): return easm_operand_is_writable(destination)",
    "if op == \"fldcw\" or op == \"ldmxcsr\": return easm_operand_is_supported_memory(source) if op == \"fnstcw\" or op == \"stmxcsr\": return easm_operand_is_supported_memory(destination)",
    "shift_count_is_valid: bool = easm_operand_is_immediate(source) or (easm_operand_is_direct_register(source) and easm_register_operand(source) == \"cl\") return shift_count_is_valid and easm_operand_is_writable(destination)",
    "if op == \"call\" or op == \"callq\" or op == \"jmp\" or op == \"jmpq\": return easm_operand_is_control_target(op, destination)",
    "if op == \"mrs\": return false",
    "if (op == \"je\" or op == \"jz\" or op == \"jne\" or op == \"jnz\" or op == \"jl\" or op == \"jle\" or op == \"jg\" or op == \"jge\" or op == \"jb\" or op == \"jbe\" or op == \"ja\" or op == \"jae\"): return EasmOperandScan::is_direct_control_target(op, destination, true)",
    "if easm_is_move_operation(op): return easm_move_operand_roles_supported(source, destination)",
    "if easm_is_extension_move(op): return (not easm_operand_is_immediate(source)) and easm_operand_is_direct_register(destination) and easm_operand_is_data_source(source)",
    "return easm_operand_is_writable(source) and easm_operand_is_writable(destination) and not (easm_memory_operand(source) and easm_memory_operand(destination))",
    "return easm_operand_is_data_source(source) and easm_operand_is_writable(destination)",
):
    if compact(expected_fragment) not in role_body:
        raise SystemExit("instruction role validation lost a push/unary/FPU/shift/control/move/binary operand rule")
register_bit_body = compact(function_section(MODEL.read_text(), "easm_register_bit"))
if register_bit_body != compact("""
def easm_register_bit(register: sview) -> i64:
    ensure result == EasmRegisterMasks::register_bit(register)
    return EasmRegisterMasks::register_bit(register)
"""):
    raise SystemExit("register lookup no longer delegates exactly to the canonical EASM register map")
register_bit_source = compact(MASKS.read_text())
if compact("_ -> result == 0") not in register_bit_source or compact("_: 0") not in register_bit_source:
    raise SystemExit("unknown register names must map to no modeled register bit")
if "EasmOperandScan::is_aarch64_mrs_form" in role_body:
    raise SystemExit("executable MRS must fail closed until its AArch64 register effects are modeled")
conditional_target_check = "if EasmOperandScan::rejects_unresolved_conditional_target( easm_is_conditional_jump(inst.op), target_is_local, easm_contract_has_word(fn.requires, \"control.direct\"), easm_contract_has_word(fn.requires, \"relocation.symbol\") ): issues.push(Issue{severity: Severity.Error, code: \"unknown-label\", line: inst.line, message: \"conditional jump target is not a declared local label\"})"
if compact(conditional_target_check) not in instruction_code:
    raise SystemExit("conditional branches must reject unmodeled targets before CFG propagation")
if instruction_code.index(compact("target_is_local: bool = easm_label_index(fn.instructions, control_target) >= 0")) > instruction_code.index(compact(conditional_target_check)):
    raise SystemExit("conditional target validation must derive local-target status from the function's labels")
label_index = compact(function_section(MODEL.read_text(), "easm_label_index"))
if any(compact(fragment) not in label_index for fragment in required_label_lookup) or not label_index.endswith("return-1"):
    raise SystemExit("conditional target lookup lost its bounded first-match or unresolved-label behavior")
conditional_classifier = compact(function_section(MODEL.read_text(), "easm_is_conditional_jump"))
if conditional_classifier != compact("""
def easm_is_conditional_jump(op: sview) -> bool:
    ensure result == (easm_starts(op, "j") and not easm_equal(op, "jmp") and not easm_equal(op, "jmpq"))
    return easm_starts(op, "j") and not easm_equal(op, "jmp") and not easm_equal(op, "jmpq")
"""):
    raise SystemExit("conditional branch target guard must cover the production conditional-jump classifier")
one_function = compact(function_section(FUNCTION.read_text(), "verify_one_function"))
function_compositions = compact(function_section(FUNCTION.read_text(), "verify_function_compositions"))
module_compositions = compact(function_section(FUNCTION.read_text(), "verify_module_compositions"))
module_verifier = compact(function_section(FUNCTION.read_text(), "verify_module"))
if compact("verify_function_instructions(fn, issues, stack_delta, stack_touched, stack_known, uses_call, writes_segment_any)") not in one_function:
    raise SystemExit("conditional-target diagnostics are not connected to function verification")
if compact("verify_control_flow_merges(fn, issues)") not in function_compositions or \
        compact("verify_function_compositions(fn, module.fragments, issues)") not in module_compositions:
    raise SystemExit("local target validation no longer precedes control-flow merge analysis")
if module_verifier.index(compact("verify_module_functions(module, issues)")) > module_verifier.index(compact("verify_module_compositions(module, issues)")):
    raise SystemExit("function target diagnostics must run before CFG propagation consumes labels")

memory_roles = function_section(MEMORY.read_text(), "easm_verify_memory_roles")
memory_code = compact(memory_roles)
memory_arity = compact("operand_scan: EasmOperandScan::InstructionScanResult = EasmOperandScan::scan_instruction(instruction.text) continue if not operand_scan.valid or EasmOperandScan::needs_arity_rejection(operand_scan.count)")
if memory_arity not in memory_code:
    raise SystemExit("memory provenance scan must skip unsupported operand shapes before checking first/last operands")
if memory_code.index("needs_arity_rejection(operand_scan.count)") > memory_code.index(compact("for operand_index in 0..<operand_scan.count")):
    raise SystemExit("memory-address validation must fail closed before using first/last operand projections")
if compact("operand: sview = easm_substitute_operand(raw_operand, instruction)") not in memory_code:
    raise SystemExit("memory-base and layout checks must inspect fragment-substituted operands")
if "easm_memory_base_register(operand)" not in memory_code or compact("continue if not easm_memory_operand(operand)") not in memory_code:
    raise SystemExit("the raw-carrier pass must visit every substituted memory operand")

for path, expected, label in ((POSITIVE, positive_names, "positive"), (NEGATIVE, negative_names, "negative")):
    source = path.read_text()
    actual = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", source))
    if actual != expected:
        raise SystemExit(f"{label} proof declarations changed")
    if 'include "../../src/backend/easm_operand_scan.elisa"' not in source and path == POSITIVE:
        raise SystemExit("positive proof no longer imports the production operand scanner")

positive_text = POSITIVE.read_text()
for name, expected in expected_positive.items():
    if proof_body(positive_text, name) != compact(expected):
        raise SystemExit(f"positive scanner theorem changed: {name}")

negative_text = NEGATIVE.read_text()
for name, expected in expected_negative.items():
    if proof_body(negative_text, name) != compact(expected):
        raise SystemExit(f"negative scanner false-claim control changed: {name}")

source_closure = source_include_closure([POSITIVE, NEGATIVE])
if ARGS.source_only:
    print(json.dumps({"source_bound": True, "positive": len(positive_names),
                      "false_claim_controls": len(negative_names),
                      "source_closure_files": len(source_closure)}, sort_keys=True))
    raise SystemExit(0)

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("EASM operand scanner proof requires a strict proof build")
compiler_head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], check=True,
                               capture_output=True, text=True).stdout.strip()
if compiler_head != manifest["compiler"]["source_revision"]:
    raise SystemExit("proof product was built from a different compiler revision")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", HERE / "easm_operand_expectations.py", POSITIVE, NEGATIVE,
    POLICY, INSTRUCTION_SCAN, ENV, PROVENANCE, FUNCTION, MEMORY, MODEL, MASKS,
]
inputs.extend(source_closure)
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True, text=True, timeout=60)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "proof report changed across repeated runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert positive_names <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["obligations"] - negative["summary"]["proven"] == len(negative_names)
assert {(finding["kind"], finding["name"]) for finding in negative["findings"]} == {
    ("ensure-unproven", name) for name in negative_names
}
assert not negative_names & {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert require_current_product(BIN, PROVER) == manifest, "proof-product provenance changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "EASM operand grouping and form checks, conditional target validation, fail-closed arity",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(negative_names),
    "proof_binary_sha256": hashlib.sha256(BIN.read_bytes()).hexdigest(),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
