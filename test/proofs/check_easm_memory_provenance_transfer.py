"""Admit the EASM register provenance transfer lemmas against the production verifier."""
from __future__ import annotations

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
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
HERE = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument("--source-only", action="store_true",
                    help="check source and fixture bindings without invoking Elisa-Proof")
ARGS = parser.parse_args()
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=not ARGS.source_only)
POSITIVE = HERE / "easm_memory_provenance_transfer.elisa"
NEGATIVE = HERE / "easm_memory_provenance_transfer_rejected.elisa"
MEMORY = ROOT / "src/backend/easm_verify_memory.elisa"
MEMORY_EFFECTS = ROOT / "src/backend/easm_verify_memory_effects.elisa"
ADDRESS_POLICY = ROOT / "src/backend/easm_address_width_policy.elisa"
MODEL = HERE / "easm_memory_provenance_transfer.elisa"

POSITIVE_NAMES = {
    "a_call_drops_existing_caller_saved_provenance",
    "a_call_preserves_existing_callee_saved_provenance",
    "an_implicit_result_write_drops_old_provenance",
    "a_partial_register_move_drops_the_destination_fact",
    "a_partial_register_exchange_drops_both_operand_facts",
    "a_tracked_empty_fact_does_not_recover_input_type",
    "an_untracked_input_register_uses_signature_provenance",
    "pseudo_instruction_preserves_destination_provenance",
    "pseudo_instruction_preserves_source_provenance",
    "non_exchange_without_a_destination_is_a_state_noop",
    "move_cannot_create_provenance_from_an_untracked_source",
    "move_copies_a_tracked_source_provenance_component",
    "move_from_a_nonregister_clears_the_old_destination_provenance",
    "lea_cannot_create_provenance_from_an_untracked_base",
    "lea_copies_a_tracked_base_provenance_component",
    "lea_without_a_parsed_base_clears_old_destination_provenance",
    "pointer_arithmetic_preserves_destination_provenance",
    "every_other_register_write_kills_stale_destination_provenance",
    "xchg_swaps_destination_provenance",
    "xchg_swaps_source_provenance",
    "xchg_with_one_unparsed_operand_clears_the_surviving_register",
}
MODEL_NAMES = {
    "provenance_after_implicit_clobber",
    "provenance_type_after_signature_fallback",
    "provenance_destination_after",
    "provenance_source_after",
}
NEGATIVE_NAMES = {
    "false_claim_move_invents_provenance_from_an_untracked_source",
    "false_claim_unknown_write_preserves_stale_provenance",
    "false_claim_arithmetic_destroys_valid_pointer_provenance",
    "false_claim_xchg_without_destination_preserves_the_source",
    "false_claim_call_preserves_caller_saved_provenance",
    "false_claim_defined_implicit_result_preserves_old_provenance",
    "false_claim_partial_move_copies_pointer_provenance",
    "false_claim_partial_exchange_preserves_source",
    "false_claim_partial_exchange_preserves_destination",
    "false_claim_cleared_provenance_recovers_from_signature_input",
}

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(source: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in expand_return_if_blocks(source).splitlines())


def code_only(source: str) -> str:
    return "\n".join(line.split("#", 1)[0] for line in source.splitlines())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^[ \t]*def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    start = matches[0].start()
    following = re.search(r"(?m)^[ \t]*def [A-Za-z_][A-Za-z0-9_]*\(", source[matches[0].end():])
    end = matches[0].end() + following.start() if following else len(source)
    return source[start:end]


def declared_functions(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


def proof_body(source: str, name: str) -> str:
    signature = f"def {name}("
    if signature not in source:
        raise SystemExit(f"missing proof function: {name}")
    return source.split(signature, 1)[1].split("\ndef ", 1)[0].split(":\n", 1)[1]


memory = compact(code_only(function_section(MEMORY.read_text(), "easm_update_memory_provenance")))
required_order = (
    "if instruction.pseudo:return",
    "implicit_writes:mutable i64=easm_implicit_write_mask(instruction.op)",
    'if easm_starts(instruction.op,"call"):',
    "implicit_writes<-EasmRegisterMasks::call_clobber_mask()",
    "if implicit_writes!=0:",
    "for index in 0..<states.count |index,states,implicit_writes|:",
    "bit:i64=easm_register_bit(states[index].register)",
    "if bit!=0and(implicit_writes&bit)!=0:",
    'states[index]<-MemoryProvenance{register:states[index].register,type_name:"",parameter:""}',
    "returndestination_operand:sview=",
    "op:sview=instruction.op",
    "destination_width:i64=EasmAddressWidthPolicy::address_register_width(destination)",
    "source_width:i64=EasmAddressWidthPolicy::address_register_width(source)",
    'if easm_starts(instruction.op,"xchg"):',
    "full_width_exchange:bool=destination_width==EasmAddressWidthPolicy::ADDRESS_REGISTER_WIDTH_64andsource_width==EasmAddressWidthPolicy::ADDRESS_REGISTER_WIDTH_64and(op==\"xchgq\"orop==\"xchg\")",
    'if full_width_exchange and source!=""anddestination!="":',
    "source_type:sview=easm_provenance_type(states,source)",
    "source_parameter:sview=easm_provenance_parameter(states,source)",
    "destination_type:sview=easm_provenance_type(states,destination)",
    "destination_parameter:sview=easm_provenance_parameter(states,destination)",
    "easm_provenance_set_parameter(states,source,destination_type,destination_parameter)",
    "easm_provenance_set_parameter(states,destination,source_type,source_parameter)",
    'easm_provenance_set_parameter(states,source,"","")ifsource!=""',
    'easm_provenance_set_parameter(states,destination,"","")ifdestination!=""',
    'if destination=="":return',
    'if (op=="mov"orop=="movq")anddestination_width==EasmAddressWidthPolicy::ADDRESS_REGISTER_WIDTH_64and(source==""orsource_width==EasmAddressWidthPolicy::ADDRESS_REGISTER_WIDTH_64):',
    "inherited<-easm_provenance_type(states,source)",
    "inherited_parameter<-easm_provenance_parameter(states,source)",
    'elif (op=="lea"orop=="leaq")anddestination_width==EasmAddressWidthPolicy::ADDRESS_REGISTER_WIDTH_64:',
    "source_register:sview=easm_memory_base_register(source_operand)",
    "ifEasmAddressWidthPolicy::address_register_width(source_register)==EasmAddressWidthPolicy::ADDRESS_REGISTER_WIDTH_64:",
    "inherited<-easm_provenance_type(states,source_register)",
    "inherited_parameter<-easm_provenance_parameter(states,source_register)",
    'elif (op=="add"orop=="addq"orop=="sub"orop=="subq"orop=="inc"orop=="incq"orop=="dec"orop=="decq")anddestination_width==EasmAddressWidthPolicy::ADDRESS_REGISTER_WIDTH_64:',
    "inherited<-easm_provenance_type(states,destination)",
    "inherited_parameter<-easm_provenance_parameter(states,destination)",
    "easm_provenance_set_parameter(states,destination,inherited,inherited_parameter)",
)
positions = [memory.find(compact(fragment)) for fragment in required_order]
if any(position < 0 for position in positions) or positions != sorted(positions):
    raise SystemExit("production provenance transfer no longer matches the proved preservation and clobber cases")
if memory.count('easm_provenance_set_parameter(states,destination,inherited,inherited_parameter)') != 1:
    raise SystemExit("every non-pseudo destination write must finish through the single fact-replacement step")
if memory.count('easm_provenance_set_parameter(states,source,destination_type,destination_parameter)') != 1 or \
        memory.count('easm_provenance_set_parameter(states,destination,source_type,source_parameter)') != 1:
    raise SystemExit("xchg must snapshot both provenance components before replacing either register")
xchg_start = memory.find('ifeasm_starts(instruction.op,"xchg"):')
xchg_end = memory.find('ifdestination=="":return', xchg_start)
expected_xchg_transfer = compact("""
if easm_starts(instruction.op, "xchg"):
    full_width_exchange: bool = destination_width == EasmAddressWidthPolicy::ADDRESS_REGISTER_WIDTH_64 and source_width == EasmAddressWidthPolicy::ADDRESS_REGISTER_WIDTH_64 and (op == "xchgq" or op == "xchg")
    if full_width_exchange and source != "" and destination != "":
        source_type: sview = easm_provenance_type(states, source)
        source_parameter: sview = easm_provenance_parameter(states, source)
        destination_type: sview = easm_provenance_type(states, destination)
        destination_parameter: sview = easm_provenance_parameter(states, destination)
        easm_provenance_set_parameter(states, source, destination_type, destination_parameter)
        easm_provenance_set_parameter(states, destination, source_type, source_parameter)
    else:
        easm_provenance_set_parameter(states, source, "", "") if source != ""
        easm_provenance_set_parameter(states, destination, "", "") if destination != ""
    return
""")
if xchg_start < 0 or xchg_end < 0 or memory[xchg_start:xchg_end] != expected_xchg_transfer:
    raise SystemExit("partial exchange must clear both parsed operand facts; only full-width exchanges may swap them")
destination_guard = memory.find('ifdestination=="":return')
if destination_guard < 6 or memory[destination_guard - 6:destination_guard] != "return":
    raise SystemExit("xchg handling must return before the ordinary destination-write transfer")
dispatch_start = memory.find("op:sview=instruction.op")
dispatch_end = memory.find("easm_provenance_set_parameter(states,destination,inherited,inherited_parameter)", dispatch_start)
if dispatch_start < 0 or dispatch_end < 0:
    raise SystemExit("could not isolate the ordinary register-write transfer")
dispatch = memory[dispatch_start:dispatch_end]
classified_ops = re.findall(r'op=="([a-z]+)"', dispatch)
if classified_ops != ["xchgq", "xchg", "mov", "movq", "lea", "leaq", "add", "addq", "sub", "subq", "inc", "incq", "dec", "decq"]:
    raise SystemExit("provenance-preserving opcode classes changed; revise the proof model before admission")

width_policy_source = compact(code_only(function_section(ADDRESS_POLICY.read_text(), "address_register_width")))
expected_width_policy = compact("""
def address_register_width(register: sview) -> i64:
    ensure when register:
        "rax" | "rcx" | "rdx" | "rbx" | "rsi" | "rdi" | "rbp" | "rsp" | "r8" | "r9" | "r10" | "r11" | "r12" | "r13" | "r14" | "r15" -> result == ADDRESS_REGISTER_WIDTH_64
        "eax" | "ecx" | "edx" | "ebx" | "esi" | "edi" | "ebp" | "esp" | "r8d" | "r9d" | "r10d" | "r11d" | "r12d" | "r13d" | "r14d" | "r15d" -> result == ADDRESS_REGISTER_WIDTH_32
        _ -> result == ADDRESS_REGISTER_WIDTH_UNKNOWN
    return match register:
        "rax" | "rcx" | "rdx" | "rbx" | "rsi" | "rdi" | "rbp" | "rsp" | "r8" | "r9" | "r10" | "r11" | "r12" | "r13" | "r14" | "r15": ADDRESS_REGISTER_WIDTH_64
        "eax" | "ecx" | "edx" | "ebx" | "esi" | "edi" | "ebp" | "esp" | "r8d" | "r9d" | "r10d" | "r11d" | "r12d" | "r13d" | "r14d" | "r15d": ADDRESS_REGISTER_WIDTH_32
        _: ADDRESS_REGISTER_WIDTH_UNKNOWN
""")
if width_policy_source != expected_width_policy:
    raise SystemExit("linear provenance width gates must use the exact proved 32/64/unknown register partition")
for width_tag, value in (("ADDRESS_REGISTER_WIDTH_UNKNOWN", 0), ("ADDRESS_REGISTER_WIDTH_32", 32), ("ADDRESS_REGISTER_WIDTH_64", 64)):
    if f"const{width_tag}:i64={value}" not in compact(ADDRESS_POLICY.read_text()):
        raise SystemExit(f"linear provenance width tag changed: {width_tag}")

implicit_write_source = compact(code_only(function_section(MEMORY_EFFECTS.read_text(), "easm_implicit_write_mask")))
expected_implicit_write_source = compact("""
def easm_implicit_write_mask(op: sview) -> i64:
    ensure result == EasmRegisterMasks::implicit_result_write_mask(op)
    return EasmRegisterMasks::implicit_result_write_mask(op)
""")
if implicit_write_source != expected_implicit_write_source:
    raise SystemExit("memory provenance clobber proof must delegate implicit-result masks to the canonical register model")

has_register = compact(code_only(function_section(MEMORY.read_text(), "easm_provenance_has_register")))
if has_register != compact("""
def easm_provenance_has_register(states: mutable darray[MemoryProvenance]&, register: sview) -> bool:
    for state in states:
        if easm_provenance_registers_equal(state.register, register):
            return true
    return false
"""):
    raise SystemExit("explicitly cleared provenance must remain distinguishable from an unseen register")
register_identity = compact(code_only(function_section(MEMORY.read_text(), "easm_provenance_registers_equal")))
if register_identity != compact("""
def easm_provenance_registers_equal(left: sview, right: sview) -> bool:
    left_bit: i64 = easm_register_bit(left)
    return left_bit != 0 and left_bit == easm_register_bit(right)
"""):
    raise SystemExit("linear provenance state must match canonical register aliases before width gates")
for helper, expected in (
    ("easm_provenance_type", """
        def easm_provenance_type(states: mutable darray[MemoryProvenance]&, register: sview) -> sview:
            for state in states:
                if easm_provenance_registers_equal(state.register, register):
                    return state.type_name
            return ""
    """),
    ("easm_provenance_set_parameter", """
        def easm_provenance_set_parameter(states: mutable darray[MemoryProvenance]&, register: sview, type_name: sview, parameter: sview) -> void:
            for index in 0..<states.count |index, states, register, type_name|:
                if easm_provenance_registers_equal(states[index].register, register):
                    states[index] <- MemoryProvenance{register: register, type_name: type_name, parameter: parameter}
                    return
            states.push(MemoryProvenance{register: register, type_name: type_name, parameter: parameter})
    """),
    ("easm_provenance_parameter", """
        def easm_provenance_parameter(states: mutable darray[MemoryProvenance]&, register: sview) -> sview:
            for state in states:
                if easm_provenance_registers_equal(state.register, register):
                    return state.parameter
            return ""
    """),
):
    if compact(code_only(function_section(MEMORY.read_text(), helper))) != compact(expected):
        raise SystemExit(f"memory provenance alias-aware helper changed: {helper}")
layout_role = compact(code_only(function_section(MEMORY.read_text(), "easm_verify_memory_roles")))
signature_fallback = "ifnoteasm_provenance_has_register(states,base):type_name<-easm_input_type_for_register(fn,base)"
tracked_lookup = "type_name:mutablesview=easm_provenance_type(states,base)"
if signature_fallback not in layout_role:
    raise SystemExit("layout checking must only fall back to signature provenance for an untracked register")
if tracked_lookup not in layout_role:
    raise SystemExit("layout checking must read tracked provenance before applying signature fallback")
if layout_role.find(tracked_lookup) > layout_role.find(signature_fallback):
    raise SystemExit("layout checking must read the tracked fact before deciding whether signature fallback is allowed")
if "ifEasmMemoryBasePolicy::rejects_untraced_raw_base(type_name!=\"\",easm_contract_has_word(fn.requires,\"memory.base.untyped\"))" not in layout_role:
    raise SystemExit("empty or untraced provenance must remain a rejected memory base")

proof_text = code_only(POSITIVE.read_text())
if declared_functions(POSITIVE) != POSITIVE_NAMES | MODEL_NAMES:
    raise SystemExit("positive EASM provenance proof inventory is incomplete or contains extras")
if declared_functions(NEGATIVE) != NEGATIVE_NAMES:
    raise SystemExit("negative EASM provenance proof inventory is incomplete or contains extras")
for fact in (
    "const PROV_CLOBBER: i64 = 0",
    "const PROV_MOVE: i64 = 1",
    "const PROV_LEA: i64 = 2",
    "const PROV_ADD: i64 = 3",
    "const PROV_SUB: i64 = 4",
    "const PROV_INC: i64 = 5",
    "const PROV_DEC: i64 = 6",
    "const PROV_XCHG: i64 = 7",
    "const PROV_PARTIAL_MOVE: i64 = 8",
    "const PROV_PARTIAL_XCHG: i64 = 9",
):
    if compact(fact) not in compact(proof_text):
        raise SystemExit(f"proof model is missing transfer class: {fact}")

if compact(proof_body(proof_text, "provenance_destination_after")) != compact("""
requires kind >= PROV_CLOBBER and kind <= PROV_PARTIAL_XCHG
if pseudo or not has_destination_register:
    return old_destination
if kind == PROV_MOVE or kind == PROV_XCHG:
    return old_source if has_source_register else false
if kind == PROV_LEA:
    return old_base if has_base_register else false
if kind == PROV_ADD or kind == PROV_SUB or kind == PROV_INC or kind == PROV_DEC:
    return old_destination
return false
"""):
    raise SystemExit("destination abstract transfer must model partial writes as clobbers")
if compact(proof_body(proof_text, "provenance_source_after")) != compact("""
requires kind >= PROV_CLOBBER and kind <= PROV_PARTIAL_XCHG
if pseudo or (kind != PROV_XCHG and kind != PROV_PARTIAL_XCHG) or not has_source_register:
    return old_source
if kind == PROV_PARTIAL_XCHG:
    return false
return old_destination if has_destination_register else false
"""):
    raise SystemExit("source abstract transfer must model both partial-exchange operand clobbers")

if compact(proof_body(proof_text, "provenance_after_implicit_clobber")) != compact(
    "ensure result == (old_provenance and not is_written)\n    return old_provenance and not is_written"
):
    raise SystemExit("implicit clobber model must erase exactly written-register facts")
if compact(proof_body(proof_text, "provenance_type_after_signature_fallback")) != compact(
    "ensure is_tracked implies result == tracked_type\n    ensure not is_tracked implies result == input_type\n    return tracked_type if is_tracked else input_type"
):
    raise SystemExit("signature fallback model must preserve present empty facts and consult inputs only when untracked")
if compact(proof_body(proof_text, "a_tracked_empty_fact_does_not_recover_input_type")) != compact(
    'requires input_type != ""\n    ensure result == true\n    return provenance_type_after_signature_fallback(true, "", input_type) == ""'
):
    raise SystemExit("tracked-empty theorem must establish that a prior clobber cannot recover signature provenance")
if compact(proof_body(proof_text, "an_untracked_input_register_uses_signature_provenance")) != compact(
    'requires input_type != ""\n    ensure result == true\n    return provenance_type_after_signature_fallback(false, "", input_type) == input_type'
):
    raise SystemExit("fallback theorem must retain legitimate signature provenance for unseen inputs")
if compact(proof_body(proof_text, "a_call_drops_existing_caller_saved_provenance")) != compact(
    "requires old_provenance\n    ensure result == false\n    return provenance_after_implicit_clobber(true, old_provenance)"
):
    raise SystemExit("caller-saved call theorem must prove invalidation of an established fact")
if compact(proof_body(proof_text, "a_call_preserves_existing_callee_saved_provenance")) != compact(
    "requires old_provenance\n    ensure result == true\n    return provenance_after_implicit_clobber(false, old_provenance)"
):
    raise SystemExit("callee-saved call theorem must preserve an established fact")
if compact(proof_body(proof_text, "a_partial_register_move_drops_the_destination_fact")) != compact(
    "requires not pseudo and has_source and old_source and old_destination\n    ensure result == false\n    return provenance_destination_after(PROV_PARTIAL_MOVE, pseudo, has_source, true, false, old_source, old_destination, false)"
):
    raise SystemExit("partial-width move theorem must reject copying even an established source carrier")
if compact(proof_body(proof_text, "a_partial_register_exchange_drops_both_operand_facts")) != compact(
    "requires not pseudo and has_source and has_destination and old_source and old_destination\n    ensure result == true\n    return (provenance_source_after(PROV_PARTIAL_XCHG, pseudo, has_source, has_destination, old_source, old_destination) == false and provenance_destination_after(PROV_PARTIAL_XCHG, pseudo, has_source, has_destination, false, old_source, old_destination, false) == false)"
):
    raise SystemExit("partial-width exchange theorem must establish clearing of both operand facts")
if compact(proof_body(proof_text, "an_implicit_result_write_drops_old_provenance")) != compact(
    "requires old_provenance\n    ensure result == false\n    return provenance_after_implicit_clobber(true, old_provenance)"
):
    raise SystemExit("defined implicit outputs must discard the prior carrier type")
negative_text = code_only(NEGATIVE.read_text())
if compact(proof_body(negative_text, "false_claim_call_preserves_caller_saved_provenance")) != compact(
    "requires old_provenance\n    ensure result == true\n    return provenance_after_implicit_clobber(true, old_provenance)"
):
    raise SystemExit("call false control must reject preserving an established caller-saved fact")
if compact(proof_body(negative_text, "false_claim_defined_implicit_result_preserves_old_provenance")) != compact(
    "requires old_provenance\n    ensure result == true\n    return provenance_after_implicit_clobber(true, old_provenance)"
):
    raise SystemExit("implicit-result false control must reject preserving an overwritten carrier")
for name, body in {
    "false_claim_partial_move_copies_pointer_provenance": "requires old_source and old_destination ensure result == true return provenance_destination_after(PROV_PARTIAL_MOVE, false, true, true, false, old_source, old_destination, false)",
    "false_claim_partial_exchange_preserves_source": "requires old_source and old_destination ensure result == true return provenance_source_after(PROV_PARTIAL_XCHG, false, true, true, old_source, old_destination)",
    "false_claim_partial_exchange_preserves_destination": "requires old_source and old_destination ensure result == true return provenance_destination_after(PROV_PARTIAL_XCHG, false, true, true, false, old_source, old_destination, false)",
}.items():
    if compact(proof_body(negative_text, name)) != compact(body):
        raise SystemExit(f"partial-register false control changed: {name}")
if compact(proof_body(negative_text, "false_claim_cleared_provenance_recovers_from_signature_input")) != compact(
    'requires input_type != ""\n    ensure result == true\n    return provenance_type_after_signature_fallback(true, "", input_type) == input_type'
):
    raise SystemExit("signature-fallback false control must challenge recovery of a clobbered carrier")

source_closure = source_include_closure([POSITIVE, NEGATIVE])
if ARGS.source_only:
    print(json.dumps({
        "source_bound": True,
        "positive_theorems": len(POSITIVE_NAMES),
        "model_functions": len(MODEL_NAMES),
        "false_claim_controls": len(NEGATIVE_NAMES),
        "source_closure_files": len(source_closure),
    }, sort_keys=True))
    raise SystemExit(0)

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("EASM provenance proofs require a strict proof build")

inputs = list(dict.fromkeys([
    BIN,
    BIN.with_name(BIN.name + ".manifest.json"),
    BIN.with_name(BIN.name + ".manifest.json.sha256"),
    PROVER / "ELISA_COMPILER_REV",
    Path(__file__),
    HERE / "proof_product_gate.py",
    MEMORY,
    MEMORY_EFFECTS,
    ADDRESS_POLICY,
    POSITIVE,
    NEGATIVE,
    *source_closure,
]))
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


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
assert not positive["findings"]
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == POSITIVE_NAMES | MODEL_NAMES

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert {row["name"] for row in negative["findings"]} == NEGATIVE_NAMES
assert all(row["kind"] == "ensure-unproven" and row["status"] == "unknown"
           for row in negative["findings"])
assert not NEGATIVE_NAMES & {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product
print(json.dumps({
    "admitted": True,
    "scope": "call clobbering, no-fabrication, stale-fact clearing, arithmetic preservation, pseudo no-op, and xchg swap for EASM type and parameter provenance",
    "positive_obligations": positive["summary"]["proven"],
    "unsafe_simplifications_refused": sorted(NEGATIVE_NAMES),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "source_sha256": hashes_before,
}, sort_keys=True))
