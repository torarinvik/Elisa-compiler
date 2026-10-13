"""Admit the EASM machine-op arity partition against the production verifier."""
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
POSITIVE = HERE / "easm_operand_arity.elisa"
NEGATIVE = HERE / "easm_operand_arity_rejected.elisa"
POLICY = ROOT / "src/backend/easm_operand_scan.elisa"
PROVENANCE = ROOT / "src/backend/easm_verify_provenance.elisa"
FUNCTION = ROOT / "src/backend/easm_verify_function.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(source: str) -> str:
    return " ".join(" ".join(line.split("#", 1)[0].split()) for line in source.splitlines()).strip()


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)(?:ghost[ \t]+)?def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}(?:@|(?:ghost[ \t]+)?def )", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def proof_body(source: str, name: str) -> str:
    section = function_section(source, name)
    colon = section.find(":\n")
    if colon < 0:
        raise SystemExit(f"could not find body of {name}")
    return compact(section[colon + 2:])


policy = POLICY.read_text()
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
classes = {name: tuple(mnemonic for group in groups for mnemonic in group) for name, groups in classifier_groups.items()}
for name, groups in classifier_groups.items():
    mnemonics = classes[name]
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

known_op = compact(function_section(PROVENANCE.read_text(), "easm_known_op"))
known_mnemonics = set(re.findall(r'easm_equal\(op, "([^"]+)"\)', known_op)) - {"compose", "state", "label"}
class_sets = [set(mnemonics) for mnemonics in classes.values()]
if any(class_sets[i] & class_sets[j] for i in range(len(class_sets)) for j in range(i + 1, len(class_sets))):
    raise SystemExit("machine-op arity classes overlap")
if set.union(*class_sets) != known_mnemonics:
    raise SystemExit("machine-op arity classes do not cover the closed production opcode set")

expected_needs_arity = """
def needs_arity_rejection(operand_count: usize) -> bool:
    ensure result == (operand_count > MAX_MODELED_OPERAND_COUNT)
    return operand_count > MAX_MODELED_OPERAND_COUNT
"""
if compact(function_section(policy, "needs_arity_rejection")) != compact(expected_needs_arity):
    raise SystemExit("modeled arity limit no longer rejects every count above two")

expected_arity = """
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
if compact(function_section(policy, "operand_arity_supported")) != compact(expected_arity):
    raise SystemExit("operand_arity_supported no longer implements its specified precedence partition")

instruction_code = compact(function_section(FUNCTION.read_text(), "verify_function_instructions"))
arity_guard = "unsupported_operands: mutable bool = not operand_scan.valid or EasmOperandScan::needs_arity_rejection(operand_scan.count)"
arity_policy = "unsupported_operands <- not EasmOperandScan::operand_arity_supported(inst.op, operand_scan.count)"
role_policy = "unsupported_operands <- not easm_instruction_operand_roles_supported(inst.op, operand_scan.count, source_operand, destination_operand) if not unsupported_operands"
known_gate = "if not unsupported_operands and easm_known_op(inst.op): unsupported_operands <- not EasmOperandScan::operand_arity_supported(inst.op, operand_scan.count) unsupported_operands <- not easm_instruction_operand_roles_supported(inst.op, operand_scan.count, source_operand, destination_operand) if not unsupported_operands"
unsupported_handler = "if unsupported_operands: issues.push(Issue{severity: Severity.Error, code: \"unsupported-operands\", line: inst.line, message: \"instruction operand shape is outside the verified EASM model\"}) continue"
safe_extraction = "if operand_scan.valid and operand_scan.count > 0 and operand_scan.count <= EasmOperandScan::MAX_MODELED_OPERAND_COUNT: source_end: usize = operand_scan.first_separator if operand_scan.first_separator < inst.text.len else inst.text.len"
if any(part not in instruction_code for part in (arity_guard, arity_policy, role_policy, known_gate, unsupported_handler, safe_extraction)):
    raise SystemExit("instruction verifier no longer rejects unsupported arities and operand roles")
role_check_at = instruction_code.index("not easm_instruction_operand_roles_supported(inst.op, operand_scan.count, source_operand, destination_operand)")
for extraction in (
    "source_operand <- easm_substitute_operand(easm_trim(inst.text[operand_scan.start:source_end]), inst)",
    "destination_operand <- easm_substitute_operand(easm_trim(inst.text[destination_start:inst.text.len]), inst)",
):
    if instruction_code.index(extraction) > role_check_at:
        raise SystemExit("operand-role validation reads slices before extracting them")
if instruction_code.index(arity_guard) > instruction_code.index(arity_policy) or instruction_code.index(arity_policy) > role_check_at:
    raise SystemExit("arity classification and role checks must run in order")
if role_check_at > instruction_code.index("capability: sview = easm_required_capability(inst.op)"):
    raise SystemExit("operand-role validation must run before per-instruction effect analysis")

positive_names = {
    "zero_arity_classifier_is_exact", "unary_arity_classifier_is_exact", "binary_arity_classifier_is_exact",
    "shift_arity_classifier_is_exact", "machine_opcode_arity_classes_are_disjoint",
    "machine_opcode_arity_classes_cover_exact_inventory", "supported_arity_matches_precedence_partition",
    "supported_machine_arity_never_exceeds_model", "unknown_opcode_has_no_supported_arity",
}
negative_names = {
    "ret_accepts_one_operand", "call_accepts_zero_operands", "movq_accepts_one_operand",
    "incq_accepts_two_operands", "shift_accepts_three_operands", "unknown_opcode_accepts_two_operands",
}

positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()
for path, source, names, label in (
    (POSITIVE, positive_text, positive_names, "positive"),
    (NEGATIVE, negative_text, negative_names, "negative"),
):
    actual = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", source))
    if actual != names:
        raise SystemExit(f"{label} arity proof declarations changed")
    if '../../src/backend/easm_operand_scan.elisa' not in source:
        raise SystemExit(f"{label} arity proof no longer imports the production classifier")

class_expr = {
    "zero_arity_classifier_is_exact": ("is_zero_operand_instruction", "zero"),
    "unary_arity_classifier_is_exact": ("is_one_operand_instruction", "one"),
    "binary_arity_classifier_is_exact": ("is_two_operand_instruction", "two"),
    "shift_arity_classifier_is_exact": ("is_shift_instruction", "shift"),
}
expected_positive = {}
for claim, (classifier, _) in class_expr.items():
    expression = " or ".join(f'op == "{mnemonic}"' for mnemonic in classes[classifier])
    expected_positive[claim] = f"ensure result == true return EasmOperandScan::{classifier}(op) == ( {expression} )"
expected_positive.update({
    "machine_opcode_arity_classes_are_disjoint": (
        "ensure result == true return not ( "
        "(EasmOperandScan::is_zero_operand_instruction(op) and EasmOperandScan::is_one_operand_instruction(op)) or "
        "(EasmOperandScan::is_zero_operand_instruction(op) and EasmOperandScan::is_two_operand_instruction(op)) or "
        "(EasmOperandScan::is_zero_operand_instruction(op) and EasmOperandScan::is_shift_instruction(op)) or "
        "(EasmOperandScan::is_one_operand_instruction(op) and EasmOperandScan::is_two_operand_instruction(op)) or "
        "(EasmOperandScan::is_one_operand_instruction(op) and EasmOperandScan::is_shift_instruction(op)) or "
        "(EasmOperandScan::is_two_operand_instruction(op) and EasmOperandScan::is_shift_instruction(op)) )"
    ),
    "machine_opcode_arity_classes_cover_exact_inventory": (
        "ensure result == true return ( EasmOperandScan::is_zero_operand_instruction(op) or "
        "EasmOperandScan::is_one_operand_instruction(op) or EasmOperandScan::is_two_operand_instruction(op) or "
        "EasmOperandScan::is_shift_instruction(op) ) == ( "
        + " or ".join(f'op == "{mnemonic}"' for mnemonic in sorted(known_mnemonics)) + " )"
    ),
    "supported_arity_matches_precedence_partition": (
        "ensure result == true return EasmOperandScan::operand_arity_supported(op, count) == ( "
        "(EasmOperandScan::is_zero_operand_instruction(op) and count == 0) or "
        "(not EasmOperandScan::is_zero_operand_instruction(op) and EasmOperandScan::is_one_operand_instruction(op) and count == 1) or "
        "(not EasmOperandScan::is_zero_operand_instruction(op) and not EasmOperandScan::is_one_operand_instruction(op) and EasmOperandScan::is_two_operand_instruction(op) and count == 2) or "
        "(not EasmOperandScan::is_zero_operand_instruction(op) and not EasmOperandScan::is_one_operand_instruction(op) and not EasmOperandScan::is_two_operand_instruction(op) and EasmOperandScan::is_shift_instruction(op) and (count == 1 or count == 2)) )"
    ),
    "supported_machine_arity_never_exceeds_model": (
        "requires EasmOperandScan::operand_arity_supported(op, count) ensure result == true "
        "return not EasmOperandScan::needs_arity_rejection(count)"
    ),
    "unknown_opcode_has_no_supported_arity": (
        'ensure result == true return not EasmOperandScan::operand_arity_supported("movgarbage", count)'
    ),
})
for name, expected in expected_positive.items():
    if proof_body(positive_text, name) != compact(expected):
        raise SystemExit(f"positive arity theorem changed: {name}")

expected_negative = {
    "ret_accepts_one_operand": 'ensure result == true return EasmOperandScan::operand_arity_supported("ret", 1.usize())',
    "call_accepts_zero_operands": 'ensure result == true return EasmOperandScan::operand_arity_supported("callq", 0.usize())',
    "movq_accepts_one_operand": 'ensure result == true return EasmOperandScan::operand_arity_supported("movq", 1.usize())',
    "incq_accepts_two_operands": 'ensure result == true return EasmOperandScan::operand_arity_supported("incq", 2.usize())',
    "shift_accepts_three_operands": 'ensure result == true return EasmOperandScan::operand_arity_supported("shlq", 3.usize())',
    "unknown_opcode_accepts_two_operands": 'ensure result == true return EasmOperandScan::operand_arity_supported("movgarbage", 2.usize())',
}
for name, expected in expected_negative.items():
    if proof_body(negative_text, name) != compact(expected):
        raise SystemExit(f"negative arity false claim changed: {name}")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("EASM arity proof requires a strict proof build")
compiler_head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], check=True,
                               capture_output=True, text=True).stdout.strip()
if compiler_head != manifest["compiler"]["source_revision"]:
    raise SystemExit("proof product was built from a different compiler revision")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"), PROVER / "ELISA_COMPILER_REV",
    stage1_product, stage1_provenance, Path(__file__), HERE / "proof_product_gate.py", POSITIVE, NEGATIVE,
    POLICY, PROVENANCE, FUNCTION,
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
assert positive == run(POSITIVE)[1], "arity proof report changed across repeated runs"
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
    "scope": "closed EASM machine-op arity partition and verifier integration",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(negative_names),
    "proof_binary_sha256": hashlib.sha256(BIN.read_bytes()).hexdigest(),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
