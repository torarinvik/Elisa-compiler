"""Admit the EASM register/ABI mask proof against a strict Elisa-proof product."""
import argparse
import hashlib
from itertools import combinations
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure
from source_guard_compat import expand_return_if_blocks


argument_parser = argparse.ArgumentParser()
argument_parser.add_argument("--source-only", action="store_true",
                             help="check production and proof bindings without running Elisa-Proof")
ARGS = argument_parser.parse_args()
ROOT = Path(__file__).resolve().parents[2]
PROVER = ROOT.parent / "elisa-proof"
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=not ARGS.source_only)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
POSITIVE = HERE / "easm_register_masks.elisa"
NEGATIVE = HERE / "easm_register_masks_rejected.elisa"
MASKS = ROOT / "src/backend/easm_register_masks.elisa"
ENV = ROOT / "src/backend/codegen_env.elisa"
MODEL = ROOT / "src/backend/easm_model.elisa"
MEMORY = ROOT / "src/backend/easm_verify_memory.elisa"
MEMORY_EFFECTS = ROOT / "src/backend/easm_verify_memory_effects.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")
if 'include "easm_register_masks.elisa"' not in ENV.read_text():
    raise SystemExit("backend environment no longer imports the canonical EASM register masks")
if 'include "../../src/backend/easm_register_masks.elisa"' not in POSITIVE.read_text():
    raise SystemExit("proof no longer imports the production register masks")

mask_source = MASKS.read_text()
all_registers = ("RAX", "RCX", "RDX", "RBX", "RSI", "RDI", "RBP", "RSP",
                 "R8", "R9", "R10", "R11", "R12", "R13", "R14", "R15")
expected_mask_values = dict(zip(all_registers, (1, 2, 4, 8, 16, 32, 64, 128,
                                                256, 512, 1024, 2048, 4096, 8192,
                                                16384, 32768)))
actual_mask_values = {
    name: int(value) for name, value in re.findall(
        r"(?m)^        const (R[A-Z0-9]+): i64 = ([0-9]+)$", mask_source
    )
}
if {name: actual_mask_values.get(name) for name in all_registers} != expected_mask_values:
    raise SystemExit("canonical register masks no longer have the expected one-hot i64 assignments")
invalidation_body = mask_source.split("def call_invalidates_live_mask() -> i64:", 1)[1].split(
    "def callee_saved_gpr_mask()", 1
)[0]
if "ensure result + RAX == call_clobber_mask()" not in invalidation_body:
    raise SystemExit("call invalidation no longer exports preservation of the architectural result register")

positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()
pairwise_start = positive_text.find("def low_seven_register_masks_are_pairwise_disjoint() -> bool:")
if pairwise_start < 0:
    raise SystemExit("proof no longer states low-register pairwise disjointness")
pairwise_end = positive_text.find("\ndef ", pairwise_start + 1)
pairwise_body = positive_text[pairwise_start:pairwise_end if pairwise_end >= 0 else len(positive_text)]
pairwise_compact = "".join(expand_return_if_blocks(pairwise_body).split())
low_registers = ("RAX", "RCX", "RDX", "RBX", "RSI", "RDI", "RBP")
expected_disjoint_pairs = {
    f"(EasmRegisterMasks::{left}&EasmRegisterMasks::{right})==0"
    for left, right in combinations(low_registers, 2)
}
actual_disjoint_pairs = set(re.findall(
    r"\(EasmRegisterMasks::(R[A-Z0-9]+)&EasmRegisterMasks::(R[A-Z0-9]+)\)==0",
    pairwise_compact,
))
actual_disjoint_pairs = {f"(EasmRegisterMasks::{left}&EasmRegisterMasks::{right})==0" for left, right in actual_disjoint_pairs}
if actual_disjoint_pairs != expected_disjoint_pairs:
    raise SystemExit("pairwise-disjointness theorem no longer covers exactly every low-register pair")
if pairwise_compact.count("EasmRegisterMasks::") != 2 * len(expected_disjoint_pairs):
    raise SystemExit("pairwise-disjointness theorem contains an untracked register-mask reference")
full_start = positive_text.find("def all_register_masks_are_pairwise_disjoint() -> bool:")
if full_start < 0:
    raise SystemExit("proof no longer states full register-mask pairwise disjointness")
full_end = positive_text.find("\ndef ", full_start + 1)
full_body = positive_text[full_start:full_end if full_end >= 0 else len(positive_text)]
full_compact = "".join(expand_return_if_blocks(full_body).split())
expected_full_pairs = {
    f"(EasmRegisterMasks::{left}&EasmRegisterMasks::{right})==0i64"
    for left, right in combinations(all_registers, 2)
}
actual_full_pairs = {
    f"(EasmRegisterMasks::{left}&EasmRegisterMasks::{right})==0i64"
    for left, right in re.findall(
        r"\(EasmRegisterMasks::(R[A-Z0-9]+)&EasmRegisterMasks::(R[A-Z0-9]+)\)==0i64",
        full_compact,
    )
}
if actual_full_pairs != expected_full_pairs or full_compact.count("EasmRegisterMasks::") != 2 * len(expected_full_pairs):
    raise SystemExit("full mask-disjointness theorem no longer covers exactly every canonical register pair")
if "def rax_and_rcx_masks_overlap() -> bool:" not in negative_text or "(EasmRegisterMasks::RAX & EasmRegisterMasks::RCX) != 0" not in negative_text:
    raise SystemExit("rejected proof no longer challenges the RAX/RCX collision claim")
rejected_claims = {
    "call_preserves_rcx": "(EasmRegisterMasks::call_clobber_mask() & EasmRegisterMasks::RCX) == 0",
    "live_invalidation_equals_full_clobber_mask": "EasmRegisterMasks::call_invalidates_live_mask() == EasmRegisterMasks::call_clobber_mask()",
    "rax_and_rcx_masks_overlap": "(EasmRegisterMasks::RAX & EasmRegisterMasks::RCX) != 0",
    "rip_is_the_rsp_register": "EasmRegisterMasks::register_bit(\"rip\") == EasmRegisterMasks::RSP",
    "uppercase_rax_is_a_register_alias": "EasmRegisterMasks::register_bit(\"RAX\") == EasmRegisterMasks::RAX",
    "r16_is_a_supported_register_alias": "EasmRegisterMasks::register_bit(\"r16\") == EasmRegisterMasks::R15",
    "high_byte_alias_is_supported": "EasmRegisterMasks::register_bit(\"ah\") == EasmRegisterMasks::RAX",
    "byte_alias_has_a_distinct_register_bit": "EasmRegisterMasks::register_bit(\"al\") == 65536",
    "r14_and_r15_masks_overlap": "(EasmRegisterMasks::R14 & EasmRegisterMasks::R15) != 0i64",
}
actual_rejected_claims = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(\) -> bool:", negative_text))
if actual_rejected_claims != set(rejected_claims):
    raise SystemExit("rejected proof no longer contains exactly the tracked false claims")
expected_positive_claims = {
    "register_bit_matches_its_exhaustive_alias_spec",
    "every_supported_register_alias_selects_its_canonical_bit",
    "unsupported_register_names_have_no_general_purpose_bit",
    "every_register_has_its_canonical_one_hot_bit",
    "low_seven_register_masks_are_pairwise_disjoint",
    "all_register_masks_are_pairwise_disjoint",
    "all_register_masks_are_pairwise_disjoint",
    "call_clobber_mask_is_exactly_the_caller_saved_union",
    "call_invalidation_mask_is_exactly_the_non_result_caller_saved_union",
    "call_invalidation_preserves_the_architectural_result_register",
    "callee_saved_gpr_mask_is_exactly_the_callee_saved_register_union",
    "cpuid_and_rdtsc_implicit_masks_match_their_register_effects",
}
actual_positive_claims = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(.*\) -> bool:", positive_text))
if actual_positive_claims != expected_positive_claims:
    raise SystemExit("positive proof no longer contains exactly the tracked register-mask claims")
for name, claim in rejected_claims.items():
    declaration = negative_text.split(f"def {name}() -> bool:", 1)[1].split("\ndef ", 1)[0]
    declaration_compact = "".join(declaration.split())
    if "ensureresult==true" not in declaration_compact or f"return{''.join(claim.split())}" not in declaration_compact:
        raise SystemExit(f"rejected proof changed the tracked false claim {name}")

model = MODEL.read_text()
register_aliases = {
    "RAX": ("rax", "eax", "ax", "al"),
    "RCX": ("rcx", "ecx", "cx", "cl"),
    "RDX": ("rdx", "edx", "dx", "dl"),
    "RBX": ("rbx", "ebx", "bx", "bl"),
    "RSI": ("rsi", "esi", "si", "sil"),
    "RDI": ("rdi", "edi", "di", "dil"),
    "RBP": ("rbp", "ebp", "bp", "bpl"),
    "RSP": ("rsp", "esp", "sp", "spl"),
    "R8": ("r8", "r8d", "r8w", "r8b"),
    "R9": ("r9", "r9d", "r9w", "r9b"),
    "R10": ("r10", "r10d", "r10w", "r10b"),
    "R11": ("r11", "r11d", "r11w", "r11b"),
    "R12": ("r12", "r12d", "r12w", "r12b"),
    "R13": ("r13", "r13d", "r13w", "r13b"),
    "R14": ("r14", "r14d", "r14w", "r14b"),
    "R15": ("r15", "r15d", "r15w", "r15b"),
}
register_names = [alias for aliases in register_aliases.values() for alias in aliases]
register_bit_source = MASKS.read_text().split(
    "def register_bit(register: sview) -> i64:", 1
)[1].split("def call_clobber_mask()", 1)[0]
register_bit_compact = "".join(register_bit_source.split())
contract_marker = "ensurewhenregister:"
match_marker = "returnmatchregister:"
if contract_marker not in register_bit_compact or match_marker not in register_bit_compact:
    raise SystemExit("canonical EASM register-bit helper lost its exact contract or match implementation")
contract_spec, match_implementation = register_bit_compact.split(contract_marker, 1)[1].split(
    match_marker, 1
)
for register, aliases in register_aliases.items():
    alias_pattern = "|".join(f'"{alias}"' for alias in aliases)
    if f"{alias_pattern}->result=={register}" not in contract_spec:
        raise SystemExit(f"register-bit contract no longer maps {register} aliases to its canonical bit")
    if f"{alias_pattern}:{register}" not in match_implementation:
        raise SystemExit(f"register-bit implementation no longer maps {register} aliases to its canonical bit")
if re.findall(r'"([a-z0-9]+)"', contract_spec) != register_names:
    raise SystemExit("register-bit contract has a missing, duplicate, or untracked alias")
if re.findall(r'"([a-z0-9]+)"', match_implementation) != register_names:
    raise SystemExit("register-bit match has a missing, duplicate, or untracked alias")
if "_->result==0" not in contract_spec or "_:0" not in match_implementation:
    raise SystemExit("unknown register names must map to zero in both the contract and implementation")

register_wrapper = model.split("def easm_register_bit(register: sview) -> i64:", 1)[1].split(
    "def easm_register_mask(text: sview)", 1
)[0]
if "".join(register_wrapper.split()) != (
    "ensure result == EasmRegisterMasks::register_bit(register)"
    "return EasmRegisterMasks::register_bit(register)"
).replace(" ", ""):
    raise SystemExit("EASM model register-bit wrapper no longer delegates exactly to the proved alias map")

alias_spec_theorem = positive_text.split(
    "def register_bit_matches_its_exhaustive_alias_spec(register: sview) -> bool:", 1
)
if len(alias_spec_theorem) != 2:
    raise SystemExit("proof no longer states a universal register-bit alias specification")
alias_spec_body = alias_spec_theorem[1].split("\ndef every_supported_register_alias_selects_its_canonical_bit()", 1)[0]
alias_spec_compact = "".join(alias_spec_body.split())
expected_spec = "".join(
    "|".join(f'"{alias}"' for alias in aliases) + f"->EasmRegisterMasks::{register}"
    for register, aliases in register_aliases.items()
) + "_->0"
if "ensure result == true".replace(" ", "") not in alias_spec_compact:
    raise SystemExit("universal register-bit alias theorem no longer requires true")
if "returnEasmRegisterMasks::register_bit(register)==(whenregister:" not in alias_spec_compact:
    raise SystemExit("universal register-bit alias theorem no longer compares the helper to its exact map")
proof_spec = alias_spec_compact.split("==(whenregister:", 1)[1].split(")", 1)[0]
if proof_spec != expected_spec:
    raise SystemExit("universal register-bit alias theorem no longer covers exactly the production alias map")

concrete_alias_theorem = positive_text.split(
    "def every_supported_register_alias_selects_its_canonical_bit() -> bool:", 1
)
if len(concrete_alias_theorem) != 2:
    raise SystemExit("proof no longer checks each concrete architectural register alias")
concrete_alias_body = concrete_alias_theorem[1].split(
    "\ndef unsupported_register_names_have_no_general_purpose_bit()", 1
)[0]
concrete_pairs = re.findall(
    r'EasmRegisterMasks::register_bit\("([a-z0-9]+)"\)==EasmRegisterMasks::(R[A-Z0-9]+)',
    "".join(concrete_alias_body.split()),
)
expected_pairs = [(alias, register) for register, aliases in register_aliases.items() for alias in aliases]
if concrete_pairs != expected_pairs:
    raise SystemExit("concrete alias proof no longer checks every spelling against its canonical bit")

unknown_theorem = positive_text.split(
    "def unsupported_register_names_have_no_general_purpose_bit() -> bool:", 1
)
if len(unknown_theorem) != 2:
    raise SystemExit("proof no longer checks unsupported register names")
unknown_body = unknown_theorem[1].split("\ndef every_register_has_its_canonical_one_hot_bit()", 1)[0]
unknown_pairs = re.findall(
    r'EasmRegisterMasks::register_bit\("([A-Za-z0-9]*)"\)==0',
    "".join(unknown_body.split()),
)
if unknown_pairs != ["rip", "RAX", "r16", "ah", ""]:
    raise SystemExit("unsupported-register proof no longer covers pseudo, case-mismatched, unsupported, and empty names")

operand_mask = model.split("def easm_operand_register_mask(operand: sview) -> i64:", 1)[1].split(
    "def easm_instruction_register_mask(", 1
)[0]
if "easm_register_bit(easm_register_operand(operand))" not in operand_mask:
    raise SystemExit("operand register scanning no longer normalizes direct aliases through the proved register-bit map")
for helper in ("easm_memory_base_register(operand)", "easm_memory_index_register(operand)"):
    if helper not in operand_mask:
        raise SystemExit(f"operand register scanning no longer includes address component {helper}")

instruction_mask = model.split("def easm_instruction_register_mask(instruction: Instruction) -> i64:", 1)[1].split(
    "def easm_written_mask(", 1
)[0]
if "easm_operand_register_mask(easm_substitute_operand(easm_first_operand(instruction.text), instruction))" not in instruction_mask:
    raise SystemExit("instruction masks no longer include source aliases from parsed operands")
if "easm_operand_register_mask(easm_substitute_operand(easm_last_operand(instruction.text), instruction))" not in instruction_mask:
    raise SystemExit("instruction masks no longer include destination address aliases from parsed operands")
if "easm_operand_register_mask(substitution.replacement)" not in instruction_mask:
    raise SystemExit("instruction masks no longer include aliases introduced by operand substitutions")

read_mask = model.split("def easm_read_mask(instruction: Instruction) -> i64:", 1)[1].split(
    "def easm_label_name(", 1
)[0]
for fragment in (
    "return 0 if easm_self_zeroing(instruction)",
    "return easm_operand_register_mask(source) | destination_reads",
    "return 0 if easm_register_operand(destination) != \"\" else easm_operand_register_mask(destination)",
):
    if fragment not in read_mask:
        raise SystemExit(f"EASM read-mask transfer is missing required alias/read behavior: {fragment}")

register_scan = model.split("def easm_register_mask(text: sview) -> i64:", 1)[1].split(
    "def easm_substitution_at(", 1
)[0]
if re.search(r"mask\s*<-\s*mask\s*\|\s*\d+", register_scan):
    raise SystemExit("register scanning bypasses the canonical one-hot bit declarations")
for register in register_aliases:
    if f"mask <- mask | EasmRegisterMasks::{register} if easm_find(text, \"%{register.lower()}\")" not in register_scan:
        raise SystemExit(f"register scan no longer contributes the canonical {register} bit")

memory = MEMORY_EFFECTS.read_text()
operation_effect = memory.split("def easm_operation_effect(op: sview)", 1)[1].split(
    "def easm_implicit_read_mask(", 1
)[0]
implicit_reads = memory.split("def easm_implicit_read_mask(op: sview)", 1)[1].split(
    "def easm_implicit_write_mask(", 1
)[0]
implicit_writes = memory.split("def easm_implicit_write_mask(op: sview)", 1)[1].split(
    "def easm_immediate_after_dollar(", 1
)[0]
for fragment in (
    "implicit_writes <- EasmRegisterMasks::call_clobber_mask()",
    "return EasmRegisterMasks::cpuid_read_mask()",
    "return EasmRegisterMasks::implicit_result_write_mask(op)",
):
    if fragment not in operation_effect + implicit_reads + implicit_writes:
        raise SystemExit(f"EASM implicit effects no longer use their proved mask: {fragment}")
if "out.live <- out.live & (~EasmRegisterMasks::call_invalidates_live_mask())" not in model:
    raise SystemExit("EASM call-flow transfer no longer uses the separately proved live-invalidation mask")

if ARGS.source_only:
    source_closure = source_include_closure([POSITIVE, NEGATIVE])
    print(json.dumps({"source_bound": True,
                      "positive_claims": len(expected_positive_claims),
                      "false_claim_controls": len(rejected_claims),
                      "register_pairs_proved": len(expected_full_pairs),
                      "source_closure_files": len(source_closure)}, sort_keys=True))
    raise SystemExit(0)

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("EASM register-mask proof requires a strict proof build")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [
    BIN,
    MANIFEST,
    MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV",
    stage1_product,
    stage1_provenance,
    Path(__file__),
    HERE / "proof_product_gate.py",
    POSITIVE,
    NEGATIVE,
    MASKS,
    ENV,
    MODEL,
    MEMORY,
    MEMORY_EFFECTS,
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


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "proof report changed across repeated runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
expected = {
    "register_bit",
    "call_clobber_mask",
    "call_invalidates_live_mask",
    "callee_saved_gpr_mask",
    "cpuid_read_mask",
    "cpuid_write_mask",
    "rdtsc_write_mask",
    "register_bit_matches_its_exhaustive_alias_spec",
    "every_supported_register_alias_selects_its_canonical_bit",
    "unsupported_register_names_have_no_general_purpose_bit",
    "every_register_has_its_canonical_one_hot_bit",
    "low_seven_register_masks_are_pairwise_disjoint",
    "call_clobber_mask_is_exactly_the_caller_saved_union",
    "call_invalidation_mask_is_exactly_the_non_result_caller_saved_union",
    "call_invalidation_preserves_the_architectural_result_register",
    "callee_saved_gpr_mask_is_exactly_the_callee_saved_register_union",
    "cpuid_and_rdtsc_implicit_masks_match_their_register_effects",
}
assert expected <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["proven"] + 9 == negative["summary"]["obligations"]
assert {(finding["kind"], finding["name"]) for finding in negative["findings"]} == {
    ("ensure-unproven", "call_preserves_rcx"),
    ("ensure-unproven", "live_invalidation_equals_full_clobber_mask"),
    ("ensure-unproven", "rax_and_rcx_masks_overlap"),
    ("ensure-unproven", "rip_is_the_rsp_register"),
    ("ensure-unproven", "uppercase_rax_is_a_register_alias"),
    ("ensure-unproven", "r16_is_a_supported_register_alias"),
    ("ensure-unproven", "high_byte_alias_is_supported"),
    ("ensure-unproven", "byte_alias_has_a_distinct_register_bit"),
    ("ensure-unproven", "r14_and_r15_masks_overlap"),
}
assert not {
    "call_preserves_rcx",
    "live_invalidation_equals_full_clobber_mask",
    "rax_and_rcx_masks_overlap",
    "rip_is_the_rsp_register",
    "uppercase_rax_is_a_register_alias",
    "r16_is_a_supported_register_alias",
    "high_byte_alias_is_supported",
    "byte_alias_has_a_distinct_register_bit",
    "r14_and_r15_masks_overlap",
} & {
    row["name"] for row in negative["declaration_details"] if row.get("verified")
}

assert require_current_product(BIN, PROVER) == manifest, "proof-product provenance changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "exact EASM register aliases, all canonical mask pairs, call-result preservation, ABI call clobbers, and implicit CPU register effects",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": [
        "call_preserves_rcx",
        "live_invalidation_equals_full_clobber_mask",
        "rax_and_rcx_masks_overlap",
        "rip_is_the_rsp_register",
        "uppercase_rax_is_a_register_alias",
        "r16_is_a_supported_register_alias",
        "high_byte_alias_is_supported",
        "byte_alias_has_a_distinct_register_bit",
        "r14_and_r15_masks_overlap",
    ],
    "proof_binary_sha256": hashlib.sha256(BIN.read_bytes()).hexdigest(),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
