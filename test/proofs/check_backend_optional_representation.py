"""Replay source-bound optional representation decisions for the LLVM backend."""
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
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
FACADE = ROOT / "src/backend/codegen.elisa"
OPTIONALS = ROOT / "src/backend/codegen_optionals.elisa"
PLACE = ROOT / "src/backend/codegen_place.elisa"
TYPE_TABLES = ROOT / "src/backend/codegen_type_tables.elisa"
LLVM_TYPES = ROOT / "src/backend/codegen_llvm_types.elisa"
LLVM_C = ROOT / "src/backend/llvm_c.elisa"
VALUE_TYPES = ROOT / "src/backend/codegen_value_type.elisa"
POLICY = ROOT / "src/backend/codegen_optional_representation_policy.elisa"
POSITIVE = HERE / "backend_optional_representation.elisa"
NEGATIVE = HERE / "backend_optional_representation_rejected.elisa"

POSITIVE_NAMES = {
    "pointer_payload_partition_is_exact",
    "tagged_null_test_partition_is_exact",
    "reference_payload_uses_the_null_niche",
    "c_string_payload_uses_the_null_niche",
    "function_payload_uses_the_null_niche",
    "python_object_payload_uses_the_null_niche",
    "scalar_payload_uses_the_tagged_representation",
    "ordinary_nonnull_tagged_payload_keeps_constant_presence",
    "c_string_tagged_payload_tests_for_null",
    "heap_reference_tagged_payload_tests_for_null",
    "forced_tagged_payload_tests_for_null",
}
NEGATIVE_NAMES = {
    "a_scalar_payload_cannot_use_the_null_niche",
    "a_nonnullable_tagged_payload_does_not_need_a_null_test",
    "a_forced_tagged_payload_cannot_skip_the_null_test",
}
POLICY_NAMES = {"pointer_payload_uses_niche", "tagged_payload_needs_null_test"}


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
    return source[match.start():end]


def declaration_names(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


policy_text = POLICY.read_text()
policy_shapes = {
    "pointer_payload_uses_niche": """
def pointer_payload_uses_niche(is_ref: bool, is_cstr: bool, is_fn: bool, is_pyobject: bool) -> bool:
    ensure result == (is_ref or is_cstr or is_fn or is_pyobject)
    return is_ref or is_cstr or is_fn or is_pyobject
""",
    "tagged_payload_needs_null_test": """
def tagged_payload_needs_null_test(force_null_test: bool, is_cstr: bool, is_heap_ref: bool) -> bool:
    ensure result == (force_null_test or is_cstr or is_heap_ref)
    return force_null_test or is_cstr or is_heap_ref
""",
}
if not compact(policy_text).startswith("moduleBackendOptionalRepresentationPolicy:public:"):
    raise SystemExit("optional representation policy must remain public through its named module")
for name, expected in policy_shapes.items():
    if compact(function_section(policy_text, name)) != compact(expected):
        raise SystemExit(f"production optional representation policy {name} changed without its proof")

optional_is_niche = compact(function_section(OPTIONALS.read_text(), "optional_is_niche"))
expected_optional_is_niche = compact("""
def optional_is_niche(optional_type: ValueType, structs: mutable StructTable&) -> bool can[Abort.Panic]:
    can Abort.Panic:
        false return if optional_type.kind != TypeKind.Optional
        niche_payload: ValueType = optional_payload_of(optional_type, structs)
        return BackendOptionalRepresentationPolicy::pointer_payload_uses_niche(
            niche_payload.kind == TypeKind.Ref,
            niche_payload.kind == TypeKind.CStr,
            niche_payload.kind == TypeKind.Fn,
            niche_payload.kind == TypeKind.PyObject)
""")
if optional_is_niche != expected_optional_is_niche:
    raise SystemExit("optional niche classification no longer guards the payload lookup and uses the proved partition")

optional_tag = compact(function_section(OPTIONALS.read_text(), "optional_tag_of"))
null_presence_branch = (
    "ifoptional_is_niche(optional_type,structs):"
    "returnLLVMBuildICmp(builder,LLVMIntPredicate::NE,optional_value,"
    "LLVMConstNull(LLVMPointerTypeInContext(ctx,0)),\"opt.present\")"
)
if null_presence_branch not in optional_tag or \
        "returnLLVMBuildExtractValue(builder,optional_value,0,\"opt.tag\")" not in optional_tag:
    raise SystemExit("optional presence must use a null test for niche values and field zero for tagged values")

optional_payload = compact(function_section(OPTIONALS.read_text(), "optional_payload_value_of"))
if ("optional_valuereturnifoptional_is_niche(optional_type,structs)" not in optional_payload or
        "returnLLVMBuildExtractValue(builder,optional_value,1,\"opt.payload\")" not in optional_payload):
    raise SystemExit("optional payload must be the pointer itself for niche values and field one for tagged values")

wrap = compact(function_section(OPTIONALS.read_text(), "wrap_optional_tagged"))
wrap_steps = (
    "valuereturnifoptional_is_niche(optional_type,structs)",
    "payload_type:ValueType=optional_payload_of(optional_type,structs)",
    (
        "BackendOptionalRepresentationPolicy::tagged_payload_needs_null_test("
        "force_null_test,payload_type.kind==TypeKind.CStr,"
        "payload_type.kind==TypeKind.Refandref_is_heap_ref(payload_type,structs))"
    ),
    "LLVMBuildStore(builder,LLVMBuildICmp(builder,LLVMIntPredicate::NE,value,null_pointer,\"opt.present\"),tag_pointer)",
    "LLVMBuildStore(builder,LLVMConstInt(LLVMInt1TypeInContext(ctx),1,0),tag_pointer)",
    "value_pointer:LLVMValueRef=LLVMBuildStructGEP2(builder,optional_llvm,slot,1,\"opt.value.ptr\")",
    "_=LLVMBuildStore(builder,value,value_pointer)",
    "returnLLVMBuildLoad2(builder,optional_llvm,slot,\"opt.wrapped\")",
)
positions = [wrap.find(step) for step in wrap_steps]
if any(position < 0 for position in positions) or positions != sorted(positions):
    raise SystemExit("optional wrapping no longer applies the proved null-tag rule before storing its payload")
if wrap.count("LLVMBuildStore(builder,value,value_pointer)") != 1:
    raise SystemExit("optional wrapping must store the payload exactly once after selecting its tag")
if compact("NE: i32 = 33") not in compact(LLVM_C.read_text()):
    raise SystemExit("LLVMIntPredicate::NE no longer binds to LLVM-C's not-equal predicate")
if wrap.count("LLVMIntPredicate::NE") != 1 or optional_tag.count("LLVMIntPredicate::NE") != 1:
    raise SystemExit("optional null checks must use the named LLVM not-equal predicate")

type_table_text = TYPE_TABLES.read_text()
if compact(function_section(type_table_text, "optional_payload_of")) != compact("""
def optional_payload_of(value_type: ValueType, structs: mutable StructTable&) -> ValueType can[Abort.Panic]:
    unmodeled_type() return if value_type.kind != TypeKind.Optional
    return copied_type(structs.interned_types.optional_targets[value_type.bits.usize()])
"""):
    raise SystemExit("optional payload lookup no longer checks the variant tag before reading its interned payload")
if compact(function_section(type_table_text, "ref_is_heap_ref")) != compact("""
def ref_is_heap_ref(value_type: ValueType, structs: StructTable&) -> bool can[Abort.Panic]:
    return value_type.kind == TypeKind.Ref and structs.interned_types.ref_is_heap[value_type.bits.usize()]
"""):
    raise SystemExit("heap-reference nullability no longer follows the recorded reference-kind row")

intern_optional = compact(function_section(type_table_text, "intern_optional_type"))
intern_optional_steps = (
    "unmodeled_type()returnifpayload.kind==TypeKind.Unmodeledorpayload.kind==TypeKind.Optional",
    "forindexin0..<structs.interned_types.optional_targets.count",
    "existing:ValueType=structs.interned_types.optional_targets[index]",
    "ifvalue_type_identity_equal(existing,payload):returnValueType{kind:TypeKind.Optional,bits:index.u32()}",
    "structs.interned_types.optional_targets<-structs.interned_types.optional_targets.push(payload)",
    "returnValueType{kind:TypeKind.Optional,bits:(structs.interned_types.optional_targets.count-1).u32()}",
)
intern_optional_positions = [intern_optional.find(step) for step in intern_optional_steps]
if any(position < 0 for position in intern_optional_positions) or intern_optional_positions != sorted(intern_optional_positions):
    raise SystemExit("optional TypeIds no longer point to the matching interned payload row")

llvm_type = compact(function_section(LLVM_TYPES.read_text(), "llvm_type_of"))
llvm_optional_steps = (
    "ifvalue_type.kind==TypeKind.Optional:",
    "payload:ValueType=copied_type(structs.interned_types.optional_targets[value_type.bits.usize()])",
    "llvm_type_of(payload,structs,ctx)returnifoptional_is_niche(value_type,structs)",
    "fields:mutabledarray[LLVMTypeRef]=[LLVMInt1TypeInContext(ctx),llvm_type_of(payload,structs,ctx)]",
    "returnLLVMStructTypeInContext(ctx,fields_pointer,2,0)",
)
llvm_optional_positions = [llvm_type.find(step) for step in llvm_optional_steps]
if any(position < 0 for position in llvm_optional_positions) or llvm_optional_positions != sorted(llvm_optional_positions):
    raise SystemExit("LLVM optional type layout no longer shares the niche decision with value encoding")

facade_text = compact(FACADE.read_text())
place_text = compact(PLACE.read_text())
if ('include"./codegen_place.elisa"' not in facade_text or
        'include"./codegen_optionals.elisa"' not in place_text):
    raise SystemExit("the proof-bound optional implementation is no longer included by the backend")
kind_region = VALUE_TYPES.read_text()
kind_start = kind_region.find("const enum TypeKind of u8:")
kind_end = kind_region.find("struct ValueType:", kind_start)
if kind_start < 0 or kind_end < 0:
    raise SystemExit("backend TypeKind declaration or ValueType record disappeared")
kinds = set(re.findall(r"(?m)^\s+([A-Z][A-Za-z0-9_]*)\s*$", kind_region[kind_start:kind_end]))
if not {"Optional", "Ref", "CStr", "Fn", "PyObject"}.issubset(kinds):
    raise SystemExit("optional niche proof no longer matches the backend's relevant TypeKind members")

if 'include "../../src/backend/codegen_optional_representation_policy.elisa"' not in POSITIVE.read_text():
    raise SystemExit("positive optional proofs no longer import the production policy")
if 'include "./backend_optional_representation.elisa"' not in NEGATIVE.read_text():
    raise SystemExit("negative optional claims no longer extend the positive proof module")
if declaration_names(POSITIVE) != POSITIVE_NAMES or declaration_names(NEGATIVE) != NEGATIVE_NAMES:
    raise SystemExit("optional representation proof inventory changed")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("optional representation proofs require a strict proof build")

stage1_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", FACADE, OPTIONALS, PLACE,
    TYPE_TABLES, LLVM_TYPES, LLVM_C, VALUE_TYPES, POLICY, POSITIVE, NEGATIVE,
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
positive_verified = POSITIVE_NAMES | POLICY_NAMES
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == positive_verified
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
assert not positive["findings"]

code, negative = replay(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert {row["name"] for row in negative["findings"]} == NEGATIVE_NAMES
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert NEGATIVE_NAMES.isdisjoint({row["name"] for row in negative["declaration_details"] if row.get("verified")})
assert require_current_product(BIN, PROVER) == product
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "optional proof inputs changed during replay or provenance validation"
print(json.dumps({
    "admitted": True,
    "scope": "pointer optional niche classification, tagged presence tests, payload projection, and wrapping tag stores",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(NEGATIVE_NAMES),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "source_sha256": hashes_before,
}, sort_keys=True))
