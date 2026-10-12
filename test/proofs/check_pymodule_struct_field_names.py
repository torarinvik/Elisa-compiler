"""Admit source-pinned proofs of generated C field identifier mapping."""
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
POSITIVE = HERE / "pymodule_struct_field_names.elisa"
NEGATIVE = HERE / "pymodule_struct_field_names_rejected.elisa"
HELPER = ROOT / "src/driver/pymodule_struct_field_names.elisa"
WRAPPER = ROOT / "src/driver/elisac_pymodule_struct_fields.elisa"
TYPEDEF = ROOT / "src/driver/elisac_pymodule_struct_typedef.elisa"
DEFAULT_POLICY = ROOT / "src/driver/elisac_pymodule_default_policy.elisa"
DRIVER = ROOT / "src/driver/elisac.elisa"
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")

if not __debug__:
    raise SystemExit("run without Python -O")

EXPECTED = (
    ('auto', 'elisa_pymodule_field_auto'),
    ('break', 'elisa_pymodule_field_break'),
    ('case', 'elisa_pymodule_field_case'),
    ('char', 'elisa_pymodule_field_char'),
    ('const', 'elisa_pymodule_field_const'),
    ('continue', 'elisa_pymodule_field_continue'),
    ('default', 'elisa_pymodule_field_default'),
    ('do', 'elisa_pymodule_field_do'),
    ('double', 'elisa_pymodule_field_double'),
    ('else', 'elisa_pymodule_field_else'),
    ('enum', 'elisa_pymodule_field_enum'),
    ('extern', 'elisa_pymodule_field_extern'),
    ('float', 'elisa_pymodule_field_float'),
    ('for', 'elisa_pymodule_field_for'),
    ('goto', 'elisa_pymodule_field_goto'),
    ('if', 'elisa_pymodule_field_if'),
    ('inline', 'elisa_pymodule_field_inline'),
    ('int', 'elisa_pymodule_field_int'),
    ('long', 'elisa_pymodule_field_long'),
    ('register', 'elisa_pymodule_field_register'),
    ('restrict', 'elisa_pymodule_field_restrict'),
    ('return', 'elisa_pymodule_field_return'),
    ('short', 'elisa_pymodule_field_short'),
    ('signed', 'elisa_pymodule_field_signed'),
    ('sizeof', 'elisa_pymodule_field_sizeof'),
    ('static', 'elisa_pymodule_field_static'),
    ('struct', 'elisa_pymodule_field_struct'),
    ('switch', 'elisa_pymodule_field_switch'),
    ('typedef', 'elisa_pymodule_field_typedef'),
    ('union', 'elisa_pymodule_field_union'),
    ('unsigned', 'elisa_pymodule_field_unsigned'),
    ('void', 'elisa_pymodule_field_void'),
    ('volatile', 'elisa_pymodule_field_volatile'),
    ('while', 'elisa_pymodule_field_while'),
    ('bool', 'elisa_pymodule_field_bool'),
    ('true', 'elisa_pymodule_field_true'),
    ('false', 'elisa_pymodule_field_false'),
    ('nullptr', 'elisa_pymodule_field_nullptr'),
    ('_Alignas', 'elisa_pymodule_field_Alignas'),
    ('_Alignof', 'elisa_pymodule_field_Alignof'),
    ('_Atomic', 'elisa_pymodule_field_Atomic'),
    ('_Bool', 'elisa_pymodule_field_Bool'),
    ('_Complex', 'elisa_pymodule_field_Complex'),
    ('_Generic', 'elisa_pymodule_field_Generic'),
    ('_Imaginary', 'elisa_pymodule_field_Imaginary'),
    ('_Noreturn', 'elisa_pymodule_field_Noreturn'),
    ('_Static_assert', 'elisa_pymodule_field_Static_assert'),
    ('_Thread_local', 'elisa_pymodule_field_Thread_local'),
    ('asm', 'elisa_pymodule_field_asm'),
    ('typeof', 'elisa_pymodule_field_typeof'),
    ('typeof_unqual', 'elisa_pymodule_field_typeof_unqual'),
)

def compact_source(text):
    tokens = re.findall(r'"(?:\\.|[^"\\])*"|#[^\r\n]*|\S', text)
    return "".join(token for token in tokens if not token.startswith("#"))

def source_function(text, name):
    match = re.search(rf"(?m)^\s*def\s+{re.escape(name)}(?=\[|\()", text)
    if not match:
        raise SystemExit(f"missing production function: {name}")
    tail = text[match.end():]
    following = re.search(r"(?m)^\s*(?:def\s+|public:|private:)", tail)
    end = match.end() + following.start() if following else len(text)
    return text[match.start():end]

def parse_match(block, label):
    actual = []
    fallback = 0
    for raw in block.splitlines():
        arm = raw.strip()
        if not arm:
            continue
        if arm == "_ -> field_name":
            fallback += 1
            continue
        match = re.fullmatch(r'"((?:\\.|[^"\\])*)"\s*->\s*"((?:\\.|[^"\\])*)"', arm)
        if not match:
            raise SystemExit(f"non-literal or unexpected {label} arm: {arm}")
        actual.append((match.group(1), match.group(2)))
    if fallback != 1:
        raise SystemExit(f"{label} must have exactly one pass-through fallback")
    return tuple(actual)


def expected_match_arms():
    rows = [f'"{source_name}" -> "{c_name}"' for source_name, c_name in EXPECTED]
    rows.append("_ -> field_name")
    return "\n".join(rows)


def expected_mapping_function(name, postcondition=""):
    return compact_source(
        f"def {name}(field_name: sview) -> sview:\n"
        + postcondition
        + "can Abort.Panic:\n"
        + "    return when field_name:\n"
        + "\n".join("        " + arm for arm in expected_match_arms().splitlines())
    )


source = HELPER.read_text()
function = source_function(source, "c_field_name")
expected_function = source_function(source, "c_field_name_expected")
expected_public = compact_source("""def c_field_name(field_name: sview) -> sview:
    ensure result == c_field_name_expected(field_name)
    can Abort.Panic:
        return when field_name:
            EXPECTED_MATCH_ARMS""".replace("EXPECTED_MATCH_ARMS", expected_match_arms()))
if compact_source(expected_function) != expected_mapping_function("c_field_name_expected"):
    raise SystemExit("C field expected-name helper changed from the exact closed match body")
if compact_source(function) != expected_public:
    raise SystemExit("C field mapper changed from the exact expected-name contract and match body")
expected_implementation = re.search(
    r"return\s+when\s+field_name:\s*\n(.*?)(?=^\s*(?:public:|private:|def\s)|\Z)",
    expected_function,
    re.DOTALL | re.MULTILINE,
)
implementation = re.search(r"return\s+when\s+field_name:\s*\n(.*)", function, re.DOTALL)
if not expected_implementation or not implementation:
    raise SystemExit("C field mapper lost a pattern-matching implementation")
if parse_match(expected_implementation.group(1), "expected-name mapping") != EXPECTED:
    raise SystemExit("C field expected-name mapping differs from the closed expected keyword map")
if parse_match(implementation.group(1), "implementation") != EXPECTED:
    raise SystemExit("C field implementation differs from the closed expected keyword map")

wrapper_source = WRAPPER.read_text()
if 'include "./pymodule_struct_field_names.elisa"' not in wrapper_source:
    raise SystemExit("production struct-field adapter no longer imports the proved mapper")
wrapper = compact_source(source_function(wrapper_source, "pymodule_struct_c_field_name"))
expected_wrapper = compact_source("""def pymodule_struct_c_field_name(field_name: sview) -> sview can[Abort.Panic]:
    ensure result == PymoduleStructFieldNames::c_field_name(field_name)
    can Abort.Panic:
        return PymoduleStructFieldNames::c_field_name(field_name)""")
if wrapper != expected_wrapper:
    raise SystemExit("production struct-field adapter changed from the exact proved forwarding body")
if compact_source(DRIVER.read_text()).count('include"./elisac_pymodule_struct_fields.elisa"') != 1:
    raise SystemExit("main compiler driver no longer includes the struct-field adapter exactly once")
for path, expected_calls in ((TYPEDEF, 8), (DEFAULT_POLICY, 2)):
    calls = compact_source(path.read_text()).count("pymodule_struct_c_field_name(")
    if calls != expected_calls:
        raise SystemExit(f"{path.name} changed the proved C field-name mapping call-site inventory")

compact_proof = compact_source(POSITIVE.read_text())
for source_name, c_name in EXPECTED:
    anchor = f'PymoduleStructFieldNames::c_field_name("{source_name}")=="{c_name}"'
    if anchor not in compact_proof:
        raise SystemExit(f"positive proof omits source mapping {source_name!r}")
proof_theorem = source_function(
    POSITIVE.read_text(), "every_field_name_uses_the_exact_closed_mapping")
expected_universal_theorem = compact_source(
    "def every_field_name_uses_the_exact_closed_mapping(field_name: sview) -> bool can[Abort.Panic]:\n"
    "    ensure result == true\n"
    "    can Abort.Panic:\n"
    "        expected_name: sview = when field_name:\n"
    + "\n".join("            " + arm for arm in expected_match_arms().splitlines())
    + "\n        return PymoduleStructFieldNames::c_field_name(field_name) == expected_name")
if compact_source(proof_theorem) != expected_universal_theorem:
    raise SystemExit("universal proof no longer states the exact closed C field-name map")
positive_names = set(re.findall(r"(?m)^def\s+(\w+)\s*\(", POSITIVE.read_text()))
negative_names = set(re.findall(r"(?m)^def\s+(\w+)\s*\(", NEGATIVE.read_text()))
expected_positive = {'reserved_field_names_are_mangled_group_3', 'reserved_field_names_are_mangled_group_2', 'reserved_field_names_are_mangled_group_1', 'ordinary_field_names_are_preserved', 'every_field_name_uses_the_exact_closed_mapping'}
expected_negative = {"c_keyword_must_not_keep_its_source_spelling", "ordinary_name_must_not_be_mangled"}
if positive_names != expected_positive or negative_names != expected_negative:
    raise SystemExit("C field-name proof declaration inventory changed")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("C field-name proof requires a strict proof build")
stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
source_closure = source_include_closure([POSITIVE, NEGATIVE])
inputs = [BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV", stage1_product,
          stage1_provenance, Path(__file__), HERE / "proof_product_gate.py", *source_closure,
          WRAPPER, TYPEDEF, DEFAULT_POLICY, DRIVER]
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}

def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True, text=True, timeout=60)
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
assert expected_positive <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert {row["name"] for row in negative["findings"]} == expected_negative
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert require_current_product(BIN, PROVER) == manifest, "proof product changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": f"{len(EXPECTED)} reserved C field spellings and pass-through behavior",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(expected_negative),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
