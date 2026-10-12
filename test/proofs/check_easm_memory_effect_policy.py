"""Admit proofs of the production EASM explicit-memory-operand policy."""
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
POSITIVE = HERE / "easm_memory_effect_policy.elisa"
NEGATIVE = HERE / "easm_memory_effect_policy_rejected.elisa"
HELPER = ROOT / "src/backend/easm_memory_effect_policy.elisa"
ENV = ROOT / "src/backend/codegen_env.elisa"
MEMORY = ROOT / "src/backend/easm_verify_memory.elisa"
PROVENANCE = ROOT / "src/backend/easm_verify_provenance.elisa"

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


def function_section(source: str, name: str) -> str:
    match = re.search(
        rf"(?m)^def {re.escape(name)}\([^\n]*",
        source,
    )
    if match is None:
        raise SystemExit(f"could not locate proof declaration {name}")
    following = re.search(r"(?m)^def [A-Za-z_][A-Za-z0-9_]*\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def exact_equalities(source: str, function: str) -> set[str]:
    return set(re.findall(r'op\s*==\s*"([^"]+)"', function_body(source, function)))


def exact_inequalities(source: str, function: str) -> set[str]:
    return set(re.findall(r'op\s*!=\s*"([^"]+)"', function_body(source, function)))


def match_partition(source: str, function: str) -> tuple[set[str], str]:
    body = function_body(source, function)
    if body.count("return when op:") != 1:
        raise SystemExit(f"{function} must use one exhaustive opcode match")
    arms = body.split("return when op:", 1)[1]
    cases: set[str] = set()
    all_spellings: list[str] = []
    actions: set[str] = set()
    default_action: str | None = None
    for line in arms.splitlines():
        arm = re.match(r"^\s*(.*?)\s*->\s*(true|false)\s*$", line)
        if arm is None:
            continue
        pattern, action = arm.groups()
        if pattern == "_":
            if default_action is not None:
                raise SystemExit(f"{function} opcode match has multiple default arms")
            default_action = action
            continue
        arm_spellings = re.findall(r'"([^"]+)"', pattern)
        remainder = re.sub(r'"[^"]+"', "", pattern)
        if not arm_spellings or re.sub(r"[\s|]", "", remainder):
            raise SystemExit(f"{function} opcode match has a malformed explicit arm")
        all_spellings.extend(arm_spellings)
        cases.update(arm_spellings)
        actions.add(action)
    if default_action is None:
        raise SystemExit(f"{function} opcode match must have a boolean default")
    expected_action = "false" if default_action == "true" else "true"
    if actions != {expected_action}:
        raise SystemExit(f"{function} explicit opcode arms must agree and oppose the default")
    if not cases or len(cases) != len(all_spellings):
        raise SystemExit(f"{function} opcode match must have unique explicit spellings")
    return cases, default_action


def proof_body(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^def {re.escape(name)}\([^\n]*\)[^\n]*:\n(.*?)(?=^def |\Z)",
        source,
    )
    if match is None:
        raise SystemExit(f"could not locate proof declaration {name}")
    return " ".join(compact(match.group(1)).replace("can Abort.Panic:", "").split())


helper = HELPER.read_text()
read_modify_write = {
    "add", "addq", "sub", "subq", "and", "andq", "or", "orq", "xor", "xorq",
    "inc", "incq", "dec", "decq", "neg", "negq", "not", "notq", "shl", "shlq",
    "sal", "salq", "shr", "shrq", "sar", "sarq", "xchg", "xchgl", "xchgq",
}
exchange_memory = {"xchg", "xchgl", "xchgq"}
read_only = {"cmp", "cmpq", "test", "testq", "call", "callq", "jmp", "jmpq"}
no_destination_write = {
    "fldcw", "ldmxcsr", "cmp", "cmpq", "test", "testq", "push", "pushq",
    "call", "callq", "jmp", "jmpq",
}
if exact_equalities(helper, "read_modify_write") != read_modify_write:
    raise SystemExit("production read-modify-write opcode set changed")
if exact_equalities(helper, "destination_reads_memory") != read_only:
    raise SystemExit("production read-only destination set changed")
if exact_inequalities(helper, "destination_writes_memory") != no_destination_write:
    raise SystemExit("production no-write destination set changed")
if exact_equalities(helper, "exchanges_memory_operand") != exchange_memory:
    raise SystemExit("production symmetric memory-exchange opcode set changed")
for name in ("read_modify_write", "destination_reads_memory", "destination_writes_memory", "exchanges_memory_operand"):
    if "ensure result ==" not in function_body(helper, name):
        raise SystemExit(f"{name} must expose its result equation as a contract")
if match_partition(helper, "read_modify_write") != (read_modify_write, "false"):
    raise SystemExit("read-modify-write match table no longer agrees with its contract")
if match_partition(helper, "destination_reads_memory") != (read_modify_write | read_only, "false"):
    raise SystemExit("destination-read match table no longer agrees with its contract")
if match_partition(helper, "destination_writes_memory") != (no_destination_write, "true"):
    raise SystemExit("destination-write match table no longer agrees with its contract")
if match_partition(helper, "exchanges_memory_operand") != (exchange_memory, "false"):
    raise SystemExit("symmetric memory-exchange match table no longer agrees with its contract")
reads_contract = code_compact(function_body(helper, "memory_reads"))
expected_reads_contract = code_compact("""
    ensure result == (
        not pseudo and op != "lea" and op != "leaq" and
        op != "fnstcw" and op != "stmxcsr" and op != "pop" and op != "popq" and
        (source_memory or (destination_memory and destination_reads_memory(op)))
    )
    false return if pseudo
    false return if op == "lea" or op == "leaq"
    false return if op == "fnstcw" or op == "stmxcsr"
    false return if op == "pop" or op == "popq"
    return source_memory or (destination_memory and destination_reads_memory(op))
""")
if reads_contract != expected_reads_contract:
    raise SystemExit("memory-read policy no longer implements its exact contract and suppression order")
writes_contract = code_compact(function_body(helper, "memory_writes"))
expected_writes_contract = code_compact("""
    ensure result == (
        not pseudo and op != "lea" and op != "leaq" and (
            (destination_memory and destination_writes_memory(op)) or
            (source_memory and exchanges_memory_operand(op))
        )
    )
    false return if pseudo
    false return if op == "lea" or op == "leaq"
    return (
        (destination_memory and destination_writes_memory(op)) or
        (source_memory and exchanges_memory_operand(op))
    )
""")
if writes_contract != expected_writes_contract:
    raise SystemExit("memory-write policy no longer implements its exact operand-shape gate")

environment = ENV.read_text()
include = 'include "easm_memory_effect_policy.elisa"'
if include not in environment or environment.index(include) > environment.index('include "easm_model.elisa"'):
    raise SystemExit("backend environment must import the policy before EASM verifier consumers")
if 'include "../../src/backend/easm_memory_effect_policy.elisa"' not in POSITIVE.read_text():
    raise SystemExit("positive proof no longer imports the production policy")

memory = MEMORY.read_text()
reads = function_body(memory, "easm_memory_reads")
writes = function_body(memory, "easm_memory_writes")
expected_reads_wrapper = code_compact("""
    source: sview = easm_substitute_operand(easm_first_operand(instruction.text), instruction)
    destination: sview = easm_substitute_operand(easm_last_operand(instruction.text), instruction)
    source_memory: bool = easm_memory_operand(source)
    destination_memory: bool = easm_memory_operand(destination)
    return EasmMemoryEffectPolicy::memory_reads(instruction.op, instruction.pseudo, source_memory, destination_memory)
""")
if code_compact(reads) != expected_reads_wrapper:
    raise SystemExit("memory-read verifier no longer delegates its complete effect decision to the proved policy")
expected_writes_wrapper = code_compact("""
    source: sview = easm_substitute_operand(easm_first_operand(instruction.text), instruction)
    destination: sview = easm_substitute_operand(easm_last_operand(instruction.text), instruction)
    source_memory: bool = easm_memory_operand(source)
    destination_memory: bool = easm_memory_operand(destination)
    return EasmMemoryEffectPolicy::memory_writes(instruction.op, instruction.pseudo, destination_memory, source_memory)
""")
if code_compact(writes) != expected_writes_wrapper:
    raise SystemExit("memory-write verifier no longer delegates its complete effect decision to the proved policy")
if reads.index("source_memory: bool") > reads.index("destination_memory: bool") or reads.index("destination_memory: bool") > reads.index("EasmMemoryEffectPolicy::memory_reads"):
    raise SystemExit("read verifier must derive both operand-shape facts before applying the policy")
if writes.index("source_memory: bool") > writes.index("destination_memory: bool") or writes.index("destination_memory: bool") > writes.index("EasmMemoryEffectPolicy::memory_writes"):
    raise SystemExit("write verifier must derive both operand shapes before applying the policy")

known_ops = function_body(PROVENANCE.read_text(), "easm_known_op")
known_ops_code = "".join(
    "\n".join(line.split("#", 1)[0] for line in known_ops.splitlines()).split()
)
if re.fullmatch(r'return(?:easm_equal\(op,"[^"]+"\)or)*easm_equal\(op,"[^"]+"\)', known_ops_code) is None:
    raise SystemExit("known EASM operations must remain a closed exact-equality whitelist")
known = set(re.findall(r'easm_equal\(op,\s*"([^"]+)"\)', known_ops))
if not (read_modify_write | read_only | no_destination_write | {"movq", "fnstcw", "stmxcsr", "pop", "popq"}) <= known:
    raise SystemExit("effect-policy proof cases must remain inside the exact EASM opcode whitelist")

# Preserve the previous verifier semantics for every currently accepted opcode. If the
# operation inventory grows, this equivalence check requires an explicit policy review.
old_read_prefixes = ("add", "sub", "and", "or", "xor", "inc", "dec", "neg", "not", "sh", "sa", "cmp", "test", "xchg", "call", "jmp")
old_rmw_prefixes = ("add", "sub", "and", "or", "xor", "inc", "dec", "neg", "not", "sh", "sa", "xchg")
old_write_suppression_prefixes = ("fldcw", "ldmxcsr", "cmp", "test", "push", "call", "jmp")
old_read_suppression_prefixes = ("lea", "fnstcw", "stmxcsr")
observed_destination_reads = read_modify_write | read_only
expected_destination_reads = {op for op in known if op.startswith(old_read_prefixes)}
if observed_destination_reads != expected_destination_reads:
    raise SystemExit("proved destination-read classes no longer cover the old prefix policy on all known opcodes")
expected_read_modify_write = {op for op in known if op.startswith(old_rmw_prefixes)}
if read_modify_write != expected_read_modify_write:
    raise SystemExit("proved read-modify-write class no longer covers the old read/write prefixes on all known opcodes")
expected_destination_writes = {op for op in known if not op.startswith(old_write_suppression_prefixes)}
observed_destination_writes = known - no_destination_write
if observed_destination_writes != expected_destination_writes:
    raise SystemExit("proved destination-write class no longer matches the old verifier policy on all known opcodes")
expected_read_suppression = {op for op in known if op.startswith(old_read_suppression_prefixes)}
if expected_read_suppression != {"lea", "leaq", "fnstcw", "stmxcsr"}:
    raise SystemExit("EASM opcode inventory grew a read-suppression spelling that needs an explicit proof case")

positive_names = {
    "read_modify_write_opcodes_consume_and_update_the_old_memory_value",
    "compare_and_test_destinations_are_read_only",
    "indirect_control_destinations_are_read_only",
    "ordinary_store_destinations_do_not_read_the_old_value",
    "status_save_destinations_write_without_reading",
    "status_save_memory_effects_ignore_sources_and_follow_destination_shape",
    "control_state_loads_read_sources_without_writing_destinations",
    "control_state_loads_do_not_write_a_memory_destination",
    "pseudo_and_address_calculation_instructions_have_no_explicit_memory_effect",
    "source_memory_is_read_outside_the_explicit_suppression_cases",
    "pop_memory_destination_is_written_without_counting_its_implicit_stack_read",
    "destination_read_matches_the_opcode_effect",
    "no_explicit_memory_destination_cannot_be_written",
    "explicit_memory_destination_uses_the_opcode_write_policy",
}
negative_names = {
    "compare_is_a_memory_destination_write",
    "ordinary_move_reads_its_old_memory_destination",
    "indirect_call_writes_its_explicit_memory_destination",
    "pseudo_move_writes_its_memory_destination",
    "lea_reads_its_memory_source",
    "absent_memory_destination_is_written",
    "status_save_reads_an_explicit_memory_source",
    "control_state_load_writes_a_memory_destination",
    "pop_explicit_memory_destination_is_read",
}
for source, expected, label in (
    (POSITIVE, positive_names, "positive"),
    (NEGATIVE, negative_names, "negative"),
):
    actual = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", source.read_text()))
    if actual != expected:
        raise SystemExit(f"{label} proof declarations changed")
    for name in expected:
        declaration = next(line for line in source.read_text().splitlines() if line.startswith(f"def {name}(") )
        body = function_section(source.read_text(), name)
        if "bool can[Abort.Panic]:" not in declaration or "can Abort.Panic:" not in body:
            raise SystemExit(f"{label} proof must locally grant the classifier's Abort effect: {name}")

positive_text = POSITIVE.read_text()
expected_positive_bodies = {
    "read_modify_write_opcodes_consume_and_update_the_old_memory_value": (
        'requires ( op == "add" or op == "addq" or op == "sub" or op == "subq" or '
        'op == "and" or op == "andq" or op == "or" or op == "orq" or '
        'op == "xor" or op == "xorq" or op == "inc" or op == "incq" or '
        'op == "dec" or op == "decq" or op == "neg" or op == "negq" or '
        'op == "not" or op == "notq" or op == "shl" or op == "shlq" or '
        'op == "sal" or op == "salq" or op == "shr" or op == "shrq" or '
        'op == "sar" or op == "sarq" or op == "xchg" or op == "xchgl" or op == "xchgq" ) '
        "ensure result == true return EasmMemoryEffectPolicy::destination_reads_memory(op) and "
        "EasmMemoryEffectPolicy::destination_writes_memory(op)"
    ),
    "compare_and_test_destinations_are_read_only": (
        'requires op == "cmp" or op == "cmpq" or op == "test" or op == "testq" '
        "ensure result == true return EasmMemoryEffectPolicy::destination_reads_memory(op) and not "
        "EasmMemoryEffectPolicy::destination_writes_memory(op)"
    ),
    "indirect_control_destinations_are_read_only": (
        'requires op == "call" or op == "callq" or op == "jmp" or op == "jmpq" '
        "ensure result == true return EasmMemoryEffectPolicy::destination_reads_memory(op) and not "
        "EasmMemoryEffectPolicy::destination_writes_memory(op)"
    ),
    "ordinary_store_destinations_do_not_read_the_old_value": (
        "ensure result == true return not EasmMemoryEffectPolicy::destination_reads_memory(\"movq\") and "
        "EasmMemoryEffectPolicy::destination_writes_memory(\"movq\")"
    ),
    "status_save_destinations_write_without_reading": (
        "ensure result == true return ( not EasmMemoryEffectPolicy::destination_reads_memory(\"fnstcw\") and "
        "EasmMemoryEffectPolicy::destination_writes_memory(\"fnstcw\") and not "
        "EasmMemoryEffectPolicy::destination_reads_memory(\"stmxcsr\") and "
        "EasmMemoryEffectPolicy::destination_writes_memory(\"stmxcsr\") )"
    ),
    "status_save_memory_effects_ignore_sources_and_follow_destination_shape": (
        'requires op == "fnstcw" or op == "stmxcsr" ensure result == true return ( not '
        "EasmMemoryEffectPolicy::memory_reads(op, false, source_memory, destination_memory) and "
        "EasmMemoryEffectPolicy::memory_writes(op, false, destination_memory) == destination_memory )"
    ),
    "control_state_loads_read_sources_without_writing_destinations": (
        'requires op == "fldcw" or op == "ldmxcsr" ensure result == true return ( '
        "EasmMemoryEffectPolicy::memory_reads(op, false, source_memory, destination_memory) == source_memory and "
        "not EasmMemoryEffectPolicy::memory_writes(op, false, destination_memory) )"
    ),
    "control_state_loads_do_not_write_a_memory_destination": (
        "ensure result == true return ( not EasmMemoryEffectPolicy::destination_reads_memory(\"fldcw\") and "
        "not EasmMemoryEffectPolicy::destination_writes_memory(\"fldcw\") and not "
        "EasmMemoryEffectPolicy::destination_reads_memory(\"ldmxcsr\") and not "
        "EasmMemoryEffectPolicy::destination_writes_memory(\"ldmxcsr\") )"
    ),
    "pseudo_and_address_calculation_instructions_have_no_explicit_memory_effect": (
        'requires pseudo or op == "lea" or op == "leaq" ensure result == true return ( not '
        "EasmMemoryEffectPolicy::memory_reads(op, pseudo, source_memory, destination_memory) and not "
        "EasmMemoryEffectPolicy::memory_writes(op, pseudo, destination_memory) )"
    ),
    "source_memory_is_read_outside_the_explicit_suppression_cases": (
        'requires op != "lea" and op != "leaq" and op != "fnstcw" and op != "stmxcsr" and op != "pop" and op != "popq" '
        "ensure result == true return EasmMemoryEffectPolicy::memory_reads(op, false, source_memory, false) == source_memory"
    ),
    "pop_memory_destination_is_written_without_counting_its_implicit_stack_read": (
        'requires op == "pop" or op == "popq" ensure result == true return '
        "( not EasmMemoryEffectPolicy::memory_reads(op, false, true, true) and "
        "EasmMemoryEffectPolicy::memory_writes(op, false, true) )"
    ),
    "destination_read_matches_the_opcode_effect": (
        'requires op != "lea" and op != "leaq" and op != "fnstcw" and op != "stmxcsr" '
        "ensure result == true return EasmMemoryEffectPolicy::memory_reads(op, false, false, true) == "
        "EasmMemoryEffectPolicy::destination_reads_memory(op)"
    ),
    "no_explicit_memory_destination_cannot_be_written": (
        "ensure result == true return not EasmMemoryEffectPolicy::memory_writes(op, pseudo, false)"
    ),
    "explicit_memory_destination_uses_the_opcode_write_policy": (
        'requires op != "lea" and op != "leaq" ensure result == true return '
        "EasmMemoryEffectPolicy::memory_writes(op, false, true) == "
        "EasmMemoryEffectPolicy::destination_writes_memory(op)"
    ),
}
for name, expected in expected_positive_bodies.items():
    if proof_body(positive_text, name) != compact(expected):
        raise SystemExit(f"positive theorem no longer proves its reviewed policy claim: {name}")

negative_text = NEGATIVE.read_text()
expected_negative_bodies = {
    "compare_is_a_memory_destination_write": (
        "ensure result == true return EasmMemoryEffectPolicy::destination_writes_memory(\"cmp\")"
    ),
    "ordinary_move_reads_its_old_memory_destination": (
        "ensure result == true return EasmMemoryEffectPolicy::destination_reads_memory(\"movq\")"
    ),
    "indirect_call_writes_its_explicit_memory_destination": (
        "ensure result == true return EasmMemoryEffectPolicy::destination_writes_memory(\"call\")"
    ),
    "pseudo_move_writes_its_memory_destination": (
        "ensure result == true return EasmMemoryEffectPolicy::memory_writes(\"movq\", true, true)"
    ),
    "lea_reads_its_memory_source": (
        "ensure result == true return EasmMemoryEffectPolicy::memory_reads(\"lea\", false, true, false)"
    ),
    "absent_memory_destination_is_written": (
        "ensure result == true return EasmMemoryEffectPolicy::memory_writes(\"movq\", false, false)"
    ),
    "status_save_reads_an_explicit_memory_source": (
        "ensure result == true return EasmMemoryEffectPolicy::memory_reads(\"fnstcw\", false, true, false)"
    ),
    "control_state_load_writes_a_memory_destination": (
        "ensure result == true return EasmMemoryEffectPolicy::memory_writes(\"fldcw\", false, true)"
    ),
    "pop_explicit_memory_destination_is_read": (
        "ensure result == true return EasmMemoryEffectPolicy::memory_reads(\"pop\", false, true, true)"
    ),
}
for name, expected in expected_negative_bodies.items():
    if proof_body(negative_text, name) != compact(expected):
        raise SystemExit(f"negative false-claim control changed: {name}")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("EASM memory-effect proof requires a strict proof build")
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
    HELPER, ENV, MEMORY, PROVENANCE,
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
    "scope": "EASM explicit memory-destination reads, read-modify-write, and writes",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(negative_names),
    "proof_binary_sha256": hashlib.sha256(BIN.read_bytes()).hexdigest(),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
