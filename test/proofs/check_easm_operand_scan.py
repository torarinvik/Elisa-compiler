"""Admit EASM operand parsing, operand-form checks, and conditional-target validation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


from source_guard_compat import expand_return_if_blocks
ROOT = Path(__file__).resolve().parents[2]
PROVER = ROOT.parent / "elisa-proof"
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve()
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
POSITIVE = HERE / "easm_operand_scan.elisa"
NEGATIVE = HERE / "easm_operand_scan_rejected.elisa"
POLICY = ROOT / "src/backend/easm_operand_scan.elisa"
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
expected_policy_inventory = {
    "needs_arity_rejection", "is_zero_operand_instruction", "is_one_operand_instruction", "is_two_operand_instruction",
    "is_shift_instruction", "operand_arity_supported", "is_aarch64_mrs_form", "exact_register_form", "is_direct_control_target",
    "rejects_unmodeled_operand_form", "rejects_return_immediate", "rejects_unresolved_conditional_target", "first_operand_byte",
    "next_top_level_separator", "scan_instruction",
}
actual_policy_inventory = set(re.findall(r"(?m)^\s*def ([A-Za-z_][A-Za-z0-9_]*)\(", policy))
if actual_policy_inventory != expected_policy_inventory:
    raise SystemExit("operand scanner declaration inventory changed")

expected_arity = """
def needs_arity_rejection(operand_count: usize) -> bool:
    ensure result == (operand_count > MAX_MODELED_OPERAND_COUNT)
    return operand_count > MAX_MODELED_OPERAND_COUNT
"""
if compact(function_section(policy, "needs_arity_rejection")) != compact(expected_arity):
    raise SystemExit("operand arity policy no longer rejects exactly counts above the modeled limit")

classifier_groups = {
    "is_zero_operand_instruction": (
        ("ret", "retq", "cpuid", "cld", "std"),
        ("lfence", "rdtsc", "pause", "yield", "isb"),
        ("emms", "vzeroall", "trap"),
    ),
    "is_one_operand_instruction": (
        ("push", "pushq", "pop", "popq"),
        ("inc", "incq", "dec", "decq", "neg", "negq", "not", "notq"),
        ("call", "callq", "jmp", "jmpq"),
        ("je", "jz", "jne", "jnz", "jl", "jle", "jg", "jge", "jb", "jbe", "ja", "jae"),
        ("fldcw", "fnstcw", "stmxcsr", "ldmxcsr"),
    ),
    "is_two_operand_instruction": (
        ("mov", "movq", "movb", "movw", "movl"),
        ("movsx", "movsxd", "movsbw", "movsbl", "movsbq", "movswl", "movswq", "movslq"),
        ("movzx", "movzbw", "movzbl", "movzbq", "movzwl", "movzwq"),
        ("lea", "leaq", "xchg", "xchgl", "xchgq"),
        ("add", "addq", "sub", "subq"),
        ("and", "andq", "or", "orq", "xor", "xorq"),
        ("cmp", "cmpq", "test", "testq", "mrs"),
    ),
    "is_shift_instruction": (("shl", "shlq", "sal", "salq", "shr", "shrq", "sar", "sarq"),),
}
for name, groups in classifier_groups.items():
    mnemonics = tuple(mnemonic for group in groups for mnemonic in group)
    expression = " or ".join(f'op == "{mnemonic}"' for mnemonic in mnemonics)
    match_rows = "\n".join(
        "                " + " | ".join(f'"{mnemonic}"' for mnemonic in group) + ": true"
        for group in groups
    )
    expected = f"""
def {name}(op: sview) -> bool:
    ensure result == ( {expression} )
    return match op:
{match_rows}
                _: false
"""
    if compact(function_section(policy, name)) != compact(expected):
        raise SystemExit(f"{name} changed from its specified closed opcode set")

expected_operand_arity = """
def operand_arity_supported(op: sview, operand_count: usize) -> bool:
    ensure result == (
        (is_zero_operand_instruction(op) and operand_count == 0) or
        (not is_zero_operand_instruction(op) and is_one_operand_instruction(op) and operand_count == 1) or
        (not is_zero_operand_instruction(op) and not is_one_operand_instruction(op) and is_two_operand_instruction(op) and operand_count == 2) or
        (not is_zero_operand_instruction(op) and not is_one_operand_instruction(op) and not is_two_operand_instruction(op) and is_shift_instruction(op) and (operand_count == 1 or operand_count == 2))
    )
    if is_zero_operand_instruction(op):
        return operand_count == 0
    if is_one_operand_instruction(op):
        return operand_count == 1
    if is_two_operand_instruction(op):
        return operand_count == 2
    if is_shift_instruction(op):
        return operand_count == 1 or operand_count == 2
    return false
"""
if compact(function_section(policy, "operand_arity_supported")) != compact(expected_operand_arity):
    raise SystemExit("instruction operand arity no longer matches the closed operation inventory")
zero_operand_mnemonics = tuple(mnemonic for group in classifier_groups["is_zero_operand_instruction"] for mnemonic in group)
known_op = compact(function_section(PROVENANCE.read_text(), "easm_known_op"))
if any(f'easm_equal(op,"{mnemonic}")' not in known_op for mnemonic in zero_operand_mnemonics):
    raise SystemExit("zero-operand classifier includes an opcode outside the production known-op set")

expected_mrs_form = """
def is_aarch64_mrs_form(result_register: sview, system_register: sview) -> bool:
    ensure result == (
        system_register == "cntvct_el0" and
        (result_register == "xzr" or
            (result_register.len == 2 and result_register[0] == ASCII_X and
                result_register[1] >= ASCII_ZERO and result_register[1] <= ASCII_NINE) or
            (result_register.len == 3 and result_register[0] == ASCII_X and
                (((result_register[1] == ASCII_ONE or result_register[1] == ASCII_TWO) and
                    result_register[2] >= ASCII_ZERO and result_register[2] <= ASCII_NINE) or
                    (result_register[1] == ASCII_THREE and result_register[2] == ASCII_ZERO)))
        )
    )
    if system_register != "cntvct_el0":
        return false
    if result_register == "xzr":
        return true
    if result_register.len == 2 and result_register[0] == ASCII_X:
        return result_register[1] >= ASCII_ZERO and result_register[1] <= ASCII_NINE
    if result_register.len == 3 and result_register[0] == ASCII_X:
        return ((result_register[1] == ASCII_ONE and result_register[2] >= ASCII_ZERO and result_register[2] <= ASCII_NINE) or
            (result_register[1] == ASCII_TWO and result_register[2] >= ASCII_ZERO and result_register[2] <= ASCII_NINE) or
            (result_register[1] == ASCII_THREE and result_register[2] == ASCII_ZERO))
    return false
"""
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

expected_exact_register = """
def exact_register_form(operand: sview, register_name: sview) -> bool:
    ensure result == (
        (operand.len == register_name.len + SCAN_STEP and
            operand.len > 0 and operand[0] == ASCII_PERCENT and
            operand[SCAN_STEP:operand.len] == register_name) or
        (operand.len == register_name.len + INDIRECT_REGISTER_PREFIX_LENGTH and
            operand.len >= INDIRECT_REGISTER_PREFIX_LENGTH and operand[0] == ASCII_STAR and
            operand[1] == ASCII_PERCENT and
            operand[INDIRECT_REGISTER_PREFIX_LENGTH:operand.len] == register_name)
    )
    return (
        (operand.len == register_name.len + SCAN_STEP and
            operand.len > 0 and operand[0] == ASCII_PERCENT and
            operand[SCAN_STEP:operand.len] == register_name) or
        (operand.len == register_name.len + INDIRECT_REGISTER_PREFIX_LENGTH and
            operand.len >= INDIRECT_REGISTER_PREFIX_LENGTH and operand[0] == ASCII_STAR and
            operand[1] == ASCII_PERCENT and
            operand[INDIRECT_REGISTER_PREFIX_LENGTH:operand.len] == register_name)
    )
"""
if compact(function_section(policy, "exact_register_form")) != compact(expected_exact_register):
    raise SystemExit("register syntax classification must consume the whole direct or indirect register token")
expected_direct_target = """
def is_direct_control_target(op: sview, operand: sview, is_final_operand: bool) -> bool:
    ensure result == (
        is_final_operand and operand.len > 0 and
        operand[0] != ASCII_PERCENT and operand[0] != ASCII_DOLLAR and
        operand[0] != ASCII_STAR and operand[0] != ASCII_LEFT_PAREN and
        operand[0] != ASCII_LEFT_BRACKET and
        EasmTextScan::find(operand, ":") == operand.len and
        (op == "call" or op == "callq" or op == "jmp" or op == "jmpq" or
            op == "je" or op == "jz" or op == "jne" or op == "jnz" or
            op == "jl" or op == "jle" or op == "jg" or op == "jge" or
            op == "jb" or op == "jbe" or op == "ja" or op == "jae")
    )
    return is_final_operand and operand.len > 0 and operand[0] != ASCII_PERCENT and operand[0] != ASCII_DOLLAR and operand[0] != ASCII_STAR and operand[0] != ASCII_LEFT_PAREN and operand[0] != ASCII_LEFT_BRACKET and EasmTextScan::find(operand, ":") == operand.len and (op == "call" or op == "callq" or op == "jmp" or op == "jmpq" or op == "je" or op == "jz" or op == "jne" or op == "jnz" or op == "jl" or op == "jle" or op == "jg" or op == "jge" or op == "jb" or op == "jbe" or op == "ja" or op == "jae")
"""
if compact(function_section(policy, "is_direct_control_target")) != compact(expected_direct_target):
    raise SystemExit("direct control-target classifier no longer matches its exact target syntax and opcode set")

scanner = compact(function_section(policy, "scan_instruction"))
for required in (
    "start: usize = first_operand_byte(text, EasmTextScan::first_space(text).usize())",
    'open_relative: usize = EasmTextScan::find(operands, "(")',
    'close_relative: usize = EasmTextScan::find(operands, ")")',
    'if close_relative >= operands.len: return (start, 0, text_length, text_length, false, text_length, text_length, false)',
    'close_after_open: usize = EasmTextScan::find(after_open, ")")',
    'EasmTextScan::find(address_contents, "(") < address_contents.len',
    'EasmTextScan::find(trailing, "(") < trailing.len',
    'EasmTextScan::find(trailing, ")") < trailing.len',
    "first_separator: usize = next_top_level_separator(text, start, has_address, open, close)",
    "second_separator: usize = next_top_level_separator(text, first_separator + SCAN_STEP, has_address, open, close)",
    "return (start, TOO_MANY_OPERANDS_SENTINEL, first_separator, second_separator, has_address, open, close, true)",
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
if compact("decreases text_length - index") not in first_operand_scan or compact("invariant from <= index and index <= text_length") not in first_operand_scan:
    raise SystemExit("leading-whitespace scan no longer has a bounded progress argument")
next_separator = compact(function_section(policy, "next_top_level_separator"))
for required in (
    "ensure result >= from",
    "result >= from and text[result] == ASCII_COMMA",
    "forall candidate in from..<result",
    "while index < text_length",
    "invariant from <= index and index <= text_length",
    "invariant (forall candidate in from..<index",
    "return index if text[index] == ASCII_COMMA and (not has_address or index < open or index > close)",
):
    if compact(required) not in next_separator:
        raise SystemExit(f"top-level separator search lost its first-match contract: {required}")

environment = ENV.read_text()
if environment.index('include "easm_text_scan.elisa"') > environment.index('include "easm_operand_scan.elisa"') or \
        environment.index('include "easm_operand_scan.elisa"') > environment.index('include "easm_verify_provenance.elisa"'):
    raise SystemExit("operand scanner must be imported before its verifier consumers")

expected_first = """
def easm_first_operand(text: sview) -> sview:
    scan: (start: usize, count: usize, first_separator: usize, last_separator: usize, has_address_group: bool, address_open: usize, address_close: usize, valid: bool) = EasmOperandScan::scan_instruction(text)
    if not scan.valid or scan.count == 0:
        return ""
    if scan.first_separator < text.len:
        return easm_trim(text[scan.start:scan.first_separator])
    return easm_trim(text[scan.start:text.len])
"""
expected_last = """
def easm_last_operand(text: sview) -> sview:
    scan: (start: usize, count: usize, first_separator: usize, last_separator: usize, has_address_group: bool, address_open: usize, address_close: usize, valid: bool) = EasmOperandScan::scan_instruction(text)
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
role_expectations = {
    "easm_operand_is_direct_register": "return operand.len > 0 and operand[0] == EasmOperandScan::ASCII_PERCENT and EasmOperandScan::exact_register_form(operand, register) and easm_register_bit(register) != 0",
    "easm_operand_is_segment_register": 'return operand == "%fs" or operand == "%gs"',
    "easm_operand_is_supported_memory": 'base_supported: bool = base == "" or base == "rip" or easm_register_bit(base) != 0 index_supported: bool = index == "" or (easm_register_bit(index) != 0 and easm_register_bit(index) != EasmRegisterMasks::RSP) return base_supported and index_supported',
    "easm_operand_is_data_source": "return easm_operand_is_direct_register(operand) or easm_operand_is_supported_memory(operand) or easm_operand_is_immediate(operand)",
    "easm_operand_is_writable": "return easm_operand_is_direct_register(operand) or easm_operand_is_supported_memory(operand)",
    "easm_move_operand_roles_supported": "false return if source_segment and destination_segment if source_segment: return easm_operand_is_writable(destination) if destination_segment: return (easm_operand_is_direct_register(source) or easm_operand_is_supported_memory(source)) and not easm_operand_is_immediate(source) return easm_operand_is_data_source(source) and easm_operand_is_writable(destination)",
    "easm_operand_is_control_target": "true return if EasmOperandScan::is_direct_control_target(op, operand, true) and not easm_memory_operand(operand) false return if not easm_is_call_or_unconditional_jump(op) false return if operand.len < EasmOperandScan::INDIRECT_REGISTER_PREFIX_LENGTH or operand[0] != EasmOperandScan::ASCII_STAR indirect_operand: sview = easm_trim(operand[1:operand.len]) return easm_operand_is_direct_register(indirect_operand) or easm_operand_is_supported_memory(indirect_operand)",
    "easm_instruction_operand_roles_supported": "if op == \"push\" or op == \"pushq\": return easm_operand_is_data_source(source) or easm_operand_is_segment_register(source) if op == \"pop\" or op == \"popq\": return easm_operand_is_writable(destination) or easm_operand_is_segment_register(destination)",
}
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
required_label_lookup = (
    "return -1 if count_signed < 0 or count_signed.usize() != count",
    "for index in 0..<count |instructions, target|:",
    "invariant index <= count",
    "invariant forall prior in 0..<index: not easm_equal(easm_label_name(instructions[prior]), target)",
    "if easm_equal(easm_label_name(instructions[index]), target): return index.i64()",
)
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
memory_arity = compact("operand_scan: (start: usize, count: usize, first_separator: usize, last_separator: usize, has_address_group: bool, address_open: usize, address_close: usize, valid: bool) = EasmOperandScan::scan_instruction(instruction.text) continue if not operand_scan.valid or EasmOperandScan::needs_arity_rejection(operand_scan.count)")
if memory_arity not in memory_code:
    raise SystemExit("memory provenance scan must skip unsupported operand shapes before checking first/last operands")
if memory_code.index("needs_arity_rejection(operand_scan.count)") > memory_code.index(compact("for operand_index in 0..<operand_scan.count")):
    raise SystemExit("memory-address validation must fail closed before using first/last operand projections")
if compact("operand: sview = easm_substitute_operand(raw_operand, instruction)") not in memory_code:
    raise SystemExit("memory-base and layout checks must inspect fragment-substituted operands")
if "easm_memory_base_register(operand)" not in memory_code or compact("continue if not easm_memory_operand(operand)") not in memory_code:
    raise SystemExit("the raw-carrier pass must visit every substituted memory operand")

positive_names = {
    "indexed_address_commas_stay_inside_one_operand",
    "three_top_level_operands_exceed_the_modeled_limit",
    "a_single_indexed_memory_operand_has_arity_one",
    "unmatched_address_parenthesis_fails_closed",
    "unmatched_closing_parenthesis_fails_closed",
    "nested_address_parentheses_fail_closed",
    "no_operand_instruction_has_zero_operands",
    "scan_records_exact_top_level_separator_prefix",
    "valid_scan_exposes_only_its_delimited_address_pair",
    "first_operand_byte_is_the_least_non_whitespace",
    "next_separator_is_the_first_comma_outside_address",
    "zero_operand_opcode_classifier_matches_its_exact_set",
    "modeled_arity_matches_zero_operand_opcode_class",
    "zero_operand_ret_arity_is_accepted",
    "unary_push_arity_is_accepted",
    "binary_move_arity_is_accepted",
    "one_operand_shift_arity_is_accepted",
    "two_operand_shift_arity_is_accepted",
    "mrs_arity_is_binary",
    "direct_register_token_is_recognized_exactly",
    "indirect_register_token_is_recognized_exactly",
    "segment_address_is_not_a_register_token",
    "exact_register_form_matches_its_complete_token_equation",
    "direct_control_target_classifier_matches_its_exact_set",
    "direct_call_symbol_target_is_classified_as_control",
    "conditional_symbol_target_is_classified_as_control",
    "aarch64_mrs_form_classifier_matches_x0_through_x30_and_xzr",
    "mrs_accepts_low_x_register",
    "mrs_accepts_high_x_register",
    "mrs_accepts_zero_register",
    "bare_symbol_data_operands_are_rejected",
    "direct_call_symbol_targets_are_exempt_from_data_operand_rejection",
    "register_immediate_and_address_operands_are_modeled",
    "immediate_return_operands_are_rejected",
    "conditional_jump_targets_require_local_labels_or_explicit_authorization",
    "segment_address_is_not_an_exact_register_operand",
}
negative_names = {
    "indexed_address_has_four_operands",
    "three_top_level_operands_are_supported",
    "unmatched_address_parenthesis_is_valid",
    "invalid_scan_preserves_address_group_metadata",
    "zero_operand_scan_has_non_sentinel_separator",
    "single_operand_scan_has_an_empty_operand",
    "next_separator_selects_a_comma_inside_address",
    "cpuid_is_not_a_zero_operand_instruction",
    "movq_is_a_zero_operand_instruction",
    "movq_with_one_operand_is_accepted",
    "incq_with_two_operands_is_accepted",
    "mrs_with_one_operand_is_accepted",
    "register_suffix_is_accepted_as_the_exact_register",
    "bare_register_name_is_accepted_as_att_syntax",
    "register_operand_is_classified_as_a_direct_target",
    "immediate_operand_is_classified_as_a_direct_target",
    "nonfinal_symbol_is_classified_as_a_direct_target",
    "mrs_accepts_x31",
    "mrs_accepts_zero_padded_x09",
    "mrs_accepts_general_purpose_w_register",
    "mrs_accepts_unsupported_system_register",
    "nested_address_parentheses_are_valid",
    "bare_data_symbol_is_accepted",
    "immediate_return_is_stack_neutral",
    "unresolved_conditional_target_is_always_accepted",
}
for path, expected, label in ((POSITIVE, positive_names, "positive"), (NEGATIVE, negative_names, "negative")):
    source = path.read_text()
    actual = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", source))
    if actual != expected:
        raise SystemExit(f"{label} proof declarations changed")
    if 'include "../../src/backend/easm_operand_scan.elisa"' not in source and path == POSITIVE:
        raise SystemExit("positive proof no longer imports the production operand scanner")

positive_text = POSITIVE.read_text()
scan_decl = "scan: (start: usize, count: usize, first_separator: usize, last_separator: usize, has_address_group: bool, address_open: usize, address_close: usize, valid: bool) = EasmOperandScan::scan_instruction(text)"
expected_positive = {
    "indexed_address_commas_stay_inside_one_operand": (
        'ensure result == true text: sview = "movq (%rax,%rcx,8), %rbx" ' + scan_decl + ' return ( scan.valid and scan.count == 2 and '
        'text[scan.start:scan.first_separator] == "(%rax,%rcx,8)" and '
        'text[scan.last_separator + 1.usize():text.len] == "%rbx" )'
    ),
    "three_top_level_operands_exceed_the_modeled_limit": (
        'ensure result == true text: sview = "shld %cl, %rbx, (%rax)" ' + scan_decl + ' return scan.valid and scan.count == 3 and '
        'EasmOperandScan::needs_arity_rejection(scan.count)'
    ),
    "a_single_indexed_memory_operand_has_arity_one": (
        'ensure result == true text: sview = "callq *(%rax,%rcx,8)" ' + scan_decl + ' return scan.valid and scan.count == 1 and '
        'not EasmOperandScan::needs_arity_rejection(scan.count)'
    ),
    "unmatched_address_parenthesis_fails_closed": (
        'ensure result == true text: sview = "movq (%rax,%rcx,8, %rbx" ' + scan_decl + ' return not scan.valid'
    ),
    "unmatched_closing_parenthesis_fails_closed": (
        'ensure result == true text: sview = "movq %rax), %rbx" ' + scan_decl + ' return not scan.valid'
    ),
    "nested_address_parentheses_fail_closed": (
        'ensure result == true text: sview = "movq ((%rax)), %rbx" ' + scan_decl + ' return not scan.valid'
    ),
    "no_operand_instruction_has_zero_operands": (
        'ensure result == true scan: (start: usize, count: usize, first_separator: usize, last_separator: usize, has_address_group: bool, address_open: usize, address_close: usize, valid: bool) = EasmOperandScan::scan_instruction("ret") '
        'return scan.valid and scan.count == 0'
    ),
    "scan_records_exact_top_level_separator_prefix": (
        "ensure result == true scan: (start: usize, count: usize, first_separator: usize, last_separator: usize, has_address_group: bool, address_open: usize, address_close: usize, valid: bool) = EasmOperandScan::scan_instruction(text) "
        "if not scan.valid: return scan.count == 0 and scan.first_separator == text.len and scan.last_separator == text.len and not scan.has_address_group "
        "if scan.count == 0: return (scan.start == text.len and scan.first_separator == text.len and scan.last_separator == text.len and not scan.has_address_group and scan.address_open == text.len and scan.address_close == text.len ) "
        "if scan.count == 1: return (scan.first_separator == text.len and scan.last_separator == text.len and scan.start < text.len and EasmOperandScan::first_operand_byte(text[scan.start:text.len], 0.usize()) < (text[scan.start:text.len]).len and EasmOperandScan::next_top_level_separator(text, scan.start, scan.has_address_group, scan.address_open, scan.address_close) == text.len ) "
        "first: usize = EasmOperandScan::next_top_level_separator(text, scan.start, scan.has_address_group, scan.address_open, scan.address_close) "
        "if scan.count == 2: return (scan.first_separator == first and scan.last_separator == first and EasmOperandScan::next_top_level_separator(text, first + 1.usize(), scan.has_address_group, scan.address_open, scan.address_close) == text.len ) "
        "second: usize = EasmOperandScan::next_top_level_separator(text, first + 1.usize(), scan.has_address_group, scan.address_open, scan.address_close) "
        "return scan.count == EasmOperandScan::TOO_MANY_OPERANDS_SENTINEL and scan.first_separator == first and scan.last_separator == second"
    ),
    "valid_scan_exposes_only_its_delimited_address_pair": (
        "ensure result == true scan: (start: usize, count: usize, first_separator: usize, last_separator: usize, has_address_group: bool, address_open: usize, address_close: usize, valid: bool) = EasmOperandScan::scan_instruction(text) "
        "if not scan.valid: return true "
        "if scan.has_address_group: return (scan.start <= scan.address_open and scan.address_open < scan.address_close and scan.address_close < text.len and text[scan.address_open] == EasmOperandScan::ASCII_LEFT_PAREN and text[scan.address_close] == EasmOperandScan::ASCII_RIGHT_PAREN and "
        "(forall candidate in scan.start..<scan.address_open: text[candidate] != EasmOperandScan::ASCII_LEFT_PAREN and text[candidate] != EasmOperandScan::ASCII_RIGHT_PAREN) and "
        "(forall candidate in scan.address_open + 1.usize()..<scan.address_close: text[candidate] != EasmOperandScan::ASCII_LEFT_PAREN and text[candidate] != EasmOperandScan::ASCII_RIGHT_PAREN) and "
        "(forall candidate in scan.address_close + 1.usize()..<text.len: text[candidate] != EasmOperandScan::ASCII_LEFT_PAREN and text[candidate] != EasmOperandScan::ASCII_RIGHT_PAREN) ) "
        "return (scan.address_open == text.len and scan.address_close == text.len and "
        "(forall candidate in scan.start..<text.len: text[candidate] != EasmOperandScan::ASCII_LEFT_PAREN and text[candidate] != EasmOperandScan::ASCII_RIGHT_PAREN) )"
    ),
    "first_operand_byte_is_the_least_non_whitespace": (
        "requires from <= text.len ensure result == true index: usize = EasmOperandScan::first_operand_byte(text, from) return ((index == text.len and "
        "(forall candidate in from..<text.len: text[candidate] == EasmOperandScan::ASCII_SPACE or text[candidate] == EasmOperandScan::ASCII_TAB)) or "
        "(index < text.len and text[index] != EasmOperandScan::ASCII_SPACE and text[index] != EasmOperandScan::ASCII_TAB and "
        "(forall candidate in from..<index: text[candidate] == EasmOperandScan::ASCII_SPACE or text[candidate] == EasmOperandScan::ASCII_TAB)))"
    ),
    "next_separator_is_the_first_comma_outside_address": (
        "requires from <= text.len and open <= text.len and close <= text.len ensure result == true separator: usize = EasmOperandScan::next_top_level_separator(text, from, has_address, open, close) "
        "return ((separator == text.len or (separator >= from and text[separator] == EasmOperandScan::ASCII_COMMA and (not has_address or separator < open or separator > close))) and "
        "(forall candidate in from..<separator: text[candidate] != EasmOperandScan::ASCII_COMMA or (has_address and candidate >= open and candidate <= close)))"
    ),
    "zero_operand_opcode_classifier_matches_its_exact_set": (
        'ensure result == true return EasmOperandScan::is_zero_operand_instruction(op) == ( op == "ret" or op == "retq" or op == "cpuid" or op == "cld" or op == "std" or '
        'op == "lfence" or op == "rdtsc" or op == "pause" or op == "yield" or op == "isb" or op == "emms" or op == "vzeroall" or op == "trap" )'
    ),
    "modeled_arity_matches_zero_operand_opcode_class": (
        "ensure result == true rejected: bool = ( EasmOperandScan::needs_arity_rejection(count) or (count == 0 and not zero_operand_opcode) or (count != 0 and zero_operand_opcode) ) "
        "return (not rejected) == ( count <= EasmOperandScan::MAX_MODELED_OPERAND_COUNT and ((count == 0) == zero_operand_opcode) )"
    ),
    "zero_operand_ret_arity_is_accepted": (
        'ensure result == true return EasmOperandScan::operand_arity_supported("ret", 0.usize())'
    ),
    "unary_push_arity_is_accepted": (
        'ensure result == true return EasmOperandScan::operand_arity_supported("pushq", 1.usize())'
    ),
    "binary_move_arity_is_accepted": (
        'ensure result == true return EasmOperandScan::operand_arity_supported("movq", 2.usize())'
    ),
    "one_operand_shift_arity_is_accepted": (
        'ensure result == true return EasmOperandScan::operand_arity_supported("shlq", 1.usize())'
    ),
    "two_operand_shift_arity_is_accepted": (
        'ensure result == true return EasmOperandScan::operand_arity_supported("shlq", 2.usize())'
    ),
    "mrs_arity_is_binary": (
        'ensure result == true return EasmOperandScan::operand_arity_supported("mrs", 2.usize())'
    ),
    "direct_register_token_is_recognized_exactly": (
        'ensure result == true return EasmOperandScan::exact_register_form("%rax", "rax")'
    ),
    "indirect_register_token_is_recognized_exactly": (
        'ensure result == true return EasmOperandScan::exact_register_form("*%rax", "rax")'
    ),
    "segment_address_is_not_a_register_token": (
        'ensure result == true return not EasmOperandScan::exact_register_form("%fs:0x28", "fs")'
    ),
    "exact_register_form_matches_its_complete_token_equation": (
        "ensure result == true return EasmOperandScan::exact_register_form(operand, register_name) == ( "
        "(operand.len == register_name.len + EasmOperandScan::SCAN_STEP and operand.len > 0 and operand[0] == EasmOperandScan::ASCII_PERCENT and operand[EasmOperandScan::SCAN_STEP:operand.len] == register_name) or "
        "(operand.len == register_name.len + EasmOperandScan::INDIRECT_REGISTER_PREFIX_LENGTH and operand.len >= EasmOperandScan::INDIRECT_REGISTER_PREFIX_LENGTH and operand[0] == EasmOperandScan::ASCII_STAR and operand[1] == EasmOperandScan::ASCII_PERCENT and operand[EasmOperandScan::INDIRECT_REGISTER_PREFIX_LENGTH:operand.len] == register_name) )"
    ),
    "direct_control_target_classifier_matches_its_exact_set": (
        "ensure result == true return EasmOperandScan::is_direct_control_target(op, operand, is_final_operand) == ( is_final_operand and operand.len > 0 and "
        "operand[0] != EasmOperandScan::ASCII_PERCENT and operand[0] != EasmOperandScan::ASCII_DOLLAR and operand[0] != EasmOperandScan::ASCII_STAR and "
        "operand[0] != EasmOperandScan::ASCII_LEFT_PAREN and operand[0] != EasmOperandScan::ASCII_LEFT_BRACKET and EasmTextScan::find(operand, \":\") == operand.len and "
        '(op == "call" or op == "callq" or op == "jmp" or op == "jmpq" or op == "je" or op == "jz" or op == "jne" or op == "jnz" or op == "jl" or op == "jle" or op == "jg" or op == "jge" or op == "jb" or op == "jbe" or op == "ja" or op == "jae") )'
    ),
    "direct_call_symbol_target_is_classified_as_control": (
        'ensure result == true return EasmOperandScan::is_direct_control_target("callq", "runtime_helper", true)'
    ),
    "conditional_symbol_target_is_classified_as_control": (
        'ensure result == true return EasmOperandScan::is_direct_control_target("jz", "local_done", true)'
    ),
    "aarch64_mrs_form_classifier_matches_x0_through_x30_and_xzr": (
        "ensure result == true return EasmOperandScan::is_aarch64_mrs_form(result_register, system_register) == ( system_register == \"cntvct_el0\" and "
        "(result_register == \"xzr\" or (result_register.len == 2 and result_register[0] == EasmOperandScan::ASCII_X and result_register[1] >= EasmOperandScan::ASCII_ZERO and result_register[1] <= EasmOperandScan::ASCII_NINE) or "
        "(result_register.len == 3 and result_register[0] == EasmOperandScan::ASCII_X and (((result_register[1] == EasmOperandScan::ASCII_ONE or result_register[1] == EasmOperandScan::ASCII_TWO) and result_register[2] >= EasmOperandScan::ASCII_ZERO and result_register[2] <= EasmOperandScan::ASCII_NINE) or (result_register[1] == EasmOperandScan::ASCII_THREE and result_register[2] == EasmOperandScan::ASCII_ZERO))) ) )"
    ),
    "mrs_accepts_low_x_register": (
        'ensure result == true return EasmOperandScan::is_aarch64_mrs_form("x0", "cntvct_el0")'
    ),
    "mrs_accepts_high_x_register": (
        'ensure result == true return EasmOperandScan::is_aarch64_mrs_form("x30", "cntvct_el0")'
    ),
    "mrs_accepts_zero_register": (
        'ensure result == true return EasmOperandScan::is_aarch64_mrs_form("xzr", "cntvct_el0")'
    ),
    "bare_symbol_data_operands_are_rejected": (
        "requires operand_present and not memory_address and not register_operand and not immediate_operand and not direct_target "
        "ensure result == true return operand_present and not memory_address and not register_operand and not immediate_operand and not direct_target"
    ),
    "direct_call_symbol_targets_are_exempt_from_data_operand_rejection": (
        "requires operand_present and not memory_address and not register_operand and not immediate_operand and direct_target "
        "ensure result == false return operand_present and not memory_address and not register_operand and not immediate_operand and not direct_target"
    ),
    "register_immediate_and_address_operands_are_modeled": (
        "requires operand_present and (memory_address or register_operand or immediate_operand) "
        "ensure result == false return operand_present and not memory_address and not register_operand and not immediate_operand and not direct_target"
    ),
    "immediate_return_operands_are_rejected": (
        'requires immediate_operand and (op == "ret" or op == "retq") ensure result == true '
        'return immediate_operand and (op == "ret" or op == "retq")'
    ),
    "conditional_jump_targets_require_local_labels_or_explicit_authorization": (
        "ensure result == true return EasmOperandScan::rejects_unresolved_conditional_target( is_conditional_jump, target_is_local, direct_control_capability, relocation_symbol_capability ) == ( is_conditional_jump and not target_is_local and not direct_control_capability and not relocation_symbol_capability )"
    ),
    "segment_address_is_not_an_exact_register_operand": (
        'ensure result == true operand: sview = "%fs:0x28" register_name: sview = "fs" return not ( '
        '(operand.len == register_name.len + EasmOperandScan::SCAN_STEP and operand.len > 0 and '
        'operand[0] == EasmOperandScan::ASCII_PERCENT and operand[EasmOperandScan::SCAN_STEP:operand.len] == register_name) or '
        '(operand.len == register_name.len + EasmOperandScan::INDIRECT_REGISTER_PREFIX_LENGTH and '
        'operand.len >= EasmOperandScan::INDIRECT_REGISTER_PREFIX_LENGTH and '
        'operand[0] == EasmOperandScan::ASCII_STAR and operand[1] == EasmOperandScan::ASCII_PERCENT and '
        'operand[EasmOperandScan::INDIRECT_REGISTER_PREFIX_LENGTH:operand.len] == register_name) )'
    ),
}
for name, expected in expected_positive.items():
    if proof_body(positive_text, name) != compact(expected):
        raise SystemExit(f"positive scanner theorem changed: {name}")

negative_text = NEGATIVE.read_text()
expected_negative = {
    "indexed_address_has_four_operands": (
        'ensure result == true scan: (start: usize, count: usize, first_separator: usize, last_separator: usize, has_address_group: bool, address_open: usize, address_close: usize, valid: bool) = EasmOperandScan::scan_instruction("movq (%rax,%rcx,8), %rbx") '
        'return scan.count == 4'
    ),
    "three_top_level_operands_are_supported": (
        'ensure result == true scan: (start: usize, count: usize, first_separator: usize, last_separator: usize, has_address_group: bool, address_open: usize, address_close: usize, valid: bool) = EasmOperandScan::scan_instruction("shld %cl, %rbx, (%rax)") '
        "return scan.valid and not EasmOperandScan::needs_arity_rejection(scan.count)"
    ),
    "unmatched_address_parenthesis_is_valid": (
        'ensure result == true scan: (start: usize, count: usize, first_separator: usize, last_separator: usize, has_address_group: bool, address_open: usize, address_close: usize, valid: bool) = EasmOperandScan::scan_instruction("movq (%rax,%rcx,8, %rbx") '
        "return scan.valid"
    ),
    "invalid_scan_preserves_address_group_metadata": (
        'ensure result == true scan: (start: usize, count: usize, first_separator: usize, last_separator: usize, has_address_group: bool, address_open: usize, address_close: usize, valid: bool) = EasmOperandScan::scan_instruction("movq (%rax") '
        "return not scan.valid and scan.has_address_group"
    ),
    "zero_operand_scan_has_non_sentinel_separator": (
        'ensure result == true scan: (start: usize, count: usize, first_separator: usize, last_separator: usize, has_address_group: bool, address_open: usize, address_close: usize, valid: bool) = EasmOperandScan::scan_instruction("ret") '
        'return scan.valid and scan.count == 0 and scan.first_separator < ("ret").len'
    ),
    "single_operand_scan_has_an_empty_operand": (
        'ensure result == true text: sview = "callq *(%rax)" scan: (start: usize, count: usize, first_separator: usize, last_separator: usize, has_address_group: bool, address_open: usize, address_close: usize, valid: bool) = EasmOperandScan::scan_instruction(text) '
        "operand: sview = text[scan.start:text.len] return scan.valid and scan.count == 1 and EasmOperandScan::first_operand_byte(operand, 0.usize()) == operand.len"
    ),
    "next_separator_selects_a_comma_inside_address": (
        'ensure result == true text: sview = "(%rax,%rcx),%rbx" separator: usize = EasmOperandScan::next_top_level_separator(text, 0.usize(), true, 0.usize(), 10.usize()) '
        "return separator < text.len and separator <= 10.usize()"
    ),
    "cpuid_is_not_a_zero_operand_instruction": (
        'ensure result == true return not EasmOperandScan::is_zero_operand_instruction("cpuid")'
    ),
    "movq_is_a_zero_operand_instruction": (
        'ensure result == true return EasmOperandScan::is_zero_operand_instruction("movq")'
    ),
    "movq_with_one_operand_is_accepted": (
        'ensure result == true return EasmOperandScan::operand_arity_supported("movq", 1.usize())'
    ),
    "incq_with_two_operands_is_accepted": (
        'ensure result == true return EasmOperandScan::operand_arity_supported("incq", 2.usize())'
    ),
    "mrs_with_one_operand_is_accepted": (
        'ensure result == true return EasmOperandScan::operand_arity_supported("mrs", 1.usize())'
    ),
    "register_suffix_is_accepted_as_the_exact_register": (
        'ensure result == true return EasmOperandScan::exact_register_form("%rax_extra", "rax")'
    ),
    "bare_register_name_is_accepted_as_att_syntax": (
        'ensure result == true return EasmOperandScan::exact_register_form("rax", "rax")'
    ),
    "register_operand_is_classified_as_a_direct_target": (
        'ensure result == true return EasmOperandScan::is_direct_control_target("callq", "%rax", true)'
    ),
    "immediate_operand_is_classified_as_a_direct_target": (
        'ensure result == true return EasmOperandScan::is_direct_control_target("callq", "$runtime_helper", true)'
    ),
    "nonfinal_symbol_is_classified_as_a_direct_target": (
        'ensure result == true return EasmOperandScan::is_direct_control_target("callq", "runtime_helper", false)'
    ),
    "mrs_accepts_x31": (
        'ensure result == true return EasmOperandScan::is_aarch64_mrs_form("x31", "cntvct_el0")'
    ),
    "mrs_accepts_zero_padded_x09": (
        'ensure result == true return EasmOperandScan::is_aarch64_mrs_form("x09", "cntvct_el0")'
    ),
    "mrs_accepts_general_purpose_w_register": (
        'ensure result == true return EasmOperandScan::is_aarch64_mrs_form("w0", "cntvct_el0")'
    ),
    "mrs_accepts_unsupported_system_register": (
        'ensure result == true return EasmOperandScan::is_aarch64_mrs_form("x0", "cntfrq_el0")'
    ),
    "nested_address_parentheses_are_valid": (
        'ensure result == true scan: (start: usize, count: usize, first_separator: usize, last_separator: usize, has_address_group: bool, address_open: usize, address_close: usize, valid: bool) = EasmOperandScan::scan_instruction("movq ((%rax)), %rbx") '
        "return scan.valid"
    ),
    "bare_data_symbol_is_accepted": (
        "requires operand_present and not memory_address and not register_operand and not immediate_operand and not direct_target "
        "ensure result == true return not (operand_present and not memory_address and not register_operand and not immediate_operand and not direct_target)"
    ),
    "immediate_return_is_stack_neutral": (
        'requires immediate_operand and (op == "ret" or op == "retq") ensure result == true '
        'return not (immediate_operand and (op == "ret" or op == "retq"))'
    ),
    "unresolved_conditional_target_is_always_accepted": (
        "ensure result == true return not EasmOperandScan::rejects_unresolved_conditional_target(true, false, false, false)"
    ),
}
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
    Path(__file__), HERE / "proof_product_gate.py", POSITIVE, NEGATIVE,
    POLICY, ENV, PROVENANCE, FUNCTION, MEMORY, MODEL, MASKS,
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
