"""Admit the source-linked EASM raw memory-base classification proofs."""
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
POLICY = ROOT / "src/backend/easm_memory_base_policy.elisa"
SCAN = ROOT / "src/backend/easm_text_scan.elisa"
ENV = ROOT / "src/backend/codegen_env.elisa"
MEMORY = ROOT / "src/backend/easm_verify_memory.elisa"
PROVENANCE = ROOT / "src/backend/easm_verify_provenance.elisa"
FUNCTION = ROOT / "src/backend/easm_verify_function.elisa"
POSITIVE = HERE / "easm_memory_base_policy.elisa"
NEGATIVE = HERE / "easm_memory_base_policy_rejected.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(source: str) -> str:
    return "".join(" ".join(line.split("#", 1)[0].split()) for line in source.splitlines())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)(?:ghost[ \t]+)?def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}(?:ghost[ \t]+)?def [A-Za-z_][A-Za-z0-9_]*\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def declaration_names(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^[ \t]*def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


def proof_body(source: str, name: str) -> str:
    match = re.search(rf"(?ms)^def {re.escape(name)}\([^\n]*\)[^\n]*:\n(.*?)(?=^def |\Z)", source)
    if match is None:
        raise SystemExit(f"could not locate proof declaration {name}")
    return compact(match.group(1))


policy = POLICY.read_text()
policy_compact = compact(policy)
expected_raw_scalar = {
    "raw_scalar_type",
    "raw_address_type",
    "special_memory_base",
    "rejects_direct_raw_base",
    "rejects_untraced_raw_base",
    "rejects_raw_address_type_without_opt_in",
    "rejects_bracket_address_form",
    "rejects_unresolved_memory_base",
}
if declaration_names(POLICY) != expected_raw_scalar:
    raise SystemExit("memory-base policy declaration inventory changed")
raw_scalar = compact(function_section(policy, "raw_scalar_type"))
scalar_types = ("u8", "u16", "u32", "u64", "i8", "i16", "i32", "i64", "usize", "uintptr")
for type_name in scalar_types:
    if f'"{type_name}"' not in raw_scalar:
        raise SystemExit(f"raw scalar classifier lost {type_name}")
if "return when type_name:" not in raw_scalar:
    raise SystemExit("raw scalar classifier must remain an exact closed match")
if "ensure result == (" not in raw_scalar:
    raise SystemExit("raw scalar classifier no longer states its exact postcondition")
expected_policy_bodies = {
    "raw_scalar_type": """
        def raw_scalar_type(type_name: sview) -> bool:
            ensure result == (
                type_name == "u8" or type_name == "u16" or type_name == "u32" or type_name == "u64" or
                type_name == "i8" or type_name == "i16" or type_name == "i32" or type_name == "i64" or
                type_name == "usize" or type_name == "uintptr"
            )
            can Abort.Panic:
                return when type_name:
                    "u8" | "u16" | "u32" | "u64" -> true
                    "i8" | "i16" | "i32" | "i64" -> true
                    "usize" | "uintptr" -> true
                    _ -> false
    """,
    "raw_address_type": """
        def raw_address_type(type_name: sview) -> bool:
            ensure result == (
                type_name == "u8" or type_name == "u16" or type_name == "u32" or type_name == "u64" or
                type_name == "i8" or type_name == "i16" or type_name == "i32" or type_name == "i64" or
                type_name == "usize" or type_name == "uintptr"
            )
            can Abort.Panic:
                return when type_name:
                    "u8" | "u16" | "u32" | "u64" -> true
                    "i8" | "i16" | "i32" | "i64" -> true
                    "usize" | "uintptr" -> true
                    _ -> false
    """,
    "special_memory_base": """
        def special_memory_base(register: sview) -> bool:
            ensure result == (register == "" or register == "rsp" or register == "rip")
            can Abort.Panic:
                return when register:
                    "" | "rsp" | "rip" -> true
                    _ -> false
    """,
    "rejects_direct_raw_base": """
        def rejects_direct_raw_base(register: sview, type_name: sview, untyped_capability: bool) -> bool:
            ensure result == (
                register != "" and register != "rsp" and register != "rip" and
                (type_name == "u8" or type_name == "u16" or type_name == "u32" or type_name == "u64" or
                    type_name == "i8" or type_name == "i16" or type_name == "i32" or type_name == "i64" or
                    type_name == "usize" or type_name == "uintptr") and not untyped_capability
            )
            can Abort.Panic:
                return not special_memory_base(register) and raw_scalar_type(type_name) and not untyped_capability
    """,
    "rejects_untraced_raw_base": """
        def rejects_untraced_raw_base(provenance_established: bool, untyped_capability: bool) -> bool:
            ensure result == (not provenance_established and not untyped_capability)
            return not provenance_established and not untyped_capability
    """,
    "rejects_raw_address_type_without_opt_in": """
        def rejects_raw_address_type_without_opt_in(type_name: sview, untyped_capability: bool) -> bool:
            ensure result == (
                (type_name == "u8" or type_name == "u16" or type_name == "u32" or type_name == "u64" or
                    type_name == "i8" or type_name == "i16" or type_name == "i32" or type_name == "i64" or
                    type_name == "usize" or type_name == "uintptr") and not untyped_capability
            )
            can Abort.Panic:
                return raw_address_type(type_name) and not untyped_capability
    """,
    "rejects_bracket_address_form": """
        def rejects_bracket_address_form(has_square_bracket: bool) -> bool:
            ensure result == has_square_bracket
            return has_square_bracket
    """,
    "rejects_unresolved_memory_base": """
        def rejects_unresolved_memory_base(is_memory_operand: bool, base_unparsed: bool) -> bool:
            ensure result == (is_memory_operand and base_unparsed)
            return is_memory_operand and base_unparsed
    """,
}
for name, expected in expected_policy_bodies.items():
    if compact(function_section(policy, name)) != compact(expected):
        raise SystemExit(f"production memory-base policy contract changed: {name}")
for required in (
    '"" | "rsp" | "rip" -> true',
    'ensure result == (not provenance_established and not untyped_capability)',
):
    if required not in policy_compact:
        raise SystemExit(f"memory-base policy contract is missing: {required}")
if '"uintptr"' not in function_section(policy, "raw_address_type"):
    raise SystemExit("pointer-sized integer is no longer explicitly included in the raw address class")

environment = ENV.read_text()
include = 'include "easm_memory_base_policy.elisa"'
if include not in environment or environment.index(include) > environment.index('include "easm_verify_memory.elisa"'):
    raise SystemExit("backend environment must import the policy before its memory verifier")

memory = MEMORY.read_text()
legacy_scalar = compact(function_section(memory, "easm_raw_scalar_type"))
if legacy_scalar != compact("""
def easm_raw_scalar_type(type_name: sview) -> bool:
    return easm_equal(type_name, "u8") or easm_equal(type_name, "u16") or easm_equal(type_name, "u32") or easm_equal(type_name, "u64") or easm_equal(type_name, "i8") or easm_equal(type_name, "i16") or easm_equal(type_name, "i32") or easm_equal(type_name, "i64") or easm_equal(type_name, "usize") or easm_equal(type_name, "uintptr")
"""):
    raise SystemExit("legacy scalar classification changed; compare it with the proved closed type set")
roles = function_section(memory, "easm_verify_memory_roles")
roles_compact = compact(roles)
direct_call = 'EasmMemoryBasePolicy::rejects_direct_raw_base(base, carried_type, easm_contract_has_word(fn.requires, "memory.base.untyped"))'
untraced_call = 'EasmMemoryBasePolicy::rejects_untraced_raw_base(type_name != "", easm_contract_has_word(fn.requires, "memory.base.untyped"))'
typed_call = 'EasmMemoryBasePolicy::rejects_raw_address_type_without_opt_in(type_name, easm_contract_has_word(fn.requires, "memory.base.untyped"))'


def diagnostic_gate(call: str) -> bool:
    escaped = re.escape(call)
    return re.search(
        rf'(?m)^[ \t]*if {escaped}:\n[ \t]+issues\.push\(Issue\{{severity: Severity\.Error, code: "raw-memory-base"',
        roles,
    ) is not None


if roles.count(direct_call) != 1 or not diagnostic_gate(direct_call):
    raise SystemExit("direct raw-scalar policy must be the live condition that emits raw-memory-base")
if roles.count(untraced_call) != 1 or not diagnostic_gate(untraced_call):
    raise SystemExit("untraced-base policy must be the live condition that emits raw-memory-base")
if roles.count(typed_call) != 1 or not diagnostic_gate(typed_call):
    raise SystemExit("typed raw-address policy must be the live condition that emits raw-memory-base")
if roles_compact.count('code: "raw-memory-base"') != 3:
    raise SystemExit("raw-memory-base diagnostic sites changed; review the policy-to-verifier binding")

base_parser = compact(function_section(memory, "easm_memory_base_register"))
if 'open: usize = easm_find(operand, "(")' not in base_parser or \
        'if open >= sview_len(operand):return ""' not in base_parser or \
        'close_relative: usize = easm_find(operand[open:sview_len(operand)], ")")' not in base_parser or \
        'if close_relative >= sview_len(operand[open:sview_len(operand)]):return ""' not in base_parser:
    raise SystemExit("EASM base parser must fail closed when either address delimiter is missing")
memory_operand = compact(function_section(PROVENANCE.read_text(), "easm_memory_operand"))
if "EasmTextScan::contains_memory_address_delimiter" not in memory_operand or \
        'easm_find(operand, "[") < sview_len(operand)' not in memory_operand:
    raise SystemExit("bracketed operands are no longer source-classified as memory by the verifier")

bracket_gate = re.search(
    r'(?m)^[ \t]*bracketed: bool = easm_find\(operand, "\["\) < sview_len\(operand\)\n'
    r'(?P<indent>[ \t]*)if EasmMemoryBasePolicy::rejects_bracket_address_form\(bracketed\):\n'
    r'(?P=indent)[ \t]+issues\.push\(Issue\{severity: Severity\.Error, code: "unsupported-bracket-address"[^\n]*\}\)\n'
    r'(?P=indent)[ \t]+continue', roles)
if bracket_gate is None:
    raise SystemExit("bracket syntax must emit a fail-closed diagnostic before base parsing")
base_lookup = roles.find("base: sview = easm_memory_base_register(operand)")
if base_lookup < bracket_gate.start():
    raise SystemExit("bracket syntax must be rejected before an empty base can be treated as safe")
unresolved_gate = re.search(
    r'(?m)^[ \t]*if base == "" and EasmMemoryBasePolicy::rejects_unresolved_memory_base\(true, true\):\n'
    r'[ \t]+issues\.push\(Issue\{severity: Severity\.Error, code: "unresolved-memory-base"', roles)
if unresolved_gate is None:
    raise SystemExit("unparsed non-bracket memory bases must fail closed with an issue")
validation_start = roles.find("for instruction in fn.instructions:")
validation_end = roles.find("for input in fn.inputs:", validation_start)
if validation_start < 0 or validation_end < 0:
    raise SystemExit("all-instruction address validation pass was removed")
validation = roles[validation_start:validation_end]
if "continue if instruction.pseudo" not in validation or \
        "for operand_index in 0..<EasmMemoryBasePolicy::MEMORY_ADDRESS_OPERAND_COUNT" not in validation or \
        "easm_memory_operand(operand)" not in validation or \
        'easm_starts(instruction.op, "lea")' in validation:
    raise SystemExit("address fail-closed checks must visit both operands of every non-pseudo opcode, including LEA")
if not (bracket_gate.start() < base_lookup < unresolved_gate.start()):
    raise SystemExit("bracket and unresolved-base guards must run before later provenance analysis")

direct_pass_start = roles.find("for instruction_index in 0..<fn.instructions.count")
direct_pass_end = roles.find("issues.reserve(issues.count + fn.instructions.count)", direct_pass_start)
if direct_pass_start < 0 or direct_pass_end < 0:
    raise SystemExit("the independent raw-carrier verification pass was removed")
direct_pass = roles[direct_pass_start:direct_pass_end]
if not (
    direct_pass.index("continue if instruction.pseudo or easm_starts(instruction.op, \"lea\")")
    < direct_pass.index("for operand_index in 0..<EasmMemoryBasePolicy::MEMORY_ADDRESS_OPERAND_COUNT")
    < direct_pass.index("continue if not easm_memory_operand(operand)")
    < direct_pass.index(direct_call)
    < direct_pass.index('code: "raw-memory-base"')
):
    raise SystemExit("direct raw-base check no longer visits substituted memory operands in the live non-lea pass")
if "operand: sview = easm_substitute_operand(raw_operand, instruction)" not in direct_pass:
    raise SystemExit("direct raw-base check must inspect fragment-substituted operands")

untraced_start = roles.find("if type_name == \"\":")
untraced_end = roles.find("layout_name: sview = easm_carrier_layout(type_name)", untraced_start)
if untraced_start < 0 or untraced_end < 0:
    raise SystemExit("untraced-base check must run before layout resolution")
untraced_pass = roles[untraced_start:untraced_end]
if "easm_has_raw_scalar_input" in untraced_pass or untraced_call not in untraced_pass or \
        "type_name != \"\"" not in untraced_pass:
    raise SystemExit("every untraced memory base must require explicit untyped-memory capability")

post = compact(function_section(FUNCTION.read_text(), "verify_function_post"))
one = compact(function_section(FUNCTION.read_text(), "verify_one_function"))
module_functions = compact(function_section(FUNCTION.read_text(), "verify_module_functions"))
module = compact(function_section(FUNCTION.read_text(), "verify_module"))
for source, call in (
    (post, "easm_verify_memory_roles(fn, module.layouts, issues)"),
    (one, "verify_function_post(module, fn, stack_delta, stack_touched, stack_known, uses_call, writes_segment_any, issues)"),
    (module_functions, "verify_one_function(module, outer_index, fn, issues)"),
    (module, "verify_module_functions(module, issues)"),
):
    if call not in source:
        raise SystemExit(f"proved memory-role diagnostic path is not connected through the module verifier: {call}")

if 'include "../../src/backend/easm_memory_base_policy.elisa"' not in POSITIVE.read_text():
    raise SystemExit("positive proof no longer includes the production policy")
if 'include "../../src/backend/easm_text_scan.elisa"' not in POSITIVE.read_text():
    raise SystemExit("bracket-address theorem no longer includes the production delimiter scanner")
if 'include "./easm_memory_base_policy.elisa"' not in NEGATIVE.read_text():
    raise SystemExit("negative controls no longer include the positive production proof")

positive_names = {
    "raw_scalar_classification_matches_the_closed_type_set",
    "raw_address_classification_includes_pointer_sized_unsigned_values",
    "stack_instruction_pointer_and_absent_bases_are_special",
    "raw_scalar_carriers_are_rejected_as_ordinary_memory_bases",
    "explicit_untyped_memory_capability_is_the_only_direct_base_escape",
    "untraced_base_rejection_matches_provenance_and_opt_in",
    "raw_address_carriers_need_the_explicit_untyped_capability",
    "typed_non_address_carriers_are_not_rejected_as_raw_address_types",
    "bracketed_memory_address_is_detected_as_memory_syntax",
    "bracketed_raw_address_is_rejected_by_the_bracket_gate",
    "unresolved_non_bracket_memory_base_is_rejected",
    "unresolved_base_gate_matches_the_memory_and_parse_facts",
}
negative_names = {
    "raw_integer_base_is_accepted_without_capability",
    "stack_base_is_rejected_by_the_direct_raw_carrier_gate",
    "pointer_sized_integer_is_treated_as_a_typed_pointer_without_opt_in",
    "raw_integer_base_is_rejected_even_with_explicit_capability",
    "bracketed_raw_address_is_accepted_as_a_supported_base",
    "unresolved_non_bracket_memory_base_is_accepted",
    "immediate_created_untraced_base_is_allowed_without_capability",
}
for path, expected, label in ((POSITIVE, positive_names, "positive"), (NEGATIVE, negative_names, "negative")):
    if declaration_names(path) != expected:
        raise SystemExit(f"{label} proof inventory changed")

positive_text = POSITIVE.read_text()
expected_positive_bodies = {
    "raw_scalar_classification_matches_the_closed_type_set": """
        ensure result == true
        can Abort.Panic:
            return EasmMemoryBasePolicy::raw_scalar_type(type_name) == (
                type_name == "u8" or type_name == "u16" or type_name == "u32" or type_name == "u64" or
                type_name == "i8" or type_name == "i16" or type_name == "i32" or type_name == "i64" or
                type_name == "usize" or type_name == "uintptr"
            )
    """,
    "raw_address_classification_includes_pointer_sized_unsigned_values": """
        ensure result == true
        can Abort.Panic:
            return EasmMemoryBasePolicy::raw_address_type(type_name) == (
                type_name == "u8" or type_name == "u16" or type_name == "u32" or type_name == "u64" or
                type_name == "i8" or type_name == "i16" or type_name == "i32" or type_name == "i64" or
                type_name == "usize" or type_name == "uintptr"
            )
    """,
    "stack_instruction_pointer_and_absent_bases_are_special": """
        ensure result == true
        can Abort.Panic:
            return EasmMemoryBasePolicy::special_memory_base(register) == (
                register == "" or register == "rsp" or register == "rip"
            )
    """,
    "raw_scalar_carriers_are_rejected_as_ordinary_memory_bases": """
        requires register != "" and register != "rsp" and register != "rip" and (
            type_name == "u8" or type_name == "u16" or type_name == "u32" or type_name == "u64" or
            type_name == "i8" or type_name == "i16" or type_name == "i32" or type_name == "i64" or
            type_name == "usize" or type_name == "uintptr"
        )
        ensure result == true
        can Abort.Panic:
            return EasmMemoryBasePolicy::rejects_direct_raw_base(register, type_name, false)
    """,
    "explicit_untyped_memory_capability_is_the_only_direct_base_escape": """
        requires register != "" and register != "rsp" and register != "rip" and (
            type_name == "u8" or type_name == "u16" or type_name == "u32" or type_name == "u64" or
            type_name == "i8" or type_name == "i16" or type_name == "i32" or type_name == "i64" or
            type_name == "usize" or type_name == "uintptr"
        )
        ensure result == true
        can Abort.Panic:
            return EasmMemoryBasePolicy::rejects_direct_raw_base(register, type_name, untyped_capability) == not untyped_capability
    """,
    "untraced_base_rejection_matches_provenance_and_opt_in": """
        requires not provenance_established
        ensure result == true
        return EasmMemoryBasePolicy::rejects_untraced_raw_base(provenance_established, untyped_capability) == not untyped_capability
    """,
    "raw_address_carriers_need_the_explicit_untyped_capability": """
        requires (
            type_name == "u8" or type_name == "u16" or type_name == "u32" or type_name == "u64" or
            type_name == "i8" or type_name == "i16" or type_name == "i32" or type_name == "i64" or
            type_name == "usize" or type_name == "uintptr"
        )
        ensure result == true
        can Abort.Panic:
            return EasmMemoryBasePolicy::rejects_raw_address_type_without_opt_in(type_name, untyped_capability) == not untyped_capability
    """,
    "typed_non_address_carriers_are_not_rejected_as_raw_address_types": """
        requires (
            type_name != "u8" and type_name != "u16" and type_name != "u32" and type_name != "u64" and
            type_name != "i8" and type_name != "i16" and type_name != "i32" and type_name != "i64" and
            type_name != "usize" and type_name != "uintptr"
        )
        ensure result == true
        can Abort.Panic:
            return not EasmMemoryBasePolicy::rejects_raw_address_type_without_opt_in(type_name, false)
    """,
    "bracketed_memory_address_is_detected_as_memory_syntax": """
        ensure result == true
        can Abort.Panic:
            has_bracket: bool = EasmTextScan::find("[rax+8]", "[") == 0
            return has_bracket and EasmTextScan::contains_memory_address_delimiter(false, has_bracket)
    """,
    "bracketed_raw_address_is_rejected_by_the_bracket_gate": """
        ensure result == true
        can Abort.Panic:
            has_bracket: bool = EasmTextScan::find("[rax+8]", "[") == 0
            return (
                has_bracket and EasmTextScan::contains_memory_address_delimiter(false, has_bracket) and
                EasmMemoryBasePolicy::rejects_bracket_address_form(has_bracket)
            )
    """,
    "unresolved_non_bracket_memory_base_is_rejected": """
        ensure result == true
        return EasmMemoryBasePolicy::rejects_unresolved_memory_base(true, true)
    """,
    "unresolved_base_gate_matches_the_memory_and_parse_facts": """
        ensure result == true
        return EasmMemoryBasePolicy::rejects_unresolved_memory_base(is_memory_operand, base_unparsed) == (is_memory_operand and base_unparsed)
    """,
}
for name, expected in expected_positive_bodies.items():
    if proof_body(positive_text, name) != compact(expected):
        raise SystemExit(f"positive theorem no longer states its reviewed claim: {name}")

negative_text = NEGATIVE.read_text()
expected_negative_bodies = {
    "raw_integer_base_is_accepted_without_capability": """
        ensure result == true
        can Abort.Panic:
            return not EasmMemoryBasePolicy::rejects_direct_raw_base("rax", "i64", false)
    """,
    "stack_base_is_rejected_by_the_direct_raw_carrier_gate": """
        ensure result == true
        can Abort.Panic:
            return EasmMemoryBasePolicy::rejects_direct_raw_base("rsp", "i64", false)
    """,
    "pointer_sized_integer_is_treated_as_a_typed_pointer_without_opt_in": """
        ensure result == true
        can Abort.Panic:
            return not EasmMemoryBasePolicy::rejects_raw_address_type_without_opt_in("uintptr", false)
    """,
    "raw_integer_base_is_rejected_even_with_explicit_capability": """
        ensure result == true
        can Abort.Panic:
            return EasmMemoryBasePolicy::rejects_direct_raw_base("rax", "i64", true)
    """,
    "bracketed_raw_address_is_accepted_as_a_supported_base": """
        ensure result == true
        can Abort.Panic:
            has_bracket: bool = EasmTextScan::find("[rax+8]", "[") == 0
            return not EasmMemoryBasePolicy::rejects_bracket_address_form(has_bracket)
    """,
    "unresolved_non_bracket_memory_base_is_accepted": """
        ensure result == true
        return not EasmMemoryBasePolicy::rejects_unresolved_memory_base(true, true)
    """,
    "immediate_created_untraced_base_is_allowed_without_capability": """
        ensure result == true
        return not EasmMemoryBasePolicy::rejects_untraced_raw_base(false, false)
    """,
}
for name, expected in expected_negative_bodies.items():
    if proof_body(negative_text, name) != compact(expected):
        raise SystemExit(f"negative false-claim control changed: {name}")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("EASM memory-base proof requires a strict proof build")
compiler_head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], check=True,
                               capture_output=True, text=True).stdout.strip()
if compiler_head != manifest["compiler"]["source_revision"]:
    raise SystemExit("proof product was built from a different compiler revision")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
          PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
          Path(__file__), HERE / "proof_product_gate.py", POSITIVE, NEGATIVE,
          POLICY, SCAN, ENV, MEMORY, PROVENANCE, FUNCTION]
inputs.extend(source_include_closure([POSITIVE, NEGATIVE]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def replay(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True, text=True, timeout=60)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


code, positive = replay(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
assert not positive["findings"]
assert positive == replay(POSITIVE)[1], "proof report changed across repeated runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert positive_names <= verified

code, negative = replay(NEGATIVE)
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
    "scope": "EASM raw scalar, untraced, and pointer-sized memory-base rejection",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(negative_names),
    "proof_binary_sha256": hashlib.sha256(BIN.read_bytes()).hexdigest(),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
