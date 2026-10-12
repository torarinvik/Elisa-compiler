"""Admit source-linked proofs for Python error helper suffix classification."""
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
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
POSITIVE = HERE / "pymodule_error_helper_names.elisa"
NEGATIVE = HERE / "pymodule_error_helper_names_rejected.elisa"
CLASSIFIER = ROOT / "src/driver/pymodule_error_helper_names.elisa"
PAYLOAD = ROOT / "src/driver/elisac_pymodule_error_payload.elisa"
CONVERT = ROOT / "src/driver/elisac_pymodule_error_convert.elisa"
HELPERS = ROOT / "src/driver/elisac_pymodule_error_helpers.elisa"
DRIVER = ROOT / "src/driver/elisac.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")

EXPECTED = [
    ("i8", "i8"), ("i16", "i16"), ("i32", "i32"), ("i64", "i64"),
    ("int", "int"), ("isize", "isize"), ("char", "char"), ("u8", "u8"),
    ("u16", "u16"), ("u32", "u32"), ("u64", "u64"), ("usize", "usize"),
    ("uintptr", "uintptr"), ("f32", "f32"), ("f64", "f64"), ("bool", "bool"),
    ("cstr", "cstr"), ("cstr?", "cstr_optional"), ("sview", "sview"),
    ("sview?", "sview_optional"), ("py::Object", "object"),
    ("py::Object?", "object_optional"), ("i8?", "i8_optional"),
    ("i16?", "i16_optional"), ("i32?", "i32_optional"),
    ("i64?", "i64_optional"), ("int?", "int_optional"),
    ("isize?", "isize_optional"), ("char?", "char_optional"),
    ("u8?", "u8_optional"), ("u16?", "u16_optional"),
    ("u32?", "u32_optional"), ("u64?", "u64_optional"),
    ("usize?", "usize_optional"), ("uintptr?", "uintptr_optional"),
    ("bool?", "bool_optional"), ("f32?", "f32_optional"),
    ("f64?", "f64_optional"),
]


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


def function_section(source: str, name: str) -> str:
    match = re.search(rf"(?m)^[ \t]*def {re.escape(name)}\(", source)
    if match is None:
        raise SystemExit(f"missing source function {name}")
    following = re.search(r"(?m)^[ \t]*def [A-Za-z_][A-Za-z0-9_]*\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


classifier_text = CLASSIFIER.read_text()
classifier = function_section(classifier_text, "nested_darray_helper_suffix")
dispatch = re.search(r"return when element_name:\s*\n(.*)", classifier, re.DOTALL)
if dispatch is None:
    raise SystemExit("nested helper suffix classifier lost its exhaustive match")
arm_lines = [line.strip() for line in dispatch.group(1).splitlines() if line.strip()]
expected_arms = [f'"{name}" -> "{suffix}"' for name, suffix in EXPECTED] + ['_ -> ""']
if arm_lines != expected_arms:
    raise SystemExit("classifier match no longer implements the complete closed suffix table")

payload_text = PAYLOAD.read_text()
if 'include "./pymodule_error_helper_names.elisa"' not in payload_text:
    raise SystemExit("error payload builder no longer imports the proved suffix classifier")
helper_name = function_section(payload_text, "pymodule_error_nested_darray_helper_name")
if "return PymoduleErrorHelperNames::nested_darray_helper_suffix(element_name)" not in helper_name:
    raise SystemExit("nested error helper name no longer delegates to the proved classifier")
if "pymodule_error_nested_darray_helper_suffix(type_name, &helper_suffix_storage)" not in CONVERT.read_text():
    raise SystemExit("error conversion no longer uses the helper suffix path")
helpers_text = HELPERS.read_text()
if not all(fragment in helpers_text for fragment in (
    'emit_tokens_push_sview(&helper_name_storage, "elisa_pymodule_error_nested_")',
    "emit_tokens_push_sview(&helper_name_storage, helper_suffix)",
    'emit_tokens_push_sview(&helper_name_storage, "_to_py")',
)):
    raise SystemExit("nested error helper emitter no longer consumes classified suffixes")
if 'include "./elisac_pymodule_error_payload.elisa"' not in DRIVER.read_text():
    raise SystemExit("compiler driver no longer includes the nested error payload implementation")

positive_names = {
    "signed_integer_names_preserve_helper_suffix",
    "char_unsigned_float_bool_names_preserve_helper_suffix",
    "text_and_python_object_names_have_explicit_suffixes",
    "optional_primitive_names_have_optional_suffixes",
    "unsupported_leaf_names_fail_closed",
}
negative_names = {
    "optional_text_name_must_not_keep_its_source_spelling",
    "unsupported_type_must_not_receive_a_helper",
    "i64_must_not_map_to_optional_helper",
    "unknown_integer_width_must_not_be_accepted",
}
if declarations(POSITIVE) != positive_names:
    raise SystemExit("positive suffix proof inventory changed")
if declarations(NEGATIVE) != negative_names:
    raise SystemExit("rejected suffix proof inventory changed")
positive_text = POSITIVE.read_text()
proved_pairs = set(re.findall(
    r'PymoduleErrorHelperNames::nested_darray_helper_suffix\("([^"\\]+)"\)\s*==\s*"([^"\\]+)"',
    positive_text,
))
if proved_pairs != set(EXPECTED):
    raise SystemExit("positive proof no longer covers every accepted classifier mapping exactly")
unsupported_names = set(re.findall(
    r'PymoduleErrorHelperNames::nested_darray_helper_suffix\("([^"\\]*)"\)\s*==\s*""',
    positive_text,
))
if unsupported_names != {
    "", "i128", "u128", "String", "cstr??", "py::Object??", "u128?", "Object", "darray[i64]",
}:
    raise SystemExit("positive proof no longer covers the fail-closed unsupported leaf cases")
negative_text = NEGATIVE.read_text()
rejected_claims = set(re.findall(
    r'PymoduleErrorHelperNames::nested_darray_helper_suffix\("([^"\\]+)"\)\s*==\s*"([^"\\]+)"',
    negative_text,
))
if rejected_claims != {
    ("cstr?", "cstr?"), ("i64", "i64_optional"), ("i128", "i128"),
}:
    raise SystemExit("rejected proof no longer challenges the expected wrong mappings")
if 'PymoduleErrorHelperNames::nested_darray_helper_suffix("String") != ""' not in negative_text:
    raise SystemExit("rejected proof no longer challenges unsupported type acceptance")
for path in (POSITIVE, NEGATIVE):
    if 'include "../../src/driver/pymodule_error_helper_names.elisa"' not in path.read_text():
        raise SystemExit(f"{path.name} no longer proves the production classifier directly")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("nested error helper suffix proof requires a strict proof build")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
source_closure = source_include_closure([POSITIVE, NEGATIVE, PAYLOAD, CONVERT, HELPERS])
inputs = [
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV",
    stage1_product, stage1_provenance, Path(__file__), HERE / "proof_product_gate.py", DRIVER,
    *source_closure,
]
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=90)
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
assert positive == run(POSITIVE)[1], "suffix proof report changed across replay"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert positive_names <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert require_current_product(BIN, PROVER) == manifest, "proof product changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "all closed leaf-type to nested Python error-helper suffix mappings",
    "mapping_cases": len(EXPECTED),
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(negative_names),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
