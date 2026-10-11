"""Admit the EASM register/ABI mask proof against a strict Elisa-proof product."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product


ROOT = Path(__file__).resolve().parents[2]
PROVER = ROOT.parent / "elisa-proof"
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
POSITIVE = HERE / "easm_register_masks.elisa"
NEGATIVE = HERE / "easm_register_masks_rejected.elisa"
MASKS = ROOT / "src/backend/easm_register_masks.elisa"
ENV = ROOT / "src/backend/codegen_env.elisa"
MODEL = ROOT / "src/backend/easm_model.elisa"
MEMORY = ROOT / "src/backend/easm_verify_memory.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")
if 'include "easm_register_masks.elisa"' not in ENV.read_text():
    raise SystemExit("backend environment no longer imports the canonical EASM register masks")
if 'include "../../src/backend/easm_register_masks.elisa"' not in POSITIVE.read_text():
    raise SystemExit("proof no longer imports the production register masks")

model = MODEL.read_text()
register_bit_body = model.split("def easm_register_bit(register: sview) -> i64:", 1)[1].split(
    "def easm_register_mask(text: sview)", 1
)[0]
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
for register, aliases in register_aliases.items():
    condition = " or ".join(f'easm_equal(register, "{alias}")' for alias in aliases)
    expected = f"if {condition}:\n                return EasmRegisterMasks::{register}"
    if expected not in register_bit_body:
        raise SystemExit(f"EASM register aliases for {register} no longer map to its proved bit")

register_scan = model.split("def easm_register_mask(text: sview) -> i64:", 1)[1].split(
    "def easm_substitution_at(", 1
)[0]
if re.search(r"mask\s*<-\s*mask\s*\|\s*\d+", register_scan):
    raise SystemExit("register scanning bypasses the canonical one-hot bit declarations")
for register in register_aliases:
    if f"mask <- mask | EasmRegisterMasks::{register} if easm_find(text, \"%{register.lower()}\")" not in register_scan:
        raise SystemExit(f"register scan no longer contributes the canonical {register} bit")

memory = MEMORY.read_text()
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
    "return EasmRegisterMasks::cpuid_write_mask()",
    "return EasmRegisterMasks::rdtsc_write_mask()",
):
    if fragment not in operation_effect + implicit_reads + implicit_writes:
        raise SystemExit(f"EASM implicit effects no longer use their proved mask: {fragment}")
if "out.live <- out.live & (~EasmRegisterMasks::call_invalidates_live_mask())" not in model:
    raise SystemExit("EASM call-flow transfer no longer uses the separately proved live-invalidation mask")

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
]
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
    "call_clobber_mask",
    "call_invalidates_live_mask",
    "callee_saved_gpr_mask",
    "cpuid_read_mask",
    "cpuid_write_mask",
    "rdtsc_write_mask",
    "every_register_has_its_canonical_one_hot_bit",
    "call_clobber_mask_is_exactly_the_caller_saved_union",
    "call_invalidation_mask_is_exactly_the_non_result_caller_saved_union",
    "callee_saved_gpr_mask_is_exactly_the_callee_saved_register_union",
    "cpuid_and_rdtsc_implicit_masks_match_their_register_effects",
}
assert expected <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["proven"] + 1 == negative["summary"]["obligations"]
assert [(finding["kind"], finding["name"]) for finding in negative["findings"]] == [
    ("ensure-unproven", "call_preserves_rcx")
]
assert "call_preserves_rcx" not in {
    row["name"] for row in negative["declaration_details"] if row.get("verified")
}

assert require_current_product(BIN, PROVER) == manifest, "proof-product provenance changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "EASM register identity bits, ABI call clobbers, and implicit CPU register effects",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": ["call_preserves_rcx"],
    "proof_binary_sha256": hashlib.sha256(BIN.read_bytes()).hexdigest(),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
