"""Admit the EASM merge live-in analysis against a strict Elisa-proof product."""
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
POSITIVE = HERE / "easm_merge_demand.elisa"
NEGATIVE = HERE / "easm_merge_demand_rejected.elisa"
MODEL = ROOT / "src/backend/easm_model.elisa"
PROVENANCE = ROOT / "src/backend/easm_verify_provenance.elisa"
MEMORY = ROOT / "src/backend/easm_verify_memory.elisa"
REGISTER_MASKS = ROOT / "src/backend/easm_register_masks.elisa"
VERIFY_FUNCTION = ROOT / "src/backend/easm_verify_function.elisa"
PARSER = ROOT / "src/backend/easm_parse.elisa"
ENV = ROOT / "src/backend/codegen_env.elisa"

POSITIVE_NAMES = {
    "demanded_read_before_prior_write",
    "prior_definition_after_instruction",
    "read_modify_write_demands_before_its_write",
    "a_write_only_destination_does_not_demand_its_old_value",
    "a_memory_destination_demands_its_address_register",
    "a_register_move_destination_does_not_read_its_old_value",
    "a_self_zeroing_alu_operation_suppresses_old_value_demand",
    "aliased_move_source_survives_destination_write",
    "later_read_survives_an_unrelated_write",
    "an_earlier_target_write_kills_later_live_in_demand",
    "a_read_before_a_later_write_stays_demanded",
    "two_step_scan_matches_closed_demand_form",
    "three_step_scan_matches_closed_demand_form",
    "a_past_demand_survives_every_later_instruction",
    "a_prior_definition_survives_every_later_instruction",
}
NEGATIVE_NAMES = {"false_claim_read_modify_write_needs_no_old_value"}

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    return "".join(text.split())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"^[ \t]*def {re.escape(name)}\(", source, re.MULTILINE))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    start = matches[0].start()
    following = re.search(
        r"^[ \t]*def [A-Za-z_][A-Za-z0-9_]*\(", source[matches[0].end():], re.MULTILINE
    )
    end = matches[0].end() + following.start() if following else len(source)
    return source[start:end]


def proof_body(source: str, name: str) -> str:
    section = function_section(source, name)
    return section.split(":\n", 1)[1]


def exactly_contains(source: str, fragment: str, message: str) -> None:
    if compact(fragment) not in compact(source):
        raise SystemExit(message)


positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()
actual_positive = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", positive_text))
actual_negative = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", negative_text))
if actual_positive != POSITIVE_NAMES or actual_negative != NEGATIVE_NAMES:
    raise SystemExit("merge-demand proof declaration inventory changed")

expected_proofs = {
    "demanded_read_before_prior_write": (
        "ensure result == (reads_now and not defined_before)\n"
        "return reads_now and not defined_before"
    ),
    "prior_definition_after_instruction": (
        "ensure result == (defined_before or writes_now)\n"
        "return defined_before or writes_now"
    ),
    "read_modify_write_demands_before_its_write": (
        "requires not defined_before and reads_now and writes_now\n"
        "ensure result == true\n"
        "return reads_now and not defined_before"
    ),
    "a_write_only_destination_does_not_demand_its_old_value": (
        "requires not defined_before and not reads_now and writes_now\n"
        "ensure result == false\n"
        "return reads_now and not defined_before"
    ),
    "a_memory_destination_demands_its_address_register": (
        "requires not defined_before and not destination_is_register and destination_address_reads\n"
        "ensure result == true\n"
        "return (source_reads or (not destination_is_register and destination_address_reads)) and not defined_before"
    ),
    "a_register_move_destination_does_not_read_its_old_value": (
        "requires not defined_before and not source_reads and destination_is_register and destination_writes\n"
        "ensure result == false\n"
        "return (source_reads or (not destination_is_register and destination_address_reads)) and not defined_before"
    ),
    "a_self_zeroing_alu_operation_suppresses_old_value_demand": (
        "requires not defined_before and operands_are_same_register and opcode_is_xor_or_sub\n"
        "ensure result == false\n"
        "return ((source_reads or destination_address_reads) and not (operands_are_same_register and opcode_is_xor_or_sub)) and not defined_before"
    ),
    "aliased_move_source_survives_destination_write": (
        "requires not defined_before and source_alias and destination_writes\n"
        "ensure result == true\n"
        "return ((all_reads and not destination_writes) or (source_alias and destination_writes)) and not defined_before"
    ),
    "later_read_survives_an_unrelated_write": (
        "requires not defined_before and not write_target_before and write_other_before and read_now\n"
        "ensure result == true\n"
        "return (read_before and not defined_before) or (read_now and not (defined_before or write_target_before))"
    ),
    "an_earlier_target_write_kills_later_live_in_demand": (
        "requires not defined_before and not read_before and write_target_before and read_now\n"
        "ensure result == false\n"
        "return (read_before and not defined_before) or (read_now and not (defined_before or write_target_before))"
    ),
    "a_read_before_a_later_write_stays_demanded": (
        "requires not defined_before and read_before and write_target_before\n"
        "ensure result == true\n"
        "return (read_before and not defined_before) or (read_now and not (defined_before or write_target_before))"
    ),
    "two_step_scan_matches_closed_demand_form": (
        "ensure result == true\n"
        "demanded_after_first: bool = demanded_before or (reads_first and not defined_before)\n"
        "defined_after_first: bool = defined_before or writes_first\n"
        "demanded_after_second: bool = demanded_after_first or (reads_second and not defined_after_first)\n"
        "return demanded_after_second == (demanded_before or (reads_first and not defined_before) or (reads_second and not (defined_before or writes_first)))"
    ),
    "three_step_scan_matches_closed_demand_form": (
        "ensure result == true\n"
        "demanded_after_first: bool = demanded_before or (reads_first and not defined_before)\n"
        "defined_after_first: bool = defined_before or writes_first\n"
        "demanded_after_second: bool = demanded_after_first or (reads_second and not defined_after_first)\n"
        "defined_after_second: bool = defined_after_first or writes_second\n"
        "demanded_after_third: bool = demanded_after_second or (reads_third and not defined_after_second)\n"
        "return demanded_after_third == (demanded_before or (reads_first and not defined_before) or (reads_second and not (defined_before or writes_first)) or (reads_third and not (defined_before or writes_first or writes_second)))"
    ),
    "a_past_demand_survives_every_later_instruction": (
        "requires demanded_before\n"
        "ensure result == true\n"
        "return demanded_before or (reads_now and not defined_before)"
    ),
    "a_prior_definition_survives_every_later_instruction": (
        "requires defined_before\n"
        "ensure result == true\n"
        "return defined_before or writes_now"
    ),
}
for name, shape in expected_proofs.items():
    if compact(proof_body(positive_text, name)) != compact(shape):
        raise SystemExit(f"merge-demand proof changed: {name}")
if compact(proof_body(negative_text, "false_claim_read_modify_write_needs_no_old_value")) != compact(
    "requires not defined_before\nensure result == true\nreturn defined_before"
):
    raise SystemExit("read-modify-write counterexample changed")

model_text = MODEL.read_text()
register_order = (
    "RAX", "RCX", "RDX", "RBX", "RSI", "RDI", "RBP", "RSP",
    "R8", "R9", "R10", "R11", "R12", "R13", "R14", "R15",
)
operand_mask = function_section(model_text, "easm_operand_register_mask")
expected_operand_mask = """
def easm_operand_register_mask(operand: sview) -> i64:
    return easm_register_bit(easm_register_operand(operand)) | easm_register_bit(easm_memory_base_register(operand)) | easm_register_bit(easm_memory_index_register(operand))
"""
if compact(operand_mask) != compact(expected_operand_mask):
    raise SystemExit("operand register scanning must normalize direct, base, and index register spellings")

instruction_mask = function_section(model_text, "easm_instruction_register_mask")
expected_instruction_mask = """
def easm_instruction_register_mask(instruction: Instruction) -> i64:
    mask: mutable i64 = easm_register_mask(instruction.text) | easm_operand_register_mask(easm_substitute_operand(easm_first_operand(instruction.text), instruction)) | easm_operand_register_mask(easm_substitute_operand(easm_last_operand(instruction.text), instruction))
    for index in 0..<instruction.substitution_count.usize() |index, instruction, mask|:
        substitution: Substitution = easm_substitution_at(instruction, index.i64())
        if easm_find(instruction.text, substitution.from) < sview_len(instruction.text):
            mask <- mask | easm_register_mask(substitution.replacement) | easm_operand_register_mask(substitution.replacement)
    return mask
"""
if compact(instruction_mask) != compact(expected_instruction_mask):
    raise SystemExit("instruction masks must include narrow aliases from each parsed operand and substitution")

expected_register_scan = "def easm_register_mask(text: sview) -> i64:\n    mask: mutable i64 = 0\n" + "\n".join(
    f'    mask <- mask | EasmRegisterMasks::{name} if easm_find(text, "%{name.lower()}") < sview_len(text)'
    for name in register_order
) + "\n    return mask"
if compact(function_section(model_text, "easm_register_mask")) != compact(expected_register_scan):
    raise SystemExit("canonical register-text scan changed")

written = function_section(model_text, "easm_written_mask")
expected_written = """
def easm_written_mask(instruction: Instruction) -> i64:
    if easm_starts(instruction.op, "cmp") or easm_starts(instruction.op, "test") or easm_starts(instruction.op, "push") or easm_starts(instruction.op, "call") or easm_starts(instruction.op, "jmp") or easm_starts(instruction.op, "ret"):
        return 0
    return easm_register_bit(easm_register_operand(easm_substitute_operand(easm_last_operand(instruction.text), instruction)))
"""
if compact(written) != compact(expected_written):
    raise SystemExit("register definitions must include pop destinations while excluding flag, stack, call, and control instructions")

reads = function_section(model_text, "easm_read_mask")
expected_reads = """
def easm_read_mask(instruction: Instruction) -> i64:
    all_registers: i64 = easm_instruction_register_mask(instruction)
    return 0 if easm_self_zeroing(instruction)
    if easm_starts(instruction.op, "mov") or easm_starts(instruction.op, "lea"):
        source: sview = easm_substitute_operand(easm_first_operand(instruction.text), instruction)
        destination: sview = easm_substitute_operand(easm_last_operand(instruction.text), instruction)
        destination_reads: i64 = 0 if easm_register_operand(destination) != "" else easm_operand_register_mask(destination)
        return easm_operand_register_mask(source) | destination_reads
    if easm_starts(instruction.op, "pop"):
        destination: sview = easm_substitute_operand(easm_last_operand(instruction.text), instruction)
        return 0 if easm_register_operand(destination) != "" else easm_operand_register_mask(destination)
    return all_registers
"""
if compact(reads) != compact(expected_reads):
    raise SystemExit("MOV, LEA, and POP destinations must not count as reads of their old values")

provenance_text = PROVENANCE.read_text()
merge = function_section(provenance_text, "verify_control_flow_merges")
for fragment, message in (
    (
        'continue if fn.instructions[index].op != "label" or incoming_counts[index] == 0',
        "merge live-in validation must cover every reachable label block",
    ),
    ("demanded: mutable i64 = 0", "merge demand accumulator is missing"),
    ("defined_before: mutable i64 = 0", "per-register prior-definition set is missing"),
    (
        "reads: i64 = easm_read_mask(next) | easm_implicit_read_mask(next.op)",
        "merge demands must include explicit and implicit register reads",
    ),
    (
        'writes: i64 = easm_written_mask(next) | easm_implicit_write_mask(next.op) | (EasmRegisterMasks::call_clobber_mask() if easm_starts(next.op, "call") else 0)',
        "merge definition tracking must include explicit, implicit, and call clobber writes",
    ),
    (
        "demanded <- demanded | (reads & (~defined_before))",
        "each read must be demanded unless an earlier instruction defined that register",
    ),
    (
        "defined_before <- defined_before | writes",
        "per-register definitions must accumulate across the whole block",
    ),
    (
        'break if next.op == "label" or easm_is_terminator(next.op)',
        "the read scan must continue past unrelated writes and stop only at a block boundary",
    ),
):
    exactly_contains(merge, fragment, message)
if "break if easm_written_mask(next) != 0" in merge:
    raise SystemExit("a write to one register must not stop demand discovery for other registers")
expected_scan_loop = """
while probe < count |probe, demanded, defined_before, fn|:
    next: Instruction = fn.instructions[probe]
    reads: i64 = easm_read_mask(next) | easm_implicit_read_mask(next.op)
    writes: i64 = easm_written_mask(next) | easm_implicit_write_mask(next.op) | (EasmRegisterMasks::call_clobber_mask() if easm_starts(next.op, "call") else 0)
    demanded <- demanded | (reads & (~defined_before))
    defined_before <- defined_before | writes
    break if next.op == "label" or easm_is_terminator(next.op)
    probe <- probe + 1
missing: i64 = demanded & (~meets[index])
"""
if compact(expected_scan_loop) not in compact(merge):
    raise SystemExit("merge live-in source scan changed from the proof-bound cumulative transfer")

verify_function_text = VERIFY_FUNCTION.read_text()
function_compositions = function_section(verify_function_text, "verify_function_compositions")
module_compositions = function_section(verify_function_text, "verify_module_compositions")
module_verify = function_section(verify_function_text, "verify_module")
parse_text = PARSER.read_text()
layout_parse = function_section(parse_text, "parse_layout_module")
parse_module = function_section(parse_text, "parse_module")
for source, fragment, message in (
    (function_compositions, "verify_control_flow_merges(fn, issues)", "function composition must run merge validation"),
    (module_compositions, "verify_function_compositions(fn, module.fragments, issues)", "module composition must validate each function"),
    (module_verify, "verify_module_compositions(module, issues)", "module verification must reach composition validation"),
    (layout_parse, "verify_module(out)", "EASM layout parsing must invoke module verification"),
    (parse_module, "return parse_layout_module(source, length, path)", "public module parsing must reach layout parsing and verification"),
):
    exactly_contains(source, fragment, message)

env_text = ENV.read_text()
for include in (
    'include "easm_register_masks.elisa"',
    'include "easm_model.elisa"',
    'include "easm_verify_provenance.elisa"',
    'include "easm_verify_memory.elisa"',
    'include "easm_verify_function.elisa"',
    'include "easm_parse.elisa"',
):
    if include not in env_text:
        raise SystemExit(f"backend environment no longer imports required EASM source: {include}")

memory_text = MEMORY.read_text()
expected_implicit_reads = """
def easm_implicit_read_mask(op: sview) -> i64:
    if easm_equal(op, "cpuid"):
        return EasmRegisterMasks::cpuid_read_mask()
    return 0
"""
if compact(function_section(memory_text, "easm_implicit_read_mask")) != compact(expected_implicit_reads):
    raise SystemExit("merge demand model no longer matches the source implicit-read mask")
expected_implicit_writes = """
def easm_implicit_write_mask(op: sview) -> i64:
    if easm_equal(op, "cpuid"):
        return EasmRegisterMasks::cpuid_write_mask()
    if easm_equal(op, "rdtsc"):
        return EasmRegisterMasks::rdtsc_write_mask()
    return 0
"""
if compact(function_section(memory_text, "easm_implicit_write_mask")) != compact(expected_implicit_writes):
    raise SystemExit("merge demand model no longer matches the source implicit-write mask")

mask_text = REGISTER_MASKS.read_text()
for index, name in enumerate(register_order):
    exactly_contains(mask_text, f"const {name}: i64 = {1 << index}", f"canonical EASM register bit changed: {name}")
register_aliases = {
    "RAX": ("rax", "eax", "ax", "al"), "RCX": ("rcx", "ecx", "cx", "cl"),
    "RDX": ("rdx", "edx", "dx", "dl"), "RBX": ("rbx", "ebx", "bx", "bl"),
    "RSI": ("rsi", "esi", "si", "sil"), "RDI": ("rdi", "edi", "di", "dil"),
    "RBP": ("rbp", "ebp", "bp", "bpl"), "RSP": ("rsp", "esp", "sp", "spl"),
    **{f"R{i}": (f"r{i}", f"r{i}d", f"r{i}w", f"r{i}b") for i in range(8, 16)},
}
expected_register_bit = "def easm_register_bit(register: sview) -> i64:\n" + "\n".join(
    "    if " + " or ".join(f'easm_equal(register, "{alias}")' for alias in aliases) +
    f":\n        return EasmRegisterMasks::{register}"
    for register, aliases in register_aliases.items()
) + "\n    return 0"
if compact(function_section(model_text, "easm_register_bit")) != compact(expected_register_bit):
    raise SystemExit("narrow and wide register spellings must share their canonical one-hot mask")

expected_register_operand = """
def easm_register_operand(operand: sview) -> sview:
    value: sview = easm_trim(operand)
    if sview_len(value) > 0 and sview_at(value, 0) == 37:
        end: mutable usize = 1
        while end < sview_len(value) |end, value|:
            byte: u8 = sview_at(value, end)
            break if not ((byte >= 48 and byte <= 57) or (byte >= 65 and byte <= 90) or (byte >= 97 and byte <= 122) or byte == 95)
            end <- end + 1
        return value[1:end]
    # Contract bindings use bare names (`a = rdi`), while instruction operands use
    # AT&T's `%rdi`.  Both spellings denote the same machine register.
    return value if easm_register_bit(value) != 0 else ""
"""
if compact(function_section(provenance_text, "easm_register_operand")) != compact(expected_register_operand):
    raise SystemExit("EASM register operands must normalize percent-prefixed and bare aliases identically")

expected_operand_parsers = {
    "easm_first_operand": """
def easm_first_operand(text: sview) -> sview:
    start: usize = easm_first_space(text)
    if start >= sview_len(text):
        return ""
    rest: sview = easm_trim(text[start:sview_len(text)])
    comma: usize = easm_find(rest, ",")
    return rest[0:comma]
""",
    "easm_last_operand": """
def easm_last_operand(text: sview) -> sview:
    comma: mutable usize = sview_len(text)
    for index in 0..<sview_len(text) |comma, text|:
        comma <- index if sview_at(text, index) == 44
    if comma >= sview_len(text):
        start: usize = easm_first_space(text)
        if start >= sview_len(text):
            return ""
        return easm_trim(text[start:sview_len(text)])
    return easm_trim(text[comma + 1.usize():sview_len(text)])
""",
    "easm_trim": """
def easm_trim(text: sview) -> sview:
    first: mutable usize = 0
    last: mutable usize = sview_len(text)
    while first < last and (sview_at(text, first) == 32 or sview_at(text, first) == 9) |first, text, last|:
        first <- first + 1
    while last > first and (sview_at(text, last - 1.usize()) == 32 or sview_at(text, last - 1.usize()) == 9) |last, text, first|:
        last <- last - 1
    return text[first:last]
""",
    "easm_find": """
def easm_find(text: sview, needle: sview) -> usize:
    if sview_len(needle) == 0 or sview_len(text) < sview_len(needle):
        return sview_len(text)
    for index in 0..<(sview_len(text) - sview_len(needle) + 1.usize()) |text, needle|:
        if text[index:index + sview_len(needle)] == needle:
            return index
    return sview_len(text)
""",
    "easm_equal": """
def easm_equal(a: sview, b: sview) -> bool:
    return sview_len(a) == sview_len(b) and easm_starts(a, b)
""",
    "easm_starts": """
def easm_starts(text: sview, prefix: sview) -> bool:
    false return if sview_len(text) < sview_len(prefix)
    for index in 0..<sview_len(prefix) |text, prefix|:
        false return if sview_at(text, index) != sview_at(prefix, index)
    return true
""",
}
operand_sources = {
    **{name: provenance_text for name in ("easm_first_operand", "easm_last_operand", "easm_equal", "easm_starts")},
    "easm_trim": provenance_text,
    "easm_find": VERIFY_FUNCTION.read_text(),
}
for name, expected in expected_operand_parsers.items():
    if compact(function_section(operand_sources[name], name)) != compact(expected):
        raise SystemExit(f"EASM operand decoder changed: {name}")
expected_first_space = """
def easm_first_space(text: sview) -> usize:
    for index in 0..<sview_len(text) |text|:
        if sview_at(text, index) == 32 or sview_at(text, index) == 9:
            return index
    return sview_len(text)
"""
if compact(function_section(VERIFY_FUNCTION.read_text(), "easm_first_space")) != compact(expected_first_space):
    raise SystemExit("EASM mnemonic/operand boundary scan changed")

expected_memory_helpers = {
    "easm_memory_base_register": """
def easm_memory_base_register(operand: sview) -> sview:
    open: usize = easm_find(operand, "(")
    if open >= sview_len(operand):
        return ""
    close: usize = easm_find(operand[open:sview_len(operand)], ")") + open
    if close <= open:
        return ""
    inside: mutable sview = operand[open + 1.usize():close]
    comma: usize = easm_find(inside, ",")
    if comma < sview_len(inside):
        inside <- inside[0:comma]
    return easm_register_operand(inside)
""",
    "easm_memory_index_register": """
def easm_memory_index_register(operand: sview) -> sview:
    open: usize = easm_find(operand, "(")
    if open >= sview_len(operand):
        return ""
    close: usize = easm_find(operand[open:sview_len(operand)], ")") + open
    if close <= open:
        return ""
    inside: sview = operand[open + 1.usize():close]
    comma: usize = easm_find(inside, ",")
    if comma >= sview_len(inside):
        return ""
    rest: mutable sview = inside[comma + 1.usize():sview_len(inside)]
    second_comma: usize = easm_find(rest, ",")
    if second_comma < sview_len(rest):
        rest <- rest[0:second_comma]
    return easm_register_operand(rest)
""",
}
for name, expected in expected_memory_helpers.items():
    if compact(function_section(memory_text, name)) != compact(expected):
        raise SystemExit(f"EASM address register extraction changed: {name}")

expected_substitute = """
def easm_substitute_operand(operand: sview, instruction: Instruction) -> sview:
    value: sview = easm_trim(operand)
    for index in 0..<instruction.substitution_count.usize() |index, instruction, value|:
        substitution: Substitution = easm_substitution_at(instruction, index.i64())
        if easm_equal(value, substitution.from):
            return substitution.replacement
    return value
"""
if compact(function_section(model_text, "easm_substitute_operand")) != compact(expected_substitute):
    raise SystemExit("operand substitution must be applied before register-alias extraction")

expected_self_zeroing = """
def easm_self_zeroing(instruction: Instruction) -> bool:
    false return if instruction.pseudo
    source: sview = easm_register_operand(easm_first_operand(instruction.text))
    destination: sview = easm_register_operand(easm_last_operand(instruction.text))
    return source != "" and source == destination and (easm_starts(instruction.op, "xor") or easm_starts(instruction.op, "sub"))
"""
if compact(function_section(memory_text, "easm_self_zeroing")) != compact(expected_self_zeroing):
    raise SystemExit("EASM self-zeroing source/destination alias classification changed")
expected_call_clobber = """
def call_clobber_mask() -> i64:
    ensure result == (RAX | RCX | RDX | RSI | RDI | R8 | R9 | R10 | R11)
    return RAX | RCX | RDX | RSI | RDI | R8 | R9 | R10 | R11
"""
if compact(function_section(mask_text, "call_clobber_mask")) != compact(expected_call_clobber):
    raise SystemExit("merge demand model no longer matches the source call-clobber mask")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("EASM merge-demand proof requires a strict proof build")
stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"), PROVER / "ELISA_COMPILER_REV",
    stage1_product, stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
    POSITIVE, NEGATIVE, MODEL, PROVENANCE, MEMORY, REGISTER_MASKS, VERIFY_FUNCTION, PARSER, ENV,
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
assert positive["summary"]["obligations"] == positive["summary"]["proven"] == 30
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == POSITIVE_NAMES
assert positive == run(POSITIVE)[1], "merge-demand proof report changed across repeated runs"

negative_code, negative = run(NEGATIVE)
assert negative_code == 1 and negative["status"] == "failed"
assert negative["summary"]["obligations"] == 32 and negative["summary"]["proven"] == 31
finding = negative["findings"][0]
assert finding["kind"] == "ensure-unproven" and finding["name"] == "false_claim_read_modify_write_needs_no_old_value"
assert finding["status"] == "disproved" and finding["counterexample_found"]
assert finding["counterexample"][0]["left"]["name"] == "defined_before"
assert finding["counterexample"][0]["right"]["value"] is False
assert negative == run(NEGATIVE)[1], "merge-demand false-claim report changed across repeated runs"

assert require_current_product(BIN, PROVER) == manifest, "proof-product provenance changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "kernel proves one-register Boolean transfer laws, including two-instruction read/write ordering; the source checker (not the kernel proof) binds the per-register projection to the i64 bit-mask implementation, narrow register aliases, MOV/LEA/POP reads, self-zeroing idioms, explicit/implicit/call effects, and cumulative EASM block scan",
    "positive_obligations": positive["summary"]["proven"],
    "false_claim_rejected_with_counterexample": finding["name"],
    "proof_binary_sha256": hashlib.sha256(BIN.read_bytes()).hexdigest(),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
