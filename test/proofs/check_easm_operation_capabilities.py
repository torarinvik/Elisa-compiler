"""Admit the EASM operation-to-capability policy proof against a strict proof product."""
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
POSITIVE = HERE / "easm_operation_capabilities.elisa"
NEGATIVE = HERE / "easm_operation_capabilities_rejected.elisa"
MEMORY = ROOT / "src/backend/easm_verify_memory.elisa"
PROVENANCE = ROOT / "src/backend/easm_verify_provenance.elisa"
FUNCTION = ROOT / "src/backend/easm_verify_function.elisa"

CAPABILITY_GROUPS = [
    ("x86_64.atomic.rmw", ("xchg", "xchgl", "xchgq")),
    ("x86_64.cpuid", ("cpuid",)),
    ("x86_64.rdtsc", ("rdtsc",)),
    ("x86_64.sse.lfence", ("lfence",)),
    ("x86_64.sse.pause", ("pause",)),
    ("aarch64.yield", ("yield",)),
    ("aarch64.cntvct", ("mrs", "isb")),
    ("x86_64.fpu_control", ("fldcw", "fnstcw", "stmxcsr", "ldmxcsr", "emms")),
    ("x86_64.simd_state", ("vzeroall",)),
    ("debug.trap", ("trap",)),
]
OPCODE_CODES = {
    "OP_XCHG": 0,
    "OP_CPUID": 1,
    "OP_RDTSC": 2,
    "OP_LFENCE": 3,
    "OP_PAUSE": 4,
    "OP_YIELD": 5,
    "OP_MRS": 6,
    "OP_ISB": 7,
    "OP_FLDCW": 8,
    "OP_FNSTCW": 9,
    "OP_STMXCSR": 10,
    "OP_LDMXCSR": 11,
    "OP_EMMS": 12,
    "OP_VZEROALL": 13,
    "OP_TRAP": 14,
    "OP_ORDINARY": 15,
    "OP_UNKNOWN": 16,
}
OPCODE_SPELLINGS = {
    "OP_XCHG": ("xchg", "xchgl", "xchgq"),
    "OP_CPUID": ("cpuid",),
    "OP_RDTSC": ("rdtsc",),
    "OP_LFENCE": ("lfence",),
    "OP_PAUSE": ("pause",),
    "OP_YIELD": ("yield",),
    "OP_MRS": ("mrs",),
    "OP_ISB": ("isb",),
    "OP_FLDCW": ("fldcw",),
    "OP_FNSTCW": ("fnstcw",),
    "OP_STMXCSR": ("stmxcsr",),
    "OP_LDMXCSR": ("ldmxcsr",),
    "OP_EMMS": ("emms",),
    "OP_VZEROALL": ("vzeroall",),
    "OP_TRAP": ("trap",),
}
CAPABILITY_CODES = {
    "CAP_NONE": 0,
    "CAP_ATOMIC_RMW": 1,
    "CAP_CPUID": 2,
    "CAP_RDTSC": 3,
    "CAP_LFENCE": 4,
    "CAP_PAUSE": 5,
    "CAP_YIELD": 6,
    "CAP_COUNTER": 7,
    "CAP_FPU_CONTROL": 8,
    "CAP_SIMD_STATE": 9,
    "CAP_DEBUG_TRAP": 10,
}
GROUP_MODEL_ROWS = [
    ("x86_64.atomic.rmw", "xchg_family_requires_atomic_rmw", ("OP_XCHG",), "CAP_ATOMIC_RMW"),
    ("x86_64.cpuid", "cpuid_requires_cpuid_capability", ("OP_CPUID",), "CAP_CPUID"),
    ("x86_64.rdtsc", "rdtsc_requires_counter_capability", ("OP_RDTSC",), "CAP_RDTSC"),
    ("x86_64.sse.lfence", "lfence_requires_fence_capability", ("OP_LFENCE",), "CAP_LFENCE"),
    ("x86_64.sse.pause", "pause_requires_pause_capability", ("OP_PAUSE",), "CAP_PAUSE"),
    ("aarch64.yield", "yield_requires_aarch64_capability", ("OP_YIELD",), "CAP_YIELD"),
    ("aarch64.cntvct", "counter_instructions_share_the_counter_capability", ("OP_MRS", "OP_ISB"), "CAP_COUNTER"),
    ("x86_64.fpu_control", "floating_point_control_instructions_share_one_capability", ("OP_FLDCW", "OP_FNSTCW", "OP_STMXCSR", "OP_LDMXCSR", "OP_EMMS"), "CAP_FPU_CONTROL"),
    ("x86_64.simd_state", "zero_all_requires_simd_state_capability", ("OP_VZEROALL",), "CAP_SIMD_STATE"),
    ("debug.trap", "trap_requires_debug_capability", ("OP_TRAP",), "CAP_DEBUG_TRAP"),
]
EXPECTED_DECLARATIONS = {
    "all_opcode_and_capability_codes_are_canonical",
    *(theorem for _, theorem, _, _ in GROUP_MODEL_ROWS),
    "ordinary_operation_has_no_special_capability",
    "unknown_operation_has_no_special_capability",
}
FALSE_CLAIMS = {
    "ordinary_move_requires_atomic_rmw",
    "xchg_does_not_require_an_atomic_capability",
    "yield_requires_the_x86_counter_capability",
}

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(value: str) -> str:
    return " ".join(value.split())


def body(source: str, signature: str) -> str:
    if signature not in source:
        raise SystemExit(f"missing production function: {signature}")
    return source.split(signature, 1)[1].split("\n        def ", 1)[0]


def proof_body(source: str, name: str) -> str:
    signature = f"def {name}("
    if signature not in source:
        raise SystemExit(f"missing proof function: {name}")
    function_tail = source.split(signature, 1)[1].split("\ndef ", 1)[0]
    return function_tail.split(":\n", 1)[1]


positive_text = POSITIVE.read_text()
actual_opcode_codes = {
    name: int(value)
    for name, value in re.findall(r"(?m)^const (OP_[A-Z0-9_]+): i64 = ([0-9]+)$", positive_text)
}
if actual_opcode_codes != OPCODE_CODES:
    raise SystemExit("proof opcode model no longer matches the checker’s closed operation inventory")
actual_capability_codes = {
    name: int(value)
    for name, value in re.findall(r"(?m)^const (CAP_[A-Z0-9_]+): i64 = ([0-9]+)$", positive_text)
}
if actual_capability_codes != CAPABILITY_CODES:
    raise SystemExit("proof capability model no longer matches the closed capability inventory")
if set(OPCODE_SPELLINGS) != set(OPCODE_CODES) - {"OP_ORDINARY", "OP_UNKNOWN"}:
    raise SystemExit("proof opcode-to-spelling table is incomplete")
model_source_groups = {
    capability: tuple(spelling for opcode in opcode_names for spelling in OPCODE_SPELLINGS[opcode])
    for capability, _, opcode_names, _ in GROUP_MODEL_ROWS
}
if model_source_groups != dict(CAPABILITY_GROUPS):
    raise SystemExit("proof opcode rows no longer correspond to production capability groups")

def returned_expression(source: str, name: str) -> str:
    content = proof_body(source, name)
    if "return " not in content:
        raise SystemExit(f"proof function has no return expression: {name}")
    expression = compact(content.split("return ", 1)[1])
    if expression.startswith("(") and expression.endswith(")"):
        expression = expression[1:-1].strip()
    return expression


for capability, theorem, opcode_names, capability_name in GROUP_MODEL_ROWS:
    expected = " and ".join(
        [f"{name} == {OPCODE_CODES[name]}" for name in opcode_names]
        + [f"{capability_name} == {CAPABILITY_CODES[capability_name]}"]
    )
    if returned_expression(positive_text, theorem) != compact(expected):
        raise SystemExit(f"proof row does not establish the canonical code for {capability}")

canonical_codes = [f"{name} == {value}" for name, value in OPCODE_CODES.items()]
canonical_codes += [f"{name} == {value}" for name, value in CAPABILITY_CODES.items()]
if returned_expression(positive_text, "all_opcode_and_capability_codes_are_canonical") != compact(" and ".join(canonical_codes)):
    raise SystemExit("canonical code theorem no longer covers every opcode and capability code")
for theorem, opcode in (
    ("ordinary_operation_has_no_special_capability", "OP_ORDINARY"),
    ("unknown_operation_has_no_special_capability", "OP_UNKNOWN"),
):
    expected = f"{opcode} == {OPCODE_CODES[opcode]} and CAP_NONE == 0"
    if returned_expression(positive_text, theorem) != compact(expected):
        raise SystemExit(f"{theorem} no longer proves the no-capability row")


memory = MEMORY.read_text()
capability_body = body(memory, "def easm_required_capability(op: sview) -> sview:")
clauses = re.findall(r"if\s+(.*?)\s*:\s*return\s+\"([^\"]*)\"", capability_body, re.S)
observed = []
for condition, capability in clauses:
    names = tuple(re.findall(r'easm_equal\(op,\s*"([^"]+)"\)', condition))
    normalized_condition = compact(condition)
    expected_condition = compact(" or ".join(f'easm_equal(op, "{name}")' for name in names))
    if not names or normalized_condition != expected_condition:
        raise SystemExit(f"capability branch is not a closed exact-equality group: {condition!r}")
    observed.append((capability, names))
if observed != CAPABILITY_GROUPS:
    raise SystemExit(f"production capability groups changed: {observed!r}")
if compact(capability_body).count('return ""') != 1:
    raise SystemExit("unclassified EASM operations must retain the no-capability fallback")

operation_effect = body(memory, "def easm_operation_effect(op: sview) -> OperationEffect:")
if "capability: sview = easm_required_capability(op)" not in operation_effect:
    raise SystemExit("operation effects no longer consume the proved capability classifier")
function_source = FUNCTION.read_text()
verify_instructions = body(function_source, "def verify_function_instructions(")
known_check = "not easm_known_op(inst.op)"
capability_check = "not easm_contract_has_word(fn.requires, capability)"
if known_check not in verify_instructions or capability_check not in verify_instructions:
    raise SystemExit("instruction verification no longer rejects unknown ops and enforces exact capability declarations")
if verify_instructions.index(known_check) > verify_instructions.index(capability_check):
    raise SystemExit("unknown operation rejection must precede capability classification")
if 'code: "missing-capability"' not in verify_instructions:
    raise SystemExit("missing capability is no longer reported as a verifier error")
provenance = PROVENANCE.read_text()
known_op = body(provenance, "def easm_known_op(op: sview) -> bool:")
if 'easm_equal(op, "mov")' not in known_op or 'easm_equal(op, "movgarbage")' in known_op:
    raise SystemExit("ordinary/unknown opcode model no longer matches the exact whitelist")

actual_declarations = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", positive_text))
if actual_declarations != EXPECTED_DECLARATIONS:
    raise SystemExit("positive capability proof declarations changed")
negative_text = NEGATIVE.read_text()
negative_declarations = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", negative_text))
if negative_declarations != FALSE_CLAIMS:
    raise SystemExit("capability false-claim controls changed")
negative_expressions = {
    "ordinary_move_requires_atomic_rmw": "OP_ORDINARY == OP_XCHG and CAP_ATOMIC_RMW == 1",
    "xchg_does_not_require_an_atomic_capability": "CAP_ATOMIC_RMW == CAP_NONE",
    "yield_requires_the_x86_counter_capability": "OP_YIELD == OP_RDTSC and CAP_COUNTER == CAP_RDTSC",
}
for theorem, expected in negative_expressions.items():
    if returned_expression(negative_text, theorem) != compact(expected):
        raise SystemExit(f"false-claim control changed for {theorem}")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("EASM capability proof requires a strict proof build")

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
    MEMORY,
    PROVENANCE,
    FUNCTION,
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
assert positive == run(POSITIVE)[1], "capability proof report changed across repeated runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert verified == EXPECTED_DECLARATIONS

negative_code, negative = run(NEGATIVE)
assert negative_code == 1 and negative["status"] == "failed"
assert negative["summary"]["obligations"] == positive["summary"]["obligations"] + 2 * len(FALSE_CLAIMS)
assert negative["summary"]["proven"] == negative["summary"]["obligations"] - len(FALSE_CLAIMS)
assert negative["summary"]["unproven"] == len(FALSE_CLAIMS)
assert negative == run(NEGATIVE)[1], "false-claim report changed across repeated runs"
assert {(finding["kind"], finding["name"]) for finding in negative["findings"]} == {
    ("ensure-unproven", name) for name in FALSE_CLAIMS
}
assert not FALSE_CLAIMS & {
    row["name"] for row in negative["declaration_details"] if row.get("verified")
}
assert require_current_product(BIN, PROVER) == manifest, "proof-product provenance changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "exact EASM operation-to-capability classification and instruction admission",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(FALSE_CLAIMS),
    "proof_binary_sha256": hashlib.sha256(BIN.read_bytes()).hexdigest(),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
