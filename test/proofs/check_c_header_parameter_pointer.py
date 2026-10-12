"""Admit the exported-C-parameter pointer rule against the production emitter."""
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
HEADER = ROOT / "src/backend/c_header.elisa"
MODEL = ROOT / "src/backend/c_header_parameter_pointer.elisa"
PROTOTYPE_MARKER = ROOT / "src/backend/c_header_prototype_marker.elisa"
RETURN_POINTER = ROOT / "src/backend/c_header_return_pointer.elisa"
TYPES = ROOT / "src/backend/c_header_types.elisa"
CODEGEN_ENV = ROOT / "src/backend/codegen_env.elisa"
POSITIVE = HERE / "c_header_parameter_pointer.elisa"
NEGATIVE = HERE / "c_header_parameter_pointer_rejected.elisa"

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
    lines = source[start:end].splitlines()
    while lines and (not lines[-1].strip() or lines[-1].lstrip().startswith(("#", "@"))):
        lines.pop()
    return "\n".join(line for line in lines if not line.lstrip().startswith("#"))


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


expected_model = compact("""def star_count(provenance_bearing: bool, ordinary_pointer_depth: i64) -> i64:
            ensure result == (1 if provenance_bearing else ordinary_pointer_depth)
            return 1 if provenance_bearing else ordinary_pointer_depth""")
if compact(function_section(MODEL.read_text(), "star_count")) != expected_model:
    raise SystemExit("parameter-star model no longer states the exact ABI selection rule")
expected_prototype_marker = compact("""def needs_void_parameter_marker(arity: usize) -> bool:
            ensure result == (arity == 0)
            return arity == 0""")
if compact(function_section(PROTOTYPE_MARKER.read_text(), "needs_void_parameter_marker")) != expected_prototype_marker:
    raise SystemExit("C prototype model no longer selects the void marker exactly for zero arity")
expected_return_pointer = compact("""def matches_marker(annotation_owner: sview, annotation_name: sview, function_name: sview) -> bool:
            ensure result == (annotation_owner == "__extern_return_ptr" and annotation_name == function_name)
            return annotation_owner == "__extern_return_ptr" and annotation_name == function_name""")
if compact(function_section(RETURN_POINTER.read_text(), "matches_marker")) != expected_return_pointer:
    raise SystemExit("return-pointer model no longer selects only the matching marker row")
if 'include "./c_header_parameter_pointer.elisa"' not in HEADER.read_text():
    raise SystemExit("C header generator no longer imports the proved parameter-star function")
if 'include "./c_header_prototype_marker.elisa"' not in HEADER.read_text():
    raise SystemExit("C header generator no longer imports the proved zero-arity marker function")
if 'include "./c_header_return_pointer.elisa"' not in HEADER.read_text():
    raise SystemExit("C header generator no longer imports the proved return-pointer marker function")

expected_depth = compact("""def header_pointer_depth(value_type: ValueType, structs: mutable StructTable&) -> i64 can[Abort.Panic]:
            can Abort.Panic:
                depth: mutable i64 = 0
                cursor: mutable ValueType = copied_type(value_type)
                if cursor.kind == TypeKind.Optional:
                    payload: ValueType = copied_type(structs.interned_types.optional_targets[cursor.bits.usize()])
                    cursor <- payload
                if cursor.kind == TypeKind.CStr:
                    return 1
                while cursor.kind == TypeKind.Ref |cursor, depth, structs|:
                    depth <- depth + 1
                    cursor <- copied_type(structs.interned_types.ref_targets[cursor.bits.usize()])
                return depth""")
if compact(function_section(TYPES.read_text(), "header_pointer_depth")) != expected_depth:
    raise SystemExit("resolved-type pointer depth no longer follows the source-bound calculation")

expected_emitter = compact("""def header_exported_functions(file: Ast::File&, structs: mutable StructTable, out: mutable darray[u8]&) -> bool can[Abort.Panic, Memory.Allocate, Unsafe.PointerCast]:
            can Abort.Panic, Memory.Allocate:
                out.reserve(out.count + file.top_decls.count)
                for declaration in file.top_decls |file, structs, out|:
                    match declaration:
                        Decl.Extern(function_name, param_start, arity, variadic, callable, return_type_name, decorators, line):
                            is_export: mutable bool = false
                            for annotation in file.enum_annotations |is_export, function_name|:
                                is_export <- true if annotation.owner == function_name and annotation.name == "__export_fn"
                            continue if not is_export or not callable
                            return_type: ValueType = header_type_from_name(return_type_name, &structs)
                            return_pointer: mutable bool = false
                            for annotation in file.enum_annotations |return_pointer, function_name|:
                                return_pointer <- true if CHeaderReturnPointer::matches_marker(annotation.owner, annotation.name, function_name)
                            false return if return_type.kind == TypeKind.Unmodeled
                            if not header_c_name_for_source_type(return_type_name, out):
                                false return if not header_type_name(file, return_type, &structs, out)
                            out.push(32)
                            for _return_star in 0..<header_pointer_depth(return_type, &structs) |out|:
                                out.push(42)
                            out.push(42) if return_pointer
                            header_push(out, function_name)
                            out.push(40)
                            header_push(out, "void") if CHeaderPrototypeMarker::needs_void_parameter_marker(arity)
                            for parameter_index in 0..<arity.usize() |file, structs, out, param_start|:
                                header_push(out, ", ") if parameter_index > 0
                                parameter: ExternParam = file.extern_params[param_start.usize() + parameter_index]
                                parameter_type: ValueType = header_type_from_name(parameter.type_name, &structs)
                                false return if parameter_type.kind == TypeKind.Unmodeled
                                if not header_c_name_for_source_type(parameter.type_name, out):
                                    false return if not header_type_name(file, parameter_type, &structs, out)
                                out.push(32)
                                ordinary_pointer_depth: mutable i64 = 0
                                ordinary_pointer_depth <- header_pointer_depth(parameter_type, &structs) if not parameter.provenance_bearing
                                parameter_pointer_depth: i64 = CHeaderParameterPointer::star_count(parameter.provenance_bearing, ordinary_pointer_depth)
                                for _parameter_star in 0..<parameter_pointer_depth |out|:
                                    out.push(42)
                                header_push(out, "arg")
                                header_push_int(out, parameter_index.i64())
                            header_push(out, ");\\n")
                        _:
                            pass
                return true""")
if compact(function_section(HEADER.read_text(), "header_exported_functions")) != expected_emitter:
    raise SystemExit("exported function prototypes no longer emit the proved number of parameter stars")
if 'include "c_header.elisa"' not in CODEGEN_ENV.read_text():
    raise SystemExit("production backend assembly no longer includes the C header emitter")

positive_shapes = {
    "provenance_parameter_always_uses_one_pointer": "def provenance_parameter_always_uses_one_pointer(depth: i64) -> bool: ensure result == true return CHeaderParameterPointer::star_count(true, depth) == 1",
    "value_parameter_preserves_resolved_type_depth": "def value_parameter_preserves_resolved_type_depth(depth: i64) -> bool: ensure result == true return CHeaderParameterPointer::star_count(false, depth) == depth",
    "value_parameter_with_no_pointer_depth_stays_by_value": "def value_parameter_with_no_pointer_depth_stays_by_value() -> bool: ensure result == true return CHeaderParameterPointer::star_count(false, 0) == 0",
    "provenance_parameter_ignores_even_nested_source_depth": "def provenance_parameter_ignores_even_nested_source_depth() -> bool: ensure result == true return CHeaderParameterPointer::star_count(true, 3) == 1",
    "selected_pointer_count_matches_the_exact_abi_rule": "def selected_pointer_count_matches_the_exact_abi_rule(provenance_bearing: bool, depth: i64) -> bool: ensure result == true return CHeaderParameterPointer::star_count(provenance_bearing, depth) == (1 if provenance_bearing else depth)",
    "zero_arity_requires_the_c_void_marker": "def zero_arity_requires_the_c_void_marker() -> bool: ensure result == true return CHeaderPrototypeMarker::needs_void_parameter_marker(0) == true",
    "nonzero_arity_omits_the_c_void_marker": "def nonzero_arity_omits_the_c_void_marker(arity: usize) -> bool: requires arity > 0 ensure result == true return not CHeaderPrototypeMarker::needs_void_parameter_marker(arity)",
    "void_marker_predicate_matches_exact_zero_arity": "def void_marker_predicate_matches_exact_zero_arity(arity: usize) -> bool: ensure result == true return CHeaderPrototypeMarker::needs_void_parameter_marker(arity) == (arity == 0)",
    "return_pointer_marker_matches_exact_owner_and_function": "def return_pointer_marker_matches_exact_owner_and_function(annotation_owner: sview, annotation_name: sview, function_name: sview) -> bool: ensure result == true return CHeaderReturnPointer::matches_marker(annotation_owner, annotation_name, function_name) == (annotation_owner == \"__extern_return_ptr\" and annotation_name == function_name)",
    "exact_return_pointer_marker_is_recognized": "def exact_return_pointer_marker_is_recognized(function_name: sview) -> bool: ensure result == true return CHeaderReturnPointer::matches_marker(\"__extern_return_ptr\", function_name, function_name)",
    "different_return_pointer_annotation_owner_is_ignored": "def different_return_pointer_annotation_owner_is_ignored(annotation_owner: sview, annotation_name: sview, function_name: sview) -> bool: requires annotation_owner != \"__extern_return_ptr\" ensure result == true return not CHeaderReturnPointer::matches_marker(annotation_owner, annotation_name, function_name)",
    "return_pointer_marker_for_another_function_is_ignored": "def return_pointer_marker_for_another_function_is_ignored(annotation_name: sview, function_name: sview) -> bool: requires annotation_name != function_name ensure result == true return not CHeaderReturnPointer::matches_marker(\"__extern_return_ptr\", annotation_name, function_name)",
}
negative_shapes = {
    "reference_parameter_must_not_use_source_depth": "def reference_parameter_must_not_use_source_depth() -> bool: ensure result == true return CHeaderParameterPointer::star_count(true, 3) == 3",
    "value_parameter_must_not_gain_a_pointer": "def value_parameter_must_not_gain_a_pointer() -> bool: ensure result == true return CHeaderParameterPointer::star_count(false, 0) == 1",
    "value_parameter_must_not_lose_a_pointer_level": "def value_parameter_must_not_lose_a_pointer_level() -> bool: ensure result == true return CHeaderParameterPointer::star_count(false, 3) == 2",
    "zero_arity_must_not_omit_the_c_void_marker": "def zero_arity_must_not_omit_the_c_void_marker() -> bool: ensure result == true return not CHeaderPrototypeMarker::needs_void_parameter_marker(0)",
    "positive_arity_must_not_emit_the_c_void_marker": "def positive_arity_must_not_emit_the_c_void_marker() -> bool: ensure result == true return CHeaderPrototypeMarker::needs_void_parameter_marker(1)",
    "other_annotation_owner_must_not_select_a_pointer_return": "def other_annotation_owner_must_not_select_a_pointer_return() -> bool: ensure result == true return CHeaderReturnPointer::matches_marker(\"__export_fn\", \"f\", \"f\")",
    "pointer_return_marker_must_not_match_every_function": "def pointer_return_marker_must_not_match_every_function() -> bool: ensure result == true return CHeaderReturnPointer::matches_marker(\"__extern_return_ptr\", \"f\", \"g\")",
}
for path, shapes in ((POSITIVE, positive_shapes), (NEGATIVE, negative_shapes)):
    if declarations(path) != set(shapes):
        raise SystemExit(f"{path.name} theorem inventory changed")
    if 'include "../../src/backend/c_header_parameter_pointer.elisa"' not in path.read_text():
        raise SystemExit(f"{path.name} no longer imports the production parameter-star function")
    if 'include "../../src/backend/c_header_prototype_marker.elisa"' not in path.read_text():
        raise SystemExit(f"{path.name} no longer imports the production zero-arity marker function")
    if 'include "../../src/backend/c_header_return_pointer.elisa"' not in path.read_text():
        raise SystemExit(f"{path.name} no longer imports the production return-pointer marker function")
    for name, shape in shapes.items():
        if compact(function_section(path.read_text(), name)) != compact(shape):
            raise SystemExit(f"{name} no longer states the source-bound parameter-star theorem")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("C header parameter proof requires a strict proof build")
compiler = product["compiler"]
stage1_product = Path(compiler["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", POSITIVE, NEGATIVE,
    HEADER, MODEL, PROTOTYPE_MARKER, RETURN_POINTER, TYPES, CODEGEN_ENV,
    *source_include_closure([POSITIVE, NEGATIVE]),
]))
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
assert positive == run(POSITIVE)[1], "C header parameter proof report changed across repeated runs"
verified = {item["name"] for item in positive["declaration_details"] if item.get("verified")}
assert set(positive_shapes) | {"star_count", "needs_void_parameter_marker", "matches_marker"} <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative == run(NEGATIVE)[1], "C header rejected-claim report changed across repeated runs"
assert negative["verification_state"] == "disproved"
assert {(item["kind"], item["name"]) for item in negative["findings"]} == {
    ("ensure-unproven", name) for name in negative_shapes
}
assert all(item["status"] == "disproved" and item["counterexample_found"]
           for item in negative["findings"])
assert {"star_count", "needs_void_parameter_marker", "matches_marker"} <= {
    item["name"] for item in negative["declaration_details"] if item.get("verified")
}
assert require_current_product(BIN, PROVER) == product
if hashes_before != {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}:
    raise SystemExit("C header parameter proof inputs changed during replay")

print(json.dumps({
    "admitted": True,
    "scope": "C exported-function declarators and annotation-selected return pointers at the source-to-header ABI boundary",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(negative_shapes),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": compiler.get("source_revision"),
    "inputs_sha256": hashes_before,
}, sort_keys=True))
