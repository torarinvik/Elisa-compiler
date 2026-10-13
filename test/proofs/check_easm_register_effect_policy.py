"""Admit proofs of EASM register-destination reads against the production verifier."""
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
POSITIVE = HERE / "easm_register_effect_policy.elisa"
NEGATIVE = HERE / "easm_register_effect_policy_rejected.elisa"
MEMORY_POLICY = ROOT / "src/backend/easm_memory_effect_policy.elisa"
REGISTER_POLICY = ROOT / "src/backend/easm_register_effect_policy.elisa"
ENV = ROOT / "src/backend/codegen_env.elisa"
MEMORY = ROOT / "src/backend/easm_verify_memory.elisa"
PROVENANCE = ROOT / "src/backend/easm_verify_provenance.elisa"
FUNCTION = ROOT / "src/backend/easm_verify_function.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    return " ".join(text.split())


def code_compact(text: str) -> str:
    return compact("\n".join(line.split("#", 1)[0] for line in text.splitlines()))


def function_body(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^[ \t]*def {re.escape(name)}\([^\n]*\)[^\n]*:\n(.*?)(?=^[ \t]*def |\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"could not locate function {name}")
    return match.group(1)


def exact_equalities(source: str, name: str) -> set[str]:
    return set(re.findall(r'op\s*==\s*"([^"]+)"', function_body(source, name)))


def match_partition(source: str, name: str) -> tuple[set[str], str]:
    body = function_body(source, name)
    if body.count("return when op:") != 1:
        raise SystemExit(f"{name} must use one exhaustive opcode match")
    arms = body.split("return when op:", 1)[1]
    cases: set[str] = set()
    spellings: list[str] = []
    actions: set[str] = set()
    default_action: str | None = None
    for line in arms.splitlines():
        arm = re.match(r"^\s*(.*?)\s*->\s*(true|false)\s*$", line)
        if arm is None:
            continue
        pattern, action = arm.groups()
        if pattern == "_":
            if default_action is not None:
                raise SystemExit(f"{name} opcode match has multiple default arms")
            default_action = action
            continue
        arm_spellings = re.findall(r'"([^"]+)"', pattern)
        remainder = re.sub(r'"[^"]+"', "", pattern)
        if not arm_spellings or re.sub(r"[\s|]", "", remainder):
            raise SystemExit(f"{name} opcode match has a malformed explicit arm")
        spellings.extend(arm_spellings)
        cases.update(arm_spellings)
        actions.add(action)
    if default_action is None:
        raise SystemExit(f"{name} opcode match must have a boolean default")
    expected_action = "false" if default_action == "true" else "true"
    if actions != {expected_action}:
        raise SystemExit(f"{name} explicit opcode arms must agree and oppose the default")
    if not cases or len(cases) != len(spellings):
        raise SystemExit(f"{name} opcode match must have unique explicit spellings")
    return cases, default_action


def proof_body(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^def {re.escape(name)}\([^\n]*\)[^\n]*:\n(.*?)(?=^def |\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"could not locate proof declaration {name}")
    return compact(match.group(1))


memory_policy = MEMORY_POLICY.read_text()
register_policy = REGISTER_POLICY.read_text()
rmw = match_partition(memory_policy, "read_modify_write")[0]
compare_or_test = {"cmp", "cmpq", "test", "testq"}
zeroing = {"xor", "xorq", "sub", "subq"}
if match_partition(register_policy, "compare_or_test_reads_destination") != (compare_or_test, "false"):
    raise SystemExit("compare/test destination-read match table changed")
if match_partition(register_policy, "zeroing_alu_opcode") != (zeroing, "false"):
    raise SystemExit("self-zeroing opcode match table changed")

expected_register_read_contract = code_compact("""
    ensure result == (
        EasmMemoryEffectPolicy::read_modify_write(op) or
        compare_or_test_reads_destination(op)
    )
    return EasmMemoryEffectPolicy::read_modify_write(op) or compare_or_test_reads_destination(op)
""")
if code_compact(function_body(register_policy, "destination_reads_register")) != expected_register_read_contract:
    raise SystemExit("register-destination classifier no longer matches its production contract")

expected_self_zeroing_contract = code_compact("""
    ensure result == (
        source_register != "" and source_register == destination_register and
        zeroing_alu_opcode(op)
    )
    return false if:
        source_register == ""
        source_register != destination_register
    return zeroing_alu_opcode(op)
""")
if code_compact(function_body(register_policy, "is_self_zeroing")) != expected_self_zeroing_contract:
    raise SystemExit("self-zeroing implementation no longer matches its exact operands and opcode contract")

expected_destination_policy = code_compact("""
    ensure result == (
        has_register_destination and not self_zeroing and destination_reads_register(op)
    )
    return false if:
        not has_register_destination
        self_zeroing
    return destination_reads_register(op)
""")
if code_compact(function_body(register_policy, "reads_register_destination")) != expected_destination_policy:
    raise SystemExit("register-destination liveness policy no longer matches its contract")

environment = ENV.read_text()
memory_include = 'include "easm_memory_effect_policy.elisa"'
register_include = 'include "easm_register_effect_policy.elisa"'
model_include = 'include "easm_model.elisa"'
if any(item not in environment for item in (memory_include, register_include, model_include)):
    raise SystemExit("backend environment is missing a proved EASM instruction policy")
if not environment.index(memory_include) < environment.index(register_include) < environment.index(model_include):
    raise SystemExit("register effects must import their read/modify/write dependency before consumers")
positive_source = POSITIVE.read_text()
if 'include "../../src/backend/easm_memory_effect_policy.elisa"' not in positive_source or \
        'include "../../src/backend/easm_register_effect_policy.elisa"' not in positive_source:
    raise SystemExit("positive proof must import the production memory and register policies")
if positive_source.index('include "../../src/backend/easm_memory_effect_policy.elisa"') > positive_source.index(
    'include "../../src/backend/easm_register_effect_policy.elisa"'
):
    raise SystemExit("proof imports register policy before its production dependency")

memory = MEMORY.read_text()
reads_destination = code_compact(function_body(memory, "easm_reads_destination"))
expected_reads_destination = code_compact("""
    false return if instruction.pseudo
    destination: sview = easm_register_operand(easm_last_operand(instruction.text))
    false return if destination == ""
    return EasmRegisterEffectPolicy::reads_register_destination(instruction.op, destination != "", easm_self_zeroing(instruction))
""")
if reads_destination != expected_reads_destination:
    raise SystemExit("production destination-read verifier no longer delegates to the proved policy")
self_zeroing = code_compact(function_body(memory, "easm_self_zeroing"))
expected_self_zeroing = code_compact("""
    false return if instruction.pseudo
    source: sview = easm_register_operand(easm_first_operand(instruction.text))
    destination: sview = easm_register_operand(easm_last_operand(instruction.text))
    return EasmRegisterEffectPolicy::is_self_zeroing(instruction.op, source, destination)
""")
if self_zeroing != expected_self_zeroing:
    raise SystemExit("production self-zeroing verifier no longer delegates to the proved operand policy")

verify = function_body(FUNCTION.read_text(), "verify_function_instructions")
source_read = "if read_register.len > 0 and not easm_self_zeroing(inst) and not easm_live_has(live_registers, read_register)"
destination_read = "if easm_reads_destination(inst) and destination_read_register != read_register and not easm_live_has(live_registers, destination_read_register)"
if source_read not in verify or destination_read not in verify or verify.index(source_read) > verify.index(destination_read):
    raise SystemExit("function liveness must apply self-zeroing and destination-read policy before admitting the instruction")
if "not easm_contract_has_register(fn.preserves, destination_read_register)" not in verify:
    raise SystemExit("uninitialized destination reads must still be admitted only by a preserves contract")

known_body = function_body(PROVENANCE.read_text(), "easm_known_op")
known_code = "".join("\n".join(line.split("#", 1)[0] for line in known_body.splitlines()).split())
if re.fullmatch(r'return(?:easm_equal\(op,"[^"]+"\)or)*easm_equal\(op,"[^"]+"\)', known_code) is None:
    raise SystemExit("known EASM operations must remain a closed exact-equality whitelist")
known = set(re.findall(r'easm_equal\(op,\s*"([^"]+)"\)', known_body))
old_register_read_prefixes = ("add", "sub", "and", "or", "xor", "cmp", "test", "inc", "dec", "neg", "not", "sh", "sa", "xchg")
old_zeroing_prefixes = ("xor", "sub")
expected_read = {op for op in known if op.startswith(old_register_read_prefixes)}
observed_read = rmw | compare_or_test
if observed_read != expected_read:
    raise SystemExit("proved register-read opcode set no longer matches the old liveness classifier on known operations")
if zeroing != {op for op in known if op.startswith(old_zeroing_prefixes)}:
    raise SystemExit("proved zeroing-opcode set no longer matches the old self-zeroing classifier")

positive_names = {
    "read_modify_write_opcodes_read_the_old_register_destination",
    "compare_and_test_opcodes_read_the_old_register_destination",
    "ordinary_move_has_no_old_register_destination_read",
    "indirect_control_has_no_old_register_destination_read",
    "self_zeroing_recognizes_equal_nonempty_xor_and_sub_registers",
    "empty_or_distinct_operands_are_not_self_zeroing",
    "another_opcode_does_not_become_self_zeroing_for_equal_registers",
    "self_zeroing_suppresses_old_destination_reads",
    "a_present_nonzeroing_destination_uses_the_opcode_read_class",
    "absent_register_destinations_are_not_read",
}
negative_names = {
    "ordinary_move_reads_its_old_register_destination",
    "self_zeroing_xor_reads_its_old_destination",
    "distinct_xor_operands_are_self_zeroing",
    "indirect_call_reads_an_old_register_destination",
}
for source, expected, label in ((POSITIVE, positive_names, "positive"), (NEGATIVE, negative_names, "negative")):
    actual = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", source.read_text()))
    if actual != expected:
        raise SystemExit(f"{label} proof declarations changed")

positive_expected = {
    "read_modify_write_opcodes_read_the_old_register_destination": (
        "requires EasmMemoryEffectPolicy::read_modify_write(op) ensure result == true return "
        "EasmRegisterEffectPolicy::destination_reads_register(op)"
    ),
    "compare_and_test_opcodes_read_the_old_register_destination": (
        'requires op == "cmp" or op == "cmpq" or op == "test" or op == "testq" '
        "ensure result == true return EasmRegisterEffectPolicy::destination_reads_register(op)"
    ),
    "ordinary_move_has_no_old_register_destination_read": (
        "ensure result == true return not EasmRegisterEffectPolicy::destination_reads_register(\"movq\")"
    ),
    "indirect_control_has_no_old_register_destination_read": (
        "ensure result == true return not EasmRegisterEffectPolicy::destination_reads_register(\"callq\") and "
        "not EasmRegisterEffectPolicy::destination_reads_register(\"jmpq\")"
    ),
    "self_zeroing_recognizes_equal_nonempty_xor_and_sub_registers": (
        'requires (op == "xor" or op == "xorq" or op == "sub" or op == "subq") and '
        'source_register != "" and source_register == destination_register ensure result == true return '
        "EasmRegisterEffectPolicy::is_self_zeroing(op, source_register, destination_register)"
    ),
    "empty_or_distinct_operands_are_not_self_zeroing": (
        'requires source_register == "" or source_register != destination_register ensure result == false return '
        "EasmRegisterEffectPolicy::is_self_zeroing(op, source_register, destination_register)"
    ),
    "another_opcode_does_not_become_self_zeroing_for_equal_registers": (
        'requires not EasmRegisterEffectPolicy::zeroing_alu_opcode(op) and source_register != "" and '
        'source_register == destination_register ensure result == false return '
        "EasmRegisterEffectPolicy::is_self_zeroing(op, source_register, destination_register)"
    ),
    "self_zeroing_suppresses_old_destination_reads": (
        "requires EasmRegisterEffectPolicy::destination_reads_register(op) ensure result == false return "
        "EasmRegisterEffectPolicy::reads_register_destination(op, true, true)"
    ),
    "a_present_nonzeroing_destination_uses_the_opcode_read_class": (
        "requires EasmRegisterEffectPolicy::destination_reads_register(op) ensure result == true return "
        "EasmRegisterEffectPolicy::reads_register_destination(op, true, false)"
    ),
    "absent_register_destinations_are_not_read": (
        "ensure result == false return EasmRegisterEffectPolicy::reads_register_destination(op, false, self_zeroing)"
    ),
}
positive_text = POSITIVE.read_text()
for name, expected in positive_expected.items():
    if proof_body(positive_text, name) != compact(expected):
        raise SystemExit(f"positive theorem no longer proves its reviewed register claim: {name}")

negative_expected = {
    "ordinary_move_reads_its_old_register_destination": (
        "ensure result == true return EasmRegisterEffectPolicy::destination_reads_register(\"movq\")"
    ),
    "self_zeroing_xor_reads_its_old_destination": (
        "ensure result == true return EasmRegisterEffectPolicy::reads_register_destination(\"xorq\", true, true)"
    ),
    "distinct_xor_operands_are_self_zeroing": (
        "ensure result == true return EasmRegisterEffectPolicy::is_self_zeroing(\"xorq\", \"rax\", \"rbx\")"
    ),
    "indirect_call_reads_an_old_register_destination": (
        "ensure result == true return EasmRegisterEffectPolicy::destination_reads_register(\"callq\")"
    ),
}
negative_text = NEGATIVE.read_text()
for name, expected in negative_expected.items():
    if proof_body(negative_text, name) != compact(expected):
        raise SystemExit(f"negative false-claim control changed: {name}")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("EASM register-effect proof requires a strict proof build")
compiler_head = subprocess.run(
    ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
    check=True,
    capture_output=True,
    text=True,
).stdout.strip()
if compiler_head != manifest["compiler"]["source_revision"]:
    raise SystemExit("proof product was built from a different compiler revision")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", POSITIVE, NEGATIVE,
    MEMORY_POLICY, REGISTER_POLICY, ENV, MEMORY, PROVENANCE, FUNCTION,
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
assert positive_names <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["obligations"] - negative["summary"]["proven"] == len(negative_names)
assert {(finding["kind"], finding["name"]) for finding in negative["findings"]} == {
    ("ensure-unproven", name) for name in negative_names
}
assert not negative_names & {
    row["name"] for row in negative["declaration_details"] if row.get("verified")
}

assert require_current_product(BIN, PROVER) == manifest, "proof-product provenance changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "EASM register-destination liveness, compare/test reads, and self-zeroing suppression",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(negative_names),
    "proof_binary_sha256": hashlib.sha256(BIN.read_bytes()).hexdigest(),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
