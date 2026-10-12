"""Admit source-pinned proofs of the type tables used by Python bindings."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve(strict=True)
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
DRIVER = ROOT / "src/driver/elisac.elisa"
MODULE = ROOT / "src/driver/pymodule_type_classification.elisa"
LOOKUP = ROOT / "src/driver/elisac_pymodule_lookup.elisa"
REPORT = ROOT / "src/driver/elisac_pymodule_report.elisa"
POSITIVE = HERE / "pymodule_type_classification.elisa"
NEGATIVE = HERE / "pymodule_type_classification_rejected.elisa"
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")


SCALAR_GROUPS = (
    (("i8", "i16", "i32", "i64", "int", "isize", "char"), "true"),
    (("u8", "u16", "u32", "u64", "usize", "uintptr"), "true"),
    (("f32", "f64", "bool", "cstr", "sview", "py::Object"), "true"),
    (("cstr?", "py::Object?"), "true"),
    (("i8?", "i16?", "i32?", "i64?", "int?", "isize?", "char?"), "true"),
    (("u8?", "u16?", "u32?", "u64?", "usize?", "uintptr?"), "true"),
    (("bool?", "f32?", "f64?", "sview?"), "true"),
    (("_",), "false"),
)
EXPECTED_TYPE_GROUPS = (
    (("py::Object",), '"object"'),
    (("py::Object?",), '"object | None"'),
    (("cstr", "sview"), '"str | bytes"'),
    (("cstr?", "sview?"), '"str | bytes | None"'),
    (("bool",), '"bool"'),
    (("f32", "f64"), '"float"'),
    (("i8", "i16", "i32", "i64", "int", "isize", "char", "u8", "u16", "u32", "u64", "usize", "uintptr"), '"int"'),
    (("_",), '""'),
)
EXPECTED_POSITIVE = {
    "scalar_field_membership_matches_the_closed_source_table",
    "python_expected_type_matches_the_closed_source_table",
    "nearby_named_types_stay_outside_the_scalar_set",
    "unsupported_type_names_have_no_static_python_expectation",
}
EXPECTED_NEGATIVE = {
    "nearby_type_must_not_be_scalar",
    "integer_type_must_not_map_to_float",
    "unknown_type_must_not_get_sequence_label",
}


def compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def function_source(text: str, name: str) -> str:
    match = re.search(rf"(?m)^\s*def\s+{re.escape(name)}(?=\[|\()", text)
    if not match:
        raise SystemExit(f"missing source or proof function: {name}")
    tail = text[match.end():]
    following = re.search(r"(?m)^\s*(?:def\s+|public:|private:|module\s+|extend\s+)", tail)
    end = match.end() + following.start() if following else len(text)
    return text[match.start():end]


def parse_match_arms(block: str, description: str):
    actual = []
    for raw in block.splitlines():
        arm = raw.strip()
        if not arm:
            continue
        match = re.fullmatch(
            r'((?:"(?:\\.|[^"\\])*"|_)(?:\s*\|\s*"(?:\\.|[^"\\])*")*)\s*->\s*(true|false|"(?:\\.|[^"\\])*")',
            arm,
        )
        if not match:
            raise SystemExit(f"unexpected {description} arm: {arm}")
        pattern = tuple(re.findall(r'"((?:\\.|[^"\\])*)"|(_)', match.group(1)))
        names = tuple(literal if literal else "_" for literal, wildcard in pattern)
        actual.append((names, match.group(2)))
    return tuple(actual)


def match_blocks(function: str, description: str, require_contract: bool = True):
    spec = re.search(
        r"ensure\s+result\s*==\s*\(\s*when\s+type_name:\s*\n(.*?)^\s*\)",
        function,
        re.DOTALL | re.MULTILINE,
    )
    implementation = re.search(
        r"return\s+when\s+type_name:\s*\n(.*)", function, re.DOTALL
    )
    if not implementation or (require_contract and not spec):
        raise SystemExit(f"{description} is missing a required match contract or implementation")
    spec_arms = parse_match_arms(spec.group(1), f"{description} contract") if spec else None
    return spec_arms, parse_match_arms(implementation.group(1), f"{description} implementation")


def validate_source(module_text: str, lookup_text: str, report_text: str, driver_text: str):
    errors = []
    scalar = function_source(module_text, "is_scalar_field_type")
    scalar_spec, scalar_impl = match_blocks(scalar, "scalar-field classifier")
    if scalar_spec != SCALAR_GROUPS or scalar_impl != SCALAR_GROUPS:
        errors.append("scalar-field classifier differs from its exact closed name set")

    expected = function_source(module_text, "known_python_expected_type")
    expected_spec, expected_impl = match_blocks(
        expected, "Python expected-type classifier", require_contract=False
    )
    if expected_spec is not None or expected_impl != EXPECTED_TYPE_GROUPS:
        errors.append("Python expected-type classifier differs from its exact closed mapping")

    if compact(driver_text).count('include"./pymodule_type_classification.elisa"') != 1:
        errors.append("compiler driver must include the shared type classifier exactly once")

    lookup = compact(function_source(lookup_text, "pymodule_struct_scalar_field_type"))
    expected_lookup = compact(
        "def pymodule_struct_scalar_field_type(type_name: sview) -> bool can[Abort.Panic]:\n"
        "    ensure result == PymoduleTypeClassification::is_scalar_field_type(type_name)\n"
        "    can Abort.Panic:\n"
        "        return PymoduleTypeClassification::is_scalar_field_type(type_name)"
    )
    if lookup != expected_lookup:
        errors.append("production struct-scalar predicate no longer forwards exactly to the proved table")

    report_fn = compact(function_source(report_text, "pymodule_python_expected_type"))
    expected_fragments = (
        "known_expected_type:sview=PymoduleTypeClassification::known_python_expected_type(type_name)",
        'returnknown_expected_typeifknown_expected_type!=""',
        "ifpymodule_is_optional_scalar_type(type_name):",
        "ifpymodule_is_dict_type(type_name):",
        "ifpymodule_is_set_type(type_name):",
        "ifpymodule_is_darray_type(type_name)orpymodule_is_view_type(type_name)orpymodule_is_fixed_array_type(type_name):",
    )
    positions = [report_fn.find(fragment) for fragment in expected_fragments]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        errors.append("Python report classifier must preserve dynamic optional/container fallbacks after the static table")

    return errors


module_text = MODULE.read_text()
lookup_text = LOOKUP.read_text()
report_text = REPORT.read_text()
driver_text = DRIVER.read_text()
source_errors = validate_source(module_text, lookup_text, report_text, driver_text)
if source_errors:
    raise SystemExit("\n".join(source_errors))

# The source checks must reject both a widened name set and a changed result label.
mutated_scalar = module_text.replace('"i8" | "i16"', '"i8" | "i80"', 1)
if mutated_scalar == module_text or not validate_source(mutated_scalar, lookup_text, report_text, driver_text):
    raise SystemExit("checker failed to catch an injected scalar type spelling")
mutated_label = module_text.replace('"py::Object" -> "object"', '"py::Object" -> "value"', 1)
if mutated_label == module_text or not validate_source(mutated_label, lookup_text, report_text, driver_text):
    raise SystemExit("checker failed to catch a changed Python expectation label")

positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()
if 'include "../../src/driver/pymodule_type_classification.elisa"' not in positive_text:
    raise SystemExit("positive proof no longer imports the production type tables")
if 'include "./pymodule_type_classification.elisa"' not in negative_text:
    raise SystemExit("negative controls no longer share the source-linked positive proof")
positive_names = set(re.findall(r"(?m)^def\s+(\w+)\s*\(", positive_text))
negative_names = set(re.findall(r"(?m)^def\s+(\w+)\s*\(", negative_text))
if positive_names != EXPECTED_POSITIVE:
    raise SystemExit(f"positive theorem inventory changed: {sorted(positive_names)}")
if negative_names != EXPECTED_NEGATIVE:
    raise SystemExit(f"false-control inventory changed: {sorted(negative_names)}")
for name in EXPECTED_POSITIVE:
    body = compact(function_source(positive_text, name))
    if "PymoduleTypeClassification::is_scalar_field_type(" not in body and "PymoduleTypeClassification::known_python_expected_type(" not in body:
        raise SystemExit(f"positive theorem {name} no longer exercises a production classifier")
for name in EXPECTED_NEGATIVE:
    body = compact(function_source(negative_text, name))
    if "PymoduleTypeClassification::is_scalar_field_type(" not in body and "PymoduleTypeClassification::known_python_expected_type(" not in body:
        raise SystemExit(f"false control {name} no longer exercises a production classifier")

scalar_theorem = function_source(positive_text, "scalar_field_membership_matches_the_closed_source_table")
scalar_expected = re.search(
    r"expected\s*:\s*bool\s*=\s*when\s+type_name:\s*\n(.*?)(?=^\s*return\b)",
    scalar_theorem,
    re.DOTALL | re.MULTILINE,
)
if not scalar_expected or parse_match_arms(scalar_expected.group(1), "scalar proof table") != SCALAR_GROUPS:
    raise SystemExit("scalar positive theorem no longer states the exact production match table")
if compact(scalar_theorem).count("returnPymoduleTypeClassification::is_scalar_field_type(type_name)==expected") != 1:
    raise SystemExit("scalar positive theorem no longer compares the production result to its closed table")

python_type_theorem = function_source(positive_text, "python_expected_type_matches_the_closed_source_table")
python_expected = re.search(
    r"expected\s*:\s*sview\s*=\s*when\s+type_name:\s*\n(.*?)(?=^\s*return\b)",
    python_type_theorem,
    re.DOTALL | re.MULTILINE,
)
if not python_expected or parse_match_arms(python_expected.group(1), "Python expectation proof table") != EXPECTED_TYPE_GROUPS:
    raise SystemExit("Python expectation theorem no longer states the exact production match table")
if compact(python_type_theorem).count("returnPymoduleTypeClassification::known_python_expected_type(type_name)==expected") != 1:
    raise SystemExit("Python expectation theorem no longer compares the production result to its closed table")

expected_proof_returns = {
    "nearby_named_types_stay_outside_the_scalar_set": "return(notPymoduleTypeClassification::is_scalar_field_type(\"String\")andnotPymoduleTypeClassification::is_scalar_field_type(\"u128\")andnotPymoduleTypeClassification::is_scalar_field_type(\"sview??\"))",
    "unsupported_type_names_have_no_static_python_expectation": "return(PymoduleTypeClassification::known_python_expected_type(\"Widget\")==\"\"andPymoduleTypeClassification::known_python_expected_type(\"darray[i64]\")==\"\"andPymoduleTypeClassification::known_python_expected_type(\"i128\")==\"\")",
    "nearby_type_must_not_be_scalar": "returnPymoduleTypeClassification::is_scalar_field_type(\"String\")",
    "integer_type_must_not_map_to_float": "returnPymoduleTypeClassification::known_python_expected_type(\"i8\")==\"float\"",
    "unknown_type_must_not_get_sequence_label": "returnPymoduleTypeClassification::known_python_expected_type(\"Widget\")==\"sequence\"",
}
for name, expected_return in expected_proof_returns.items():
    proof_source = positive_text if name in EXPECTED_POSITIVE else negative_text
    if compact(function_source(proof_source, name)).count(expected_return) != 1:
        raise SystemExit(f"proof/control {name} no longer states its exact claim")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("PyModule type-classification proof requires a strict proof build")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
source_closure = source_include_closure([POSITIVE, NEGATIVE])
inputs = [
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV",
    stage1_product, stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
    MODULE, LOOKUP, REPORT, DRIVER, *source_closure,
]
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=60)
    proof_report = json.loads(process.stdout)
    assert proof_report["summary"]["semantic_errors"] == 0, proof_report.get("semantic_diagnostics")
    assert not proof_report["trust"]["trusted_assumptions"]
    assert proof_report["replay"]["gaps"] == 0
    assert proof_report["replay"]["certificates"] == proof_report["replay"]["replayed"] == proof_report["summary"]["proven"]
    return process.returncode, proof_report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "PyModule type-table proof changed across repeated runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert EXPECTED_POSITIVE <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert {row["name"] for row in negative["findings"]} == EXPECTED_NEGATIVE
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert require_current_product(BIN, PROVER) == manifest, "proof product changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "exact 38-name scalar set and fixed Python error expectation mapping",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(EXPECTED_NEGATIVE),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
