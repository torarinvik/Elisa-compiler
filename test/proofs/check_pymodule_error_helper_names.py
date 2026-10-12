"""Admit source-linked proofs of nested Python error-payload helper naming."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve(strict=True)
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
POSITIVE = HERE / "pymodule_error_helper_names.elisa"
NEGATIVE = HERE / "pymodule_error_helper_names_rejected.elisa"
HELPER = ROOT / "src/driver/pymodule_error_helper_names.elisa"
DRIVER = ROOT / "src/driver/elisac_pymodule_error_payload.elisa"
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")


if not __debug__:
    raise SystemExit("run without Python -O")

EXPECTED = (
    ("i8", "i8"), ("i16", "i16"), ("i32", "i32"), ("i64", "i64"),
    ("int", "int"), ("isize", "isize"), ("char", "char"),
    ("u8", "u8"), ("u16", "u16"), ("u32", "u32"), ("u64", "u64"),
    ("usize", "usize"), ("uintptr", "uintptr"), ("f32", "f32"),
    ("f64", "f64"), ("bool", "bool"), ("cstr", "cstr"),
    ("cstr?", "cstr_optional"), ("sview", "sview"),
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
)


def compact_source(text):
    # Preserve spaces in string literals while ignoring comments and layout.
    tokens = re.findall(r'"(?:\\.|[^"\\])*"|#[^\r\n]*|\S', text)
    return "".join(token for token in tokens if not token.startswith("#"))


source = HELPER.read_text()
dispatch = re.search(
    r"(?m)^\s*def nested_darray_helper_suffix\([^\n]*\n(.*?return when element_name:\s*\n)(.*?)^\s*_\s*->\s*\"\"\s*$",
    source,
    re.DOTALL | re.MULTILINE,
)
if not dispatch:
    raise SystemExit("production helper-name match or empty fallback is missing")
actual = []
for line in dispatch.group(2).splitlines():
    arm = line.strip()
    if not arm:
        continue
    match = re.fullmatch(r'"((?:\\.|[^"\\])*)"\s*->\s*"((?:\\.|[^"\\])*)"', arm)
    if not match:
        raise SystemExit(f"non-literal arm in helper-name match: {arm}")
    actual.append((match.group(1), match.group(2)))
if tuple(actual) != EXPECTED:
    raise SystemExit("production helper-name match differs from the closed supported mapping")

compact_driver = compact_source(DRIVER.read_text())
if 'include"./pymodule_error_helper_names.elisa"' not in compact_driver:
    raise SystemExit("Python error-payload driver no longer imports the proved helper table")
if "returnPymoduleErrorHelperNames::nested_darray_helper_suffix(element_name)" not in compact_driver:
    raise SystemExit("Python error-payload adapter no longer delegates to the proved helper table")
compact_proof = compact_source(POSITIVE.read_text())
for source_name, helper_suffix in EXPECTED:
    anchor = f'PymoduleErrorHelperNames::nested_darray_helper_suffix("{source_name}")=="{helper_suffix}"'
    if anchor not in compact_proof:
        raise SystemExit(f"proof does not cover production helper mapping: {source_name!r}")

positive_names = {
    "every_nonoptional_helper_name_is_preserved",
    "optional_and_object_helper_names_are_distinct",
    "nearby_unhandled_names_have_no_helper",
}
negative_names = {
    "optional_text_name_must_not_keep_its_source_spelling",
    "unsupported_type_must_not_receive_a_helper",
}
for path, expected_names in ((POSITIVE, positive_names), (NEGATIVE, negative_names)):
    found = set(re.findall(r"(?m)^def\s+(\w+)\s*\(", path.read_text()))
    if found != expected_names:
        raise SystemExit(f"{path.name} proof declaration inventory differs: {sorted(found)}")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("Python error-helper-name proof requires a strict proof build")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
source_closure = source_include_closure([POSITIVE, NEGATIVE])
inputs = [
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV",
    stage1_product, stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
    *source_closure, DRIVER,
]
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
assert positive == run(POSITIVE)[1], "helper-name proof report changed across repeats"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert positive_names <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert require_current_product(BIN, PROVER) == manifest, "proof product changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "all 38 source spellings mapped to nested Python error-payload helper suffixes",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(negative_names),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
