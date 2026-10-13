"""Bind width-aware production EASM provenance proofs to the exact transfer implementation."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
HERE = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument("--source-only", action="store_true",
                    help="check source and fixture bindings without invoking Elisa-Proof")
ARGS = parser.parse_args()
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=not ARGS.source_only)
POSITIVE = HERE / "easm_flow_width_transfer.elisa"
NEGATIVE = HERE / "easm_flow_width_transfer_rejected.elisa"
MODEL = ROOT / "src/backend/easm_model.elisa"
MASKS = ROOT / "src/backend/easm_register_masks.elisa"
WIDTH_POLICY = ROOT / "src/backend/easm_address_width_policy.elisa"

POSITIVE_NAMES = {
    "make_width_instruction",
    "snapshot_width_flow",
    "production_full_width_lea_copies_carrier_and_ambiguity",
    "production_lea_from_partial_base_clears_destination",
    "production_full_width_pointer_arithmetic_preserves_state",
    "production_partial_alias_arithmetic_clears_destination",
}
FALSE_CLAIMS = {
    "production_partial_base_lea_can_keep_a_stale_carrier",
    "production_partial_alias_arithmetic_can_keep_a_stale_carrier",
}

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(source: str) -> str:
    return "".join(source.split())


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
    section = function_section(source, name)
    colon = section.find(":\n")
    if colon < 0:
        raise SystemExit(f"could not locate proof body for {name}")
    return section[colon + 2:]


positive_text = code_only(POSITIVE.read_text())
negative_text = code_only(NEGATIVE.read_text())
if declared_functions(POSITIVE) != POSITIVE_NAMES:
    raise SystemExit("positive width-transfer proof inventory changed")
if declared_functions(NEGATIVE) != FALSE_CLAIMS:
    raise SystemExit("width-transfer false-claim controls changed")

model_source = MODEL.read_text()
transfer = compact(code_only(function_section(model_source, "easm_provenance_flow_transfer")))
lea_guard = compact("""
elif (op == "lea" or op == "leaq") and destination_width == EasmAddressWidthPolicy::ADDRESS_REGISTER_WIDTH_64:
    base: sview = easm_memory_base_register(source)
    base_slot: i64 = easm_provenance_slot(base)
    base_width: i64 = EasmAddressWidthPolicy::address_register_width(base)
    out.types[destination_slot.usize()] <- out.types[base_slot.usize()] if base_slot >= 0 and base_width == EasmAddressWidthPolicy::ADDRESS_REGISTER_WIDTH_64 else ""
    out.ambiguous <- out.ambiguous | (1 << destination_slot) if base_slot >= 0 and base_width == EasmAddressWidthPolicy::ADDRESS_REGISTER_WIDTH_64 and (out.ambiguous & (1 << base_slot)) != 0 else out.ambiguous & (~(1 << destination_slot))
""")
if lea_guard not in transfer:
    raise SystemExit("production LEA provenance must require both a 64-bit destination and a 64-bit base")
arithmetic_guard = compact("""
elif (op == "add" or op == "addq" or op == "sub" or op == "subq" or op == "inc" or op == "incq" or op == "dec" or op == "decq") and destination_width == EasmAddressWidthPolicy::ADDRESS_REGISTER_WIDTH_64:
    return out
else:
    out.types[destination_slot.usize()] <- ""
    out.ambiguous <- out.ambiguous & (~(1 << destination_slot))
""")
if arithmetic_guard not in transfer:
    raise SystemExit("production arithmetic provenance must preserve only supported 64-bit destinations")
for exact in (
    "destination_width: i64 = EasmAddressWidthPolicy::address_register_width(destination)",
    "source_width: i64 = EasmAddressWidthPolicy::address_register_width(source_register)",
    "if (op == \"mov\" or op == \"movq\") and destination_width == EasmAddressWidthPolicy::ADDRESS_REGISTER_WIDTH_64 and (source_slot < 0 or source_width == EasmAddressWidthPolicy::ADDRESS_REGISTER_WIDTH_64)",
):
    if compact(exact) not in transfer:
        raise SystemExit("production width transfer lost a register-width guard")

width_policy = compact(code_only(function_section(WIDTH_POLICY.read_text(), "address_register_width")))
if '"rax"|"rcx"|"rdx"|"rbx"|"rsi"|"rdi"|"rbp"|"rsp"|"r8"|"r9"|"r10"|"r11"|"r12"|"r13"|"r14"|"r15"->result==ADDRESS_REGISTER_WIDTH_64' not in width_policy:
    raise SystemExit("64-bit LEA proof requires the complete production 64-bit register partition")
if '"eax"|"ecx"|"edx"|"ebx"|"esi"|"edi"|"ebp"|"esp"|"r8d"|"r9d"|"r10d"|"r11d"|"r12d"|"r13d"|"r14d"|"r15d"->result==ADDRESS_REGISTER_WIDTH_32' not in width_policy:
    raise SystemExit("partial-alias proof requires the complete production 32-bit register partition")

register_bits = compact(code_only(function_section(MASKS.read_text(), "register_bit")))
for alias_group, bit in (
    ('"rax"|"eax"|"ax"|"al"', "RAX"),
    ('"rcx"|"ecx"|"cx"|"cl"', "RCX"),
):
    if f"{alias_group}->result=={bit}" not in register_bits or f"{alias_group}:{bit}" not in register_bits:
        raise SystemExit(f"width-transfer fixture requires the canonical {bit} alias bit")

expected_constructor = compact("""
def make_width_instruction(op: sview, text: sview) -> Easm::Instruction:
    return Easm::Instruction{
        op: op,
        text: text,
        line: 1,
        pseudo: false,
        substitution_count: 0,
        substitution0: Easm::Substitution{from: "", replacement: ""},
        substitution1: Easm::Substitution{from: "", replacement: ""},
        substitution2: Easm::Substitution{from: "", replacement: ""},
        substitution3: Easm::Substitution{from: "", replacement: ""}
    }
""")
if compact(function_section(positive_text, "make_width_instruction")) != expected_constructor:
    raise SystemExit("width-transfer fixture instruction constructor changed")
if compact(function_section(positive_text, "snapshot_width_flow")) != compact("""
def snapshot_width_flow(incoming: Easm::ProvenanceFlow) -> Easm::ProvenanceFlow:
    types: mutable darray[sview] = []
    for slot in 0..<incoming.types.count |slot, incoming, types|:
        types.push(incoming.types[slot])
    return Easm::ProvenanceFlow{types: types, ambiguous: incoming.ambiguous, valid: incoming.valid}
"""):
    raise SystemExit("width-transfer theorems must snapshot the complete pre-state before production mutates it")

expected_full_lea = compact("""
requires incoming.valid == true and incoming.types.count == 16
ensure result == true
before: Easm::ProvenanceFlow = snapshot_width_flow(incoming)
instruction: Easm::Instruction = make_width_instruction("leaq", "8(%rax), %rcx")
out: Easm::ProvenanceFlow = Easm::easm_provenance_flow_transfer(instruction, incoming)
return (
    out.valid == before.valid and
    out.types.count == before.types.count and
    out.types[1] == before.types[0] and
    out.ambiguous == ((before.ambiguous & (~EasmRegisterMasks::RCX)) | (EasmRegisterMasks::RCX if (before.ambiguous & EasmRegisterMasks::RAX) != 0 else 0)) and
    (forall slot in 0..<16: slot == 1 or out.types[slot] == before.types[slot])
)
""")
if compact(proof_body(positive_text, "production_full_width_lea_copies_carrier_and_ambiguity")) != expected_full_lea:
    raise SystemExit("full-width LEA theorem must preserve all carriers and transfer base ambiguity")

expected_partial_lea = compact("""
requires incoming.valid == true and incoming.types.count == 16
ensure result == true
before: Easm::ProvenanceFlow = snapshot_width_flow(incoming)
instruction: Easm::Instruction = make_width_instruction("leaq", "8(%eax), %rcx")
out: Easm::ProvenanceFlow = Easm::easm_provenance_flow_transfer(instruction, incoming)
return (
    out.valid == before.valid and
    out.types.count == before.types.count and
    out.types[1] == "" and
    out.ambiguous == (before.ambiguous & (~EasmRegisterMasks::RCX)) and
    (forall slot in 0..<16:
        (slot == 1 or out.types[slot] == before.types[slot]) and
        (slot == 1 or (out.ambiguous & (1 << slot.i64())) == (before.ambiguous & (1 << slot.i64())))
    )
)
""")
if compact(proof_body(positive_text, "production_lea_from_partial_base_clears_destination")) != expected_partial_lea:
    raise SystemExit("partial-base LEA theorem must clear the destination carrier and ambiguity")

if compact(proof_body(positive_text, "production_full_width_pointer_arithmetic_preserves_state")) != compact("""
requires incoming.valid == true and incoming.types.count == 16
ensure result == true
before: Easm::ProvenanceFlow = snapshot_width_flow(incoming)
instruction: Easm::Instruction = make_width_instruction("addq", "$8, %rax")
out: Easm::ProvenanceFlow = Easm::easm_provenance_flow_transfer(instruction, incoming)
return (
    out.valid == before.valid and
    out.types.count == before.types.count and
    out.ambiguous == before.ambiguous and
    (forall slot in 0..<16: out.types[slot] == before.types[slot])
)
"""):
    raise SystemExit("full-width pointer arithmetic theorem must compare the whole production state")

expected_partial_arithmetic = compact("""
requires incoming.valid == true and incoming.types.count == 16
requires op == "add" or op == "addl"
ensure result == true
before: Easm::ProvenanceFlow = snapshot_width_flow(incoming)
instruction: Easm::Instruction = make_width_instruction(op, "$8, %eax")
out: Easm::ProvenanceFlow = Easm::easm_provenance_flow_transfer(instruction, incoming)
return (
    out.valid == before.valid and
    out.types.count == before.types.count and
    out.types[0] == "" and
    out.ambiguous == (before.ambiguous & (~EasmRegisterMasks::RAX)) and
    (forall slot in 1..<16:
        out.types[slot] == before.types[slot] and
        (out.ambiguous & (1 << slot.i64())) == (before.ambiguous & (1 << slot.i64()))
    )
)
""")
if compact(proof_body(positive_text, "production_partial_alias_arithmetic_clears_destination")) != expected_partial_arithmetic:
    raise SystemExit("partial-alias arithmetic theorem must cover both inferred and explicit narrow forms")

if compact(proof_body(negative_text, "production_partial_base_lea_can_keep_a_stale_carrier")) != compact("""
requires incoming.valid == true and incoming.types.count == 16 and incoming.types[1] != ""
ensure result == true
before: Easm::ProvenanceFlow = snapshot_width_flow(incoming)
instruction: Easm::Instruction = make_width_instruction("leaq", "8(%eax), %rcx")
out: Easm::ProvenanceFlow = Easm::easm_provenance_flow_transfer(instruction, incoming)
return out.types[1] == before.types[1]
"""):
    raise SystemExit("partial-base LEA false control must challenge stale destination invalidation")
if compact(proof_body(negative_text, "production_partial_alias_arithmetic_can_keep_a_stale_carrier")) != compact("""
requires incoming.valid == true and incoming.types.count == 16 and incoming.types[0] != ""
requires op == "add" or op == "addl"
ensure result == true
before: Easm::ProvenanceFlow = snapshot_width_flow(incoming)
instruction: Easm::Instruction = make_width_instruction(op, "$8, %eax")
out: Easm::ProvenanceFlow = Easm::easm_provenance_flow_transfer(instruction, incoming)
return out.types[0] == before.types[0]
"""):
    raise SystemExit("partial arithmetic false control must challenge stale destination invalidation")

source_closure = source_include_closure([POSITIVE, NEGATIVE])
if ARGS.source_only:
    print(json.dumps({
        "source_bound": True,
        "positive_theorems": len(POSITIVE_NAMES) - 2,
        "false_claim_controls": len(FALSE_CLAIMS),
        "source_closure_files": len(source_closure),
    }, sort_keys=True))
    raise SystemExit(0)

product = require_current_product(BIN, PROVER)
if product.get("compile_mode") != "strict":
    raise SystemExit("EASM width-transfer proofs require a strict proof build")
inputs = list(dict.fromkeys([
    BIN,
    BIN.with_name(BIN.name + ".manifest.json"),
    BIN.with_name(BIN.name + ".manifest.json.sha256"),
    PROVER / "ELISA_COMPILER_REV",
    Path(__file__),
    HERE / "proof_product_gate.py",
    POSITIVE,
    NEGATIVE,
    MODEL,
    MASKS,
    WIDTH_POLICY,
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
assert positive["summary"]["proven"] == positive["summary"]["obligations"] and not positive["findings"]
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == POSITIVE_NAMES
code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["unproven"] == len(FALSE_CLAIMS)
assert {finding["name"] for finding in negative["findings"]} == FALSE_CLAIMS
assert all(finding["kind"] == "ensure-unproven" and finding["status"] in {"unknown", "disproved"}
           for finding in negative["findings"])
assert not FALSE_CLAIMS & {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product
print(json.dumps({
    "admitted": True,
    "scope": "production EASM LEA and pointer arithmetic width gates",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(FALSE_CLAIMS),
    "proof_revision": product["proof"].get("head"),
}, sort_keys=True))
