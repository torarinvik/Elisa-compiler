"""Admit the CoreIR scalar arithmetic guard against both production backends."""
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
HELPER = ROOT / "src/ir/core_ir_scalar_safety.elisa"
CORE_IR = ROOT / "src/ir/core_ir.elisa"
NATIVE_CALLER = ROOT / "src/backend/codegen_declare.elisa"
NATIVE_EMITTER = ROOT / "src/backend/codegen_core_ir.elisa"
EDIR = ROOT / "src/driver/emit_edir.elisa"
POSITIVE = HERE / "core_ir_scalar_safety.elisa"
NEGATIVE = HERE / "core_ir_scalar_safety_rejected.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    return "".join(text.split())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"^[ \t]*def {re.escape(name)}\(", source, re.MULTILINE))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    start = matches[0].start()
    following = re.search(r"^[ \t]*def [A-Za-z_][A-Za-z0-9_]*\(", source[matches[0].end():], re.MULTILINE)
    end = matches[0].end() + following.start() if following else len(source)
    return source[start:end]


def require_ordered(body: str, fragments: tuple[str, ...], label: str) -> None:
    compact_body = compact(body)
    positions = [compact_body.find(compact(fragment)) for fragment in fragments]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        raise SystemExit(f"{label} no longer follows the checked scalar preflight path")


helper_text = HELPER.read_text()
binary_safety = compact(function_section(helper_text, "binary_is_defined"))
expected_binary_safety = compact("""def binary_is_defined(operator: i64, left: i64, right: i64) -> bool:
            ensure left < 0 or right < 0 implies not result
            ensure operator == ElisaCoreIRArithmetic::ADD_GUARD_CODE and left >= 0 and right >= 0 implies result == (left <= ElisaCoreIRArithmetic::SIGNED_I64_MAXIMUM - right)
            ensure operator == ElisaCoreIRArithmetic::SUBTRACT_GUARD_CODE and left >= 0 and right >= 0 implies result == true
            ensure operator == ElisaCoreIRArithmetic::MULTIPLY_GUARD_CODE and left >= 0 and right >= 0 implies result == (right == 0 or left <= (ElisaCoreIRArithmetic::SIGNED_I64_MAXIMUM / right if right > 0 else ElisaCoreIRArithmetic::SIGNED_I64_MAXIMUM))
            ensure operator == ElisaCoreIRArithmetic::DIVIDE_GUARD_CODE and left >= 0 and right >= 0 implies result == (right != 0)
            ensure operator != ElisaCoreIRArithmetic::ADD_GUARD_CODE and operator != ElisaCoreIRArithmetic::SUBTRACT_GUARD_CODE and operator != ElisaCoreIRArithmetic::MULTIPLY_GUARD_CODE and operator != ElisaCoreIRArithmetic::DIVIDE_GUARD_CODE implies not result
            return false if left < 0 or right < 0
            if operator == ElisaCoreIRArithmetic::ADD_GUARD_CODE:
                return left <= ElisaCoreIRArithmetic::SIGNED_I64_MAXIMUM - right
            if operator == ElisaCoreIRArithmetic::SUBTRACT_GUARD_CODE:
                return true
            if operator == ElisaCoreIRArithmetic::MULTIPLY_GUARD_CODE:
                return true if right == ElisaCoreIRArithmetic::ZERO
                return left <= ElisaCoreIRArithmetic::SIGNED_I64_MAXIMUM / right
            if operator == ElisaCoreIRArithmetic::DIVIDE_GUARD_CODE:
                return right != ElisaCoreIRArithmetic::ZERO
            return false""")
if binary_safety != expected_binary_safety:
    raise SystemExit("CoreIR scalar arithmetic helper no longer matches its proved signed-i64 guard")

core_text = CORE_IR.read_text()
if 'include "./core_ir_scalar_safety.elisa"' not in core_text:
    raise SystemExit("CoreIR no longer imports the proved scalar arithmetic helper")
wrapper = compact(function_section(core_text, "scalar_i64_binary_is_defined"))
expected_wrapper = compact("""def scalar_i64_binary_is_defined(operator: I64BinaryOperator, left: i64, right: i64) -> bool:
            ensure left < 0 or right < 0 implies not result
            ensure operator == I64BinaryOperator.Add and left >= 0 and right >= 0 implies result == (left <= ElisaCoreIRArithmetic::SIGNED_I64_MAXIMUM - right)
            ensure operator == I64BinaryOperator.Subtract and left >= 0 and right >= 0 implies result == true
            ensure operator == I64BinaryOperator.Multiply and left >= 0 and right >= 0 implies result == (right == 0 or left <= (ElisaCoreIRArithmetic::SIGNED_I64_MAXIMUM / right if right > 0 else ElisaCoreIRArithmetic::SIGNED_I64_MAXIMUM))
            ensure operator == I64BinaryOperator.Divide and left >= 0 and right >= 0 implies result == (right != 0)
            return ElisaCoreIRScalarSafety::binary_is_defined(ElisaCoreIRArithmetic::ADD_GUARD_CODE, left, right) if operator == I64BinaryOperator.Add
            return ElisaCoreIRScalarSafety::binary_is_defined(ElisaCoreIRArithmetic::SUBTRACT_GUARD_CODE, left, right) if operator == I64BinaryOperator.Subtract
            return ElisaCoreIRScalarSafety::binary_is_defined(ElisaCoreIRArithmetic::MULTIPLY_GUARD_CODE, left, right) if operator == I64BinaryOperator.Multiply
            return ElisaCoreIRScalarSafety::binary_is_defined(ElisaCoreIRArithmetic::DIVIDE_GUARD_CODE, left, right) if operator == I64BinaryOperator.Divide
            return false""")
if wrapper != expected_wrapper:
    raise SystemExit("CoreIR enum-to-arithmetic guard mapping changed")
program_guard = compact(function_section(core_text, "scalar_expression_is_defined"))
expected_program_guard = compact("""def scalar_expression_is_defined(program: Program) -> bool:
            ensure result == (scalar_i64_binary_is_defined(program.operator, program.left, program.right) if program.has_binary_operator else true)
            return true if not program.has_binary_operator
            return scalar_i64_binary_is_defined(program.operator, program.left, program.right)""")
if program_guard != expected_program_guard:
    raise SystemExit("CoreIR program preflight no longer forwards its arithmetic fields exactly")

native_body = function_section(NATIVE_CALLER.read_text(), "emit_function_body_bound")
require_ordered(native_body, (
    "if not runtime.debug_active and not runtime.trace_enabled and old_snapshot_calls.count == 0",
    "if ElisaCoreIR::lower_function(declaration, owner) is core_program",
    "if ElisaCoreIR::scalar_expression_is_defined(core_program)",
    "emit_core_i64_program(core_program, fn, ctx, builder) return true",
), "native scalar emission")

native_emit = compact(function_section(NATIVE_EMITTER.read_text(), "emit_core_i64_program"))
native_ops = (
    "ElisaCoreIR::I64BinaryOperator.Add: LLVMBuildAdd(builder, left_value, right_value, \"core.add\")",
    "ElisaCoreIR::I64BinaryOperator.Subtract: LLVMBuildSub(builder, left_value, right_value, \"core.subtract\")",
    "ElisaCoreIR::I64BinaryOperator.Multiply: LLVMBuildMul(builder, left_value, right_value, \"core.multiply\")",
    "ElisaCoreIR::I64BinaryOperator.Divide: LLVMBuildSDiv(builder, left_value, right_value, \"core.divide\")",
)
native_positions = [native_emit.find(compact(fragment)) for fragment in native_ops]
if any(position < 0 for position in native_positions) or native_positions != sorted(native_positions):
    raise SystemExit("native CoreIR operations no longer match the checked arithmetic operators")

edir_text = EDIR.read_text()
opcode_map = compact(function_section(edir_text, "core_ir_opcode"))
edir_ops = (
    "return ElisaEDIR::Instruction::ADD_OPCODE if operator == ElisaCoreIR::I64BinaryOperator.Add",
    "return ElisaEDIR::Instruction::SUBTRACT_OPCODE if operator == ElisaCoreIR::I64BinaryOperator.Subtract",
    "return ElisaEDIR::Instruction::MULTIPLY_OPCODE if operator == ElisaCoreIR::I64BinaryOperator.Multiply",
    "return ElisaEDIR::Instruction::DIVIDE_OPCODE",
)
opcode_positions = [opcode_map.find(compact(fragment)) for fragment in edir_ops]
if any(position < 0 for position in opcode_positions) or opcode_positions != sorted(opcode_positions):
    raise SystemExit("EDIR scalar opcodes no longer match the checked arithmetic operators")
artifact_builder = compact(function_section(edir_text, "core_ir_artifact"))
guard = 'return unsupported("arithmetic may overflow or divide by zero in the managed engine") if not ElisaCoreIR::scalar_expression_is_defined(program)'
if artifact_builder.count(compact(guard)) != 2:
    raise SystemExit("EDIR must guard both local and nonlocal binary scalar emission")
guard_positions = [match.start() for match in re.finditer(re.escape(compact(guard)), artifact_builder)]
opcode_append = compact("append_instruction(&artifact, core_ir_opcode(program.operator)")
opcode_positions = [match.start() for match in re.finditer(re.escape(opcode_append), artifact_builder)]
if len(opcode_positions) != 2 or any(guard_pos > opcode_pos for guard_pos, opcode_pos in zip(guard_positions, opcode_positions)):
    raise SystemExit("an EDIR binary scalar path emits an opcode before checking arithmetic safety")

positive_names = {
    "negative_scalar_operand_is_rejected",
    "unknown_scalar_operator_is_rejected",
    "scalar_safety_constants_match_the_i64_domain",
    "nonnegative_addition_guard_is_exact",
    "nonnegative_subtraction_is_always_defined",
    "nonnegative_multiplication_guard_is_exact",
    "nonnegative_division_guard_is_exact",
    "maximum_plus_zero_is_admitted",
    "maximum_plus_one_is_rejected",
    "zero_minus_maximum_is_admitted",
    "maximum_times_one_is_admitted",
    "zero_times_maximum_is_admitted",
    "maximum_times_two_is_rejected",
    "positive_divisor_is_admitted",
    "zero_divisor_is_rejected",
    "guarded_addition_has_an_exact_i64_result",
    "guarded_subtraction_has_an_exact_i64_result",
    "guarded_zero_multiplication_has_an_exact_i64_result",
    "guarded_positive_multiplication_has_an_exact_i64_result",
    "guarded_division_has_an_exact_i64_result",
    "accepted_addition_result_is_bounded",
    "accepted_subtraction_result_is_bounded",
    "accepted_multiplication_result_is_bounded",
    "accepted_division_result_is_bounded",
}
negative_names = {
    "maximum_plus_one_is_admitted",
    "maximum_times_two_is_admitted",
    "zero_divisor_is_admitted",
    "negative_scalar_operand_is_admitted",
}


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


for path, expected in ((POSITIVE, positive_names), (NEGATIVE, negative_names)):
    if declarations(path) != expected:
        raise SystemExit(f"{path.name} proof declaration inventory changed")
    if 'include "../../src/ir/core_ir_scalar_safety.elisa"' not in path.read_text():
        raise SystemExit(f"{path.name} no longer proves the production scalar safety helper")

positive_shapes = {
    "negative_scalar_operand_is_rejected": "requires left < 0 or right < 0 ensure result == true return not ElisaCoreIRScalarSafety::binary_is_defined(operator, left, right)",
    "unknown_scalar_operator_is_rejected": "requires operator != ElisaCoreIRArithmetic::ADD_GUARD_CODE requires operator != ElisaCoreIRArithmetic::SUBTRACT_GUARD_CODE requires operator != ElisaCoreIRArithmetic::MULTIPLY_GUARD_CODE requires operator != ElisaCoreIRArithmetic::DIVIDE_GUARD_CODE ensure result == true return not ElisaCoreIRScalarSafety::binary_is_defined(operator, left, right)",
    "scalar_safety_constants_match_the_i64_domain": "ensure result == true return ElisaCoreIRArithmetic::ZERO == 0 and ElisaCoreIRArithmetic::SIGNED_I64_MAXIMUM == 9223372036854775807 and ElisaCoreIRArithmetic::ADD_GUARD_CODE == 0 and ElisaCoreIRArithmetic::SUBTRACT_GUARD_CODE == 1 and ElisaCoreIRArithmetic::MULTIPLY_GUARD_CODE == 2 and ElisaCoreIRArithmetic::DIVIDE_GUARD_CODE == 3",
    "nonnegative_addition_guard_is_exact": "requires left >= 0 and right >= 0 ensure result == (left <= ElisaCoreIRArithmetic::SIGNED_I64_MAXIMUM - right) return ElisaCoreIRScalarSafety::binary_is_defined(ElisaCoreIRArithmetic::ADD_GUARD_CODE, left, right)",
    "nonnegative_subtraction_is_always_defined": "requires left >= 0 and right >= 0 ensure result == true return ElisaCoreIRScalarSafety::binary_is_defined(ElisaCoreIRArithmetic::SUBTRACT_GUARD_CODE, left, right)",
    "nonnegative_multiplication_guard_is_exact": "requires left >= 0 and right >= 0 ensure result == (right == 0 or left <= (ElisaCoreIRArithmetic::SIGNED_I64_MAXIMUM / right if right > 0 else ElisaCoreIRArithmetic::SIGNED_I64_MAXIMUM)) return ElisaCoreIRScalarSafety::binary_is_defined(ElisaCoreIRArithmetic::MULTIPLY_GUARD_CODE, left, right)",
    "nonnegative_division_guard_is_exact": "requires left >= 0 and right >= 0 ensure result == (right != 0) return ElisaCoreIRScalarSafety::binary_is_defined(ElisaCoreIRArithmetic::DIVIDE_GUARD_CODE, left, right)",
    "accepted_addition_result_is_bounded": "requires left >= 0 and right >= 0 requires ElisaCoreIRScalarSafety::binary_is_defined(ElisaCoreIRArithmetic::ADD_GUARD_CODE, left, right) ensure result == true return left + right >= 0 and left + right <= ElisaCoreIRArithmetic::SIGNED_I64_MAXIMUM",
    "accepted_subtraction_result_is_bounded": "requires left >= 0 and right >= 0 requires ElisaCoreIRScalarSafety::binary_is_defined(ElisaCoreIRArithmetic::SUBTRACT_GUARD_CODE, left, right) ensure result == true return left - right >= 0 - ElisaCoreIRArithmetic::SIGNED_I64_MAXIMUM and left - right <= ElisaCoreIRArithmetic::SIGNED_I64_MAXIMUM",
    "accepted_multiplication_result_is_bounded": "requires left >= 0 and right >= 0 requires ElisaCoreIRScalarSafety::binary_is_defined(ElisaCoreIRArithmetic::MULTIPLY_GUARD_CODE, left, right) ensure result == true return left * right >= 0 and left * right <= ElisaCoreIRArithmetic::SIGNED_I64_MAXIMUM",
    "accepted_division_result_is_bounded": "requires left >= 0 and right > 0 requires ElisaCoreIRScalarSafety::binary_is_defined(ElisaCoreIRArithmetic::DIVIDE_GUARD_CODE, left, right) ensure result == true return left / right >= 0 and left / right <= ElisaCoreIRArithmetic::SIGNED_I64_MAXIMUM",
}
for name, shape in positive_shapes.items():
    if compact(shape) not in compact(function_section(POSITIVE.read_text(), name)):
        raise SystemExit(f"{name} no longer states the intended scalar guard law")

negative_shapes = {
    "maximum_plus_one_is_admitted": "ensure result == true return ElisaCoreIRScalarSafety::binary_is_defined(ElisaCoreIRArithmetic::ADD_GUARD_CODE, ElisaCoreIRArithmetic::SIGNED_I64_MAXIMUM, 1)",
    "maximum_times_two_is_admitted": "ensure result == true return ElisaCoreIRScalarSafety::binary_is_defined(ElisaCoreIRArithmetic::MULTIPLY_GUARD_CODE, ElisaCoreIRArithmetic::SIGNED_I64_MAXIMUM, 2)",
    "zero_divisor_is_admitted": "ensure result == true return ElisaCoreIRScalarSafety::binary_is_defined(ElisaCoreIRArithmetic::DIVIDE_GUARD_CODE, 7, 0)",
    "negative_scalar_operand_is_admitted": "ensure result == true return ElisaCoreIRScalarSafety::binary_is_defined(ElisaCoreIRArithmetic::SUBTRACT_GUARD_CODE, 0 - 1, 0)",
}
for name, shape in negative_shapes.items():
    if compact(shape) not in compact(function_section(NEGATIVE.read_text(), name)):
        raise SystemExit(f"{name} no longer challenges a rejected scalar boundary")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("CoreIR scalar safety proofs require a strict proof build")
compiler = product["compiler"]
stage1_product = Path(compiler["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", HELPER, CORE_IR,
    NATIVE_CALLER, NATIVE_EMITTER, EDIR, POSITIVE, NEGATIVE,
    *source_include_closure([POSITIVE, NEGATIVE]),
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    result = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                            text=True, timeout=90)
    report = json.loads(result.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return result.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["declarations"] == len(positive_names) + 3
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "CoreIR scalar safety proof report changed across repeated runs"
assert "binary_is_defined" in {
    item["name"] for item in positive["declaration_details"] if item.get("verified")
}

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["verification_state"] == "disproved"
assert negative["summary"]["declarations"] == len(negative_names) + 3
assert {(finding["kind"], finding["name"]) for finding in negative["findings"]} == {
    ("ensure-unproven", name) for name in negative_names
}
assert all(finding["status"] == "disproved" and finding["counterexample_found"]
           for finding in negative["findings"])
assert "binary_is_defined" in {
    item["name"] for item in negative["declaration_details"] if item.get("verified")
}
assert product == require_current_product(BIN, PROVER)
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
if hashes_before != hashes_after:
    raise SystemExit("CoreIR scalar safety proof inputs changed during replay")

print(json.dumps({
    "admitted": True,
    "scope": "CoreIR signed-i64 preflight, exact guard boundaries, and accepted-operation result bounds for native and EDIR consumers",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": compiler.get("source_revision"),
    "inputs_sha256": hashes_before,
}, sort_keys=True))
