"""Bind replayed proofs to the backend element-stride sizing policy."""
from __future__ import annotations

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
SIZES = ROOT / "src/backend/codegen_type_sizes.elisa"
VALUE_TYPE = ROOT / "src/backend/codegen_value_type.elisa"
POLICY = ROOT / "src/backend/codegen_element_stride_policy.elisa"
CODEGEN = ROOT / "src/backend/codegen.elisa"
CONTAINER_OPS = ROOT / "src/backend/codegen_container_ops.elisa"
COMPREHENSION = ROOT / "src/backend/codegen_comprehension.elisa"
CLONE = ROOT / "src/backend/codegen_clone.elisa"
EXPR_LITERALS = ROOT / "src/backend/codegen_expr_literals.elisa"
POSITIVE = HERE / "backend_element_stride.elisa"
NEGATIVE = HERE / "backend_element_stride_rejected.elisa"

POSITIVE_NAMES = {
    "scalar_kind_policy_is_exact",
    "a_string_view_uses_the_layout_size_path",
    "every_non_scalar_kind_uses_llvm_layout_sizing",
    "scalar_byte_size_matches_boolean_or_u32_width_formula",
    "boolean_stride_is_one_byte_for_every_recorded_width",
    "eight_bit_scalar_stride_is_one_byte",
    "sixteen_bit_scalar_stride_is_two_bytes",
    "thirty_two_bit_scalar_stride_is_four_bytes",
    "sixty_four_bit_scalar_stride_is_eight_bytes",
}
NEGATIVE_NAMES = {
    "a_string_view_is_sent_through_scalar_bit_width_sizing",
    "a_one_bit_boolean_has_zero_bytes",
    "a_32_bit_scalar_has_one_byte",
}

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in text.splitlines())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    section = source[match.start():end]
    return re.sub(r"(?m)^[ \t]*@[A-Za-z_][^\n]*\n", "", section)


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


sizes_text = SIZES.read_text()
backend_shapes = {
    "element_stride": """
def element_stride(element_type: ValueType, structs: mutable StructTable&, ctx: LLVMContextRef) -> LLVMValueRef can[Abort.Panic]:
    can Abort.Panic, Memory.Allocate, Unsafe.PointerCast:
        if BackendElementStridePolicy::uses_scalar_byte_size(element_type.kind == TypeKind.Signed, element_type.kind == TypeKind.Unsigned, element_type.kind == TypeKind.Float, element_type.kind == TypeKind.Bool):
            return LLVMConstInt(LLVMInt64TypeInContext(ctx), scalar_byte_size(element_type), 0)
        return LLVMSizeOf(llvm_type_of(element_type, structs, ctx))
""",
    "scalar_byte_size": """
def scalar_byte_size(value_type: ValueType) -> u64:
    return BackendElementStridePolicy::scalar_byte_size(value_type.kind == TypeKind.Bool, value_type.bits).u64()
""",
}
for name, expected in backend_shapes.items():
    if compact(function_section(sizes_text, name)) != compact(expected):
        raise SystemExit(f"production element sizing function {name} changed without updating its proof binding")

policy_text = POLICY.read_text()
if not compact(policy_text).startswith("moduleBackendElementStridePolicy:public:"):
    raise SystemExit("the pure stride policy must remain public through BackendElementStridePolicy")
policy_shapes = {
    "uses_scalar_byte_size": """
def uses_scalar_byte_size(is_signed: bool, is_unsigned: bool, is_float: bool, is_bool: bool) -> bool:
    ensure result == (is_signed or is_unsigned or is_float or is_bool)
    return is_signed or is_unsigned or is_float or is_bool
""",
    "scalar_byte_size": """
def scalar_byte_size(is_bool: bool, bit_width: u32) -> u32:
    ensure result == (1 if is_bool else bit_width / 8)
    return 1 if is_bool else bit_width / 8
""",
}
for name, expected in policy_shapes.items():
    if compact(function_section(policy_text, name)) != compact(expected):
        raise SystemExit(f"production stride policy {name} changed without updating its proof binding")
    if compact(policy_text).count(f"@inline(always)def{name}(") != 1:
        raise SystemExit(f"production stride policy {name} lost its always-inline annotation")

codegen_text = compact(CODEGEN.read_text())
policy_include = compact('include "./codegen_element_stride_policy.elisa"')
backend_include = compact('include "./codegen_env.elisa"')
if (codegen_text.find(policy_include) < 0 or codegen_text.find(backend_include) < 0 or
        codegen_text.find(policy_include) >= codegen_text.find(backend_include)):
    raise SystemExit("the backend no longer includes the proof-bound stride policy before its codegen modules")

if compact("struct ValueType: kind: TypeKind bits: u32") not in compact(VALUE_TYPE.read_text()):
    raise SystemExit("ValueType.bits no longer records a u32 scalar width")

value_type_text = VALUE_TYPE.read_text()
kind_start = value_type_text.find("const enum TypeKind of u8:")
kind_end = value_type_text.find("struct ValueType:", kind_start)
if kind_start < 0 or kind_end < 0:
    raise SystemExit("backend TypeKind declaration or ValueType record disappeared")
kind_variants = re.findall(r"(?m)^\s+([A-Z][A-Za-z0-9_]*)\s*$", value_type_text[kind_start:kind_end])
expected_kind_variants = [
    "Unmodeled", "Signed", "Unsigned", "Bool", "Float", "Void", "Struct", "Array",
    "PackedEnum", "PackedStore", "Arena", "PayloadEnum", "CStr", "PyObject", "Ref",
    "Optional", "ErrorUnion", "DArray", "View", "SView", "Fn", "GuestCarrier", "ConstUsize",
]
if kind_variants != expected_kind_variants:
    raise SystemExit("backend TypeKind variants changed without updating the scalar/layout partition proof")

stride_call_sites = {
    CONTAINER_OPS: {
        "emit_darray_push": "stride:LLVMValueRef=element_stride(element_type,structs,ctx)",
        "emit_darray_reserve": "stride:LLVMValueRef=element_stride(element_type,structs,ctx)",
        "emit_darray_append_copy": "stride:LLVMValueRef=element_stride(element_type,structs,ctx)",
    },
    COMPREHENSION: {
        "emit_comprehension": "stride:LLVMValueRef=element_stride(element_type,structs,ctx)",
    },
    CLONE: {
        "emit_clone_nested_darray_value": "stride:LLVMValueRef=element_stride(target_element,structs,ctx)",
        "emit_clone_darray_builtin": "stride:LLVMValueRef=element_stride(target_element,structs,ctx)",
    },
    EXPR_LITERALS: {
        "emit_expression_literals": "element_stride(region_new_pointee,structs,ctx)",
    },
}
for source_path, functions in stride_call_sites.items():
    source = source_path.read_text()
    for function_name, expected_call in functions.items():
        if compact(expected_call) not in compact(function_section(source, function_name)):
            raise SystemExit(f"{function_name} no longer routes element allocation through element_stride")

proof_shapes = {
    "scalar_kind_policy_is_exact": """
def scalar_kind_policy_is_exact(is_signed: bool, is_unsigned: bool, is_float: bool, is_bool: bool) -> bool:
    ensure result == true
    return BackendElementStridePolicy::uses_scalar_byte_size(is_signed, is_unsigned, is_float, is_bool) == (is_signed or is_unsigned or is_float or is_bool)
""",
    "a_string_view_uses_the_layout_size_path": """
def a_string_view_uses_the_layout_size_path(is_signed: bool, is_unsigned: bool, is_float: bool, is_bool: bool, is_sview: bool) -> bool:
    requires is_sview and not is_signed and not is_unsigned and not is_float and not is_bool
    ensure result == true
    return not BackendElementStridePolicy::uses_scalar_byte_size(is_signed, is_unsigned, is_float, is_bool)
""",
    "every_non_scalar_kind_uses_llvm_layout_sizing": """
def every_non_scalar_kind_uses_llvm_layout_sizing(is_signed: bool, is_unsigned: bool, is_float: bool, is_bool: bool) -> bool:
    requires not (is_signed or is_unsigned or is_float or is_bool)
    ensure result == true
    return not BackendElementStridePolicy::uses_scalar_byte_size(is_signed, is_unsigned, is_float, is_bool)
""",
    "scalar_byte_size_matches_boolean_or_u32_width_formula": """
def scalar_byte_size_matches_boolean_or_u32_width_formula(is_bool: bool, bit_width: u32) -> bool:
    ensure result == true
    return BackendElementStridePolicy::scalar_byte_size(is_bool, bit_width) == (1 if is_bool else bit_width / 8)
""",
    "boolean_stride_is_one_byte_for_every_recorded_width": """
def boolean_stride_is_one_byte_for_every_recorded_width(bit_width: u32) -> bool:
    ensure result == true
    return BackendElementStridePolicy::scalar_byte_size(true, bit_width) == 1
""",
    "eight_bit_scalar_stride_is_one_byte": """
def eight_bit_scalar_stride_is_one_byte() -> bool:
    ensure result == true
    return BackendElementStridePolicy::scalar_byte_size(false, 8) == 1
""",
    "sixteen_bit_scalar_stride_is_two_bytes": """
def sixteen_bit_scalar_stride_is_two_bytes() -> bool:
    ensure result == true
    return BackendElementStridePolicy::scalar_byte_size(false, 16) == 2
""",
    "thirty_two_bit_scalar_stride_is_four_bytes": """
def thirty_two_bit_scalar_stride_is_four_bytes() -> bool:
    ensure result == true
    return BackendElementStridePolicy::scalar_byte_size(false, 32) == 4
""",
    "sixty_four_bit_scalar_stride_is_eight_bytes": """
def sixty_four_bit_scalar_stride_is_eight_bytes() -> bool:
    ensure result == true
    return BackendElementStridePolicy::scalar_byte_size(false, 64) == 8
""",
}
negative_shapes = {
    "a_string_view_is_sent_through_scalar_bit_width_sizing": """
def a_string_view_is_sent_through_scalar_bit_width_sizing(is_signed: bool, is_unsigned: bool, is_float: bool, is_bool: bool, is_sview: bool) -> bool:
    requires is_sview and not is_signed and not is_unsigned and not is_float and not is_bool
    ensure result == true
    return BackendElementStridePolicy::uses_scalar_byte_size(is_signed, is_unsigned, is_float, is_bool)
""",
    "a_one_bit_boolean_has_zero_bytes": """
def a_one_bit_boolean_has_zero_bytes() -> bool:
    ensure result == true
    return BackendElementStridePolicy::scalar_byte_size(true, 1) == 0
""",
    "a_32_bit_scalar_has_one_byte": """
def a_32_bit_scalar_has_one_byte() -> bool:
    ensure result == true
    return BackendElementStridePolicy::scalar_byte_size(false, 32) == 1
""",
}

if declarations(POSITIVE) != POSITIVE_NAMES or declarations(NEGATIVE) != NEGATIVE_NAMES:
    raise SystemExit("element-stride proof inventory is incomplete or contains unexpected declarations")
for path, shapes in ((POSITIVE, proof_shapes), (NEGATIVE, negative_shapes)):
    source = path.read_text()
    for name, expected in shapes.items():
        if compact(function_section(source, name)) != compact(expected):
            raise SystemExit(f"{name} no longer proves the source-bound element-stride formula")
if 'include "./backend_element_stride.elisa"' not in NEGATIVE.read_text():
    raise SystemExit("negative controls no longer include the positive element-stride proofs")
if 'include "../../src/backend/codegen_element_stride_policy.elisa"' not in POSITIVE.read_text():
    raise SystemExit("proofs no longer include the production element-stride policy directly")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("element-stride proofs require a strict proof build")

stage1_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
manifest = BIN.with_name(BIN.name + ".manifest.json")
inputs = list(dict.fromkeys([
    BIN, manifest, manifest.with_name(manifest.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", SIZES, VALUE_TYPE, POLICY, CODEGEN,
    CONTAINER_OPS, COMPREHENSION, CLONE, EXPR_LITERALS, POSITIVE, NEGATIVE,
    *source_include_closure([POSITIVE, NEGATIVE]),
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def replay(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=60)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"]
    assert report["trust"]["kernel_replayed_certificates"] == report["replay"]["replayed"]
    return process.returncode, report


code, positive = replay(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
expected_positive_functions = POSITIVE_NAMES | set(policy_shapes)
expected_positive_declarations = expected_positive_functions | {"BackendElementStridePolicy"}
assert {row["name"] for row in positive["declaration_details"]} == expected_positive_declarations
assert positive["summary"]["declarations"] == len(expected_positive_declarations)
assert positive["summary"]["obligations"] == positive["summary"]["proven"]
assert not positive["findings"]
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == expected_positive_functions
assert positive == replay(POSITIVE)[1], "element-stride proof report changed across identical runs"

code, negative = replay(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
expected_negative_functions = expected_positive_functions | NEGATIVE_NAMES
expected_negative_declarations = expected_negative_functions | {"BackendElementStridePolicy"}
assert {row["name"] for row in negative["declaration_details"]} == expected_negative_declarations
assert negative["summary"]["declarations"] == len(expected_negative_declarations)
assert negative["summary"]["unproven"] == len(NEGATIVE_NAMES)
assert negative["summary"]["proven"] == negative["summary"]["obligations"] - len(NEGATIVE_NAMES)
assert negative["summary"]["finding_count"] == len(NEGATIVE_NAMES)
assert {row["name"] for row in negative["findings"]} == NEGATIVE_NAMES
assert all(row["kind"] == "ensure-unproven" and row["status"] in ("unknown", "disproved")
           for row in negative["findings"])
assert {row["name"] for row in negative["declaration_details"] if row.get("verified")} == expected_positive_functions

assert require_current_product(BIN, PROVER) == product
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "element-stride proof inputs changed during replay or provenance validation"
print(json.dumps({
    "admitted": True,
    "scope": "production scalar stride and byte-size policy, its LLVM-layout fallback, and darray/comprehension/clone call sites",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(NEGATIVE_NAMES),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "source_sha256": hashes_before,
}, sort_keys=True))
