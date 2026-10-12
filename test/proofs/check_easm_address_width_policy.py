"""Admit the EASM address-register width proof against the production verifier."""
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
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
POSITIVE = HERE / "easm_address_width_policy.elisa"
NEGATIVE = HERE / "easm_address_width_policy_rejected.elisa"
POLICY = ROOT / "src/backend/easm_address_width_policy.elisa"
ENV = ROOT / "src/backend/codegen_env.elisa"
FUNCTION = ROOT / "src/backend/easm_verify_function.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(source: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in source.splitlines())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)(?:ghost[ \t]+)?def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}(?:@|(?:ghost[ \t]+)?def )", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


policy = POLICY.read_text()
expected_policy = """
def address_register_width(register: sview) -> i64:
    ensure result == (when register:
        "rax" | "rcx" | "rdx" | "rbx" | "rsi" | "rdi" | "rbp" | "rsp" | "r8" | "r9" | "r10" | "r11" | "r12" | "r13" | "r14" | "r15" -> ADDRESS_REGISTER_WIDTH_64
        "eax" | "ecx" | "edx" | "ebx" | "esi" | "edi" | "ebp" | "esp" | "r8d" | "r9d" | "r10d" | "r11d" | "r12d" | "r13d" | "r14d" | "r15d" -> ADDRESS_REGISTER_WIDTH_32
        _ -> ADDRESS_REGISTER_WIDTH_UNKNOWN
    )
    return match register:
        "rax" | "rcx" | "rdx" | "rbx" | "rsi" | "rdi" | "rbp" | "rsp" | "r8" | "r9" | "r10" | "r11" | "r12" | "r13" | "r14" | "r15": ADDRESS_REGISTER_WIDTH_64
        "eax" | "ecx" | "edx" | "ebx" | "esi" | "edi" | "ebp" | "esp" | "r8d" | "r9d" | "r10d" | "r11d" | "r12d" | "r13d" | "r14d" | "r15d": ADDRESS_REGISTER_WIDTH_32
        _: ADDRESS_REGISTER_WIDTH_UNKNOWN
"""
if compact(function_section(policy, "address_register_width")) != compact(expected_policy):
    raise SystemExit("address-register policy changed from its exact 32/64-bit partition")
for declaration in (
    "const ADDRESS_REGISTER_WIDTH_UNKNOWN: i64 = 0",
    "const ADDRESS_REGISTER_WIDTH_32: i64 = 32",
    "const ADDRESS_REGISTER_WIDTH_64: i64 = 64",
):
    if compact(declaration) not in compact(policy):
        raise SystemExit(f"address-register width constant changed: {declaration}")

env_text = ENV.read_text()
policy_include = 'include "easm_address_width_policy.elisa"'
function_include = 'include "easm_verify_function.elisa"'
if policy_include not in env_text or function_include not in env_text or \
        env_text.index(policy_include) > env_text.index(function_include):
    raise SystemExit("backend must load the proved address-width policy before EASM verification")

function_text = FUNCTION.read_text()
expected_width_helper = """
def easm_address_register_width(operand: sview) -> i64:
    return EasmAddressWidthPolicy::ADDRESS_REGISTER_WIDTH_UNKNOWN if not easm_operand_is_direct_register(operand)
    return EasmAddressWidthPolicy::address_register_width(easm_register_operand(operand))
"""
if compact(function_section(function_text, "easm_address_register_width")) != compact(expected_width_helper):
    raise SystemExit("EASM verifier no longer delegates register widths to the proved policy")
tuple_body = compact(function_section(function_text, "easm_memory_address_tuple_supported"))
for required in (
    "base_width: i64 = easm_address_register_width(base_field)",
    "index_width: i64 = easm_address_register_width(index_field)",
    "index_width == base_width and easm_register_bit(easm_register_operand(index_field)) != EasmRegisterMasks::RSP",
    "index_width == 0 or index_width != base_width",
):
    if compact(required) not in tuple_body:
        raise SystemExit(f"address tuple validation lost its width guard: {required}")

positive_names = {
    "address_register_width_matches_its_exact_partition",
    "r15_is_a_64_bit_address_register",
    "r15d_is_a_32_bit_address_register",
    "partial_and_instruction_pointer_registers_are_not_address_widths",
}
negative_names = {
    "a_64_bit_register_has_32_bit_address_width",
    "a_32_bit_register_has_64_bit_address_width",
    "an_unmodeled_partial_register_has_a_valid_address_width",
    "instruction_pointer_is_a_general_address_base",
}
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()
for source, expected, label in (
    (positive_text, positive_names, "positive"),
    (negative_text, negative_names, "negative"),
):
    actual = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", source))
    if actual != expected:
        raise SystemExit(f"{label} address-width proof declaration inventory changed")


def proof_body(source: str, name: str) -> str:
    section = function_section(source, name)
    colon = section.find(":\n")
    if colon < 0:
        raise SystemExit(f"could not find proof body: {name}")
    return compact(section[colon + 2:])


if '../../src/backend/easm_address_width_policy.elisa' not in positive_text:
    raise SystemExit("positive proof no longer imports the production address-width policy")
if './easm_address_width_policy.elisa' not in negative_text:
    raise SystemExit("negative controls no longer include the positive proof and policy")

expected_positive = {
    "address_register_width_matches_its_exact_partition": (
        "ensure result == true return EasmAddressWidthPolicy::address_register_width(register) == (when register: "
        '"rax" | "rcx" | "rdx" | "rbx" | "rsi" | "rdi" | "rbp" | "rsp" | "r8" | "r9" | "r10" | "r11" | "r12" | "r13" | "r14" | "r15" -> EasmAddressWidthPolicy::ADDRESS_REGISTER_WIDTH_64 '
        '"eax" | "ecx" | "edx" | "ebx" | "esi" | "edi" | "ebp" | "esp" | "r8d" | "r9d" | "r10d" | "r11d" | "r12d" | "r13d" | "r14d" | "r15d" -> EasmAddressWidthPolicy::ADDRESS_REGISTER_WIDTH_32 '
        '_ -> EasmAddressWidthPolicy::ADDRESS_REGISTER_WIDTH_UNKNOWN )'
    ),
    "r15_is_a_64_bit_address_register": (
        'ensure result == true return EasmAddressWidthPolicy::address_register_width("r15") == EasmAddressWidthPolicy::ADDRESS_REGISTER_WIDTH_64'
    ),
    "r15d_is_a_32_bit_address_register": (
        'ensure result == true return EasmAddressWidthPolicy::address_register_width("r15d") == EasmAddressWidthPolicy::ADDRESS_REGISTER_WIDTH_32'
    ),
    "partial_and_instruction_pointer_registers_are_not_address_widths": (
        'ensure result == true return ( EasmAddressWidthPolicy::address_register_width("al") == EasmAddressWidthPolicy::ADDRESS_REGISTER_WIDTH_UNKNOWN and EasmAddressWidthPolicy::address_register_width("rip") == EasmAddressWidthPolicy::ADDRESS_REGISTER_WIDTH_UNKNOWN )'
    ),
}
for name, expected in expected_positive.items():
    if proof_body(positive_text, name) != compact(expected):
        raise SystemExit(f"positive address-width proof changed: {name}")

expected_negative = {
    "a_64_bit_register_has_32_bit_address_width": 'ensure result == true return EasmAddressWidthPolicy::address_register_width("rax") == EasmAddressWidthPolicy::ADDRESS_REGISTER_WIDTH_32',
    "a_32_bit_register_has_64_bit_address_width": 'ensure result == true return EasmAddressWidthPolicy::address_register_width("eax") == EasmAddressWidthPolicy::ADDRESS_REGISTER_WIDTH_64',
    "an_unmodeled_partial_register_has_a_valid_address_width": 'ensure result == true return EasmAddressWidthPolicy::address_register_width("al") != EasmAddressWidthPolicy::ADDRESS_REGISTER_WIDTH_UNKNOWN',
    "instruction_pointer_is_a_general_address_base": 'ensure result == true return EasmAddressWidthPolicy::address_register_width("rip") == EasmAddressWidthPolicy::ADDRESS_REGISTER_WIDTH_64',
}
for name, expected in expected_negative.items():
    if proof_body(negative_text, name) != compact(expected):
        raise SystemExit(f"negative address-width claim changed: {name}")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("address-width proof requires a strict proof build")
compiler_head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], check=True,
                               capture_output=True, text=True).stdout.strip()
if compiler_head != manifest["compiler"]["source_revision"]:
    raise SystemExit("proof product was built from a different compiler revision")

compiler_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
compiler_provenance = Path(str(compiler_product) + ".provenance.json").resolve(strict=True)
inputs = [
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"), PROVER / "ELISA_COMPILER_REV",
    compiler_product, compiler_provenance, Path(__file__), HERE / "proof_product_gate.py",
    POSITIVE, NEGATIVE, POLICY, ENV, FUNCTION,
]
inputs.extend(source_include_closure([POSITIVE, NEGATIVE]))
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
assert positive["summary"]["proven"] == positive["summary"]["obligations"] and not positive["findings"]
assert positive == run(POSITIVE)[1], "address-width proof report changed across repeated runs"
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
    "scope": "exact EASM 32/64-bit address-register classifier",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(negative_names),
    "proof_binary_sha256": hashlib.sha256(BIN.read_bytes()).hexdigest(),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
