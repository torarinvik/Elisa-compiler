"""Admit source-linked proofs of PyModule default scalar type-name groups."""
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
POSITIVE = HERE / "pymodule_default_scalar_type_policy.elisa"
NEGATIVE = HERE / "pymodule_default_scalar_type_policy_rejected.elisa"
POLICY = ROOT / "src/driver/elisac_pymodule_default_scalar_type_policy.elisa"
DEFAULT_POLICY = ROOT / "src/driver/elisac_pymodule_default_policy.elisa"
DRIVER = ROOT / "src/driver/elisac.elisa"
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")

groups = {
    "is_text_type_name": ["cstr", "sview"],
    "is_float_type_name": ["f32", "f64"],
    "is_signed_integer_type_name": ["i8", "i16", "i32", "i64", "int", "isize", "char"],
    "is_unsigned_integer_type_name": ["u8", "u16", "u32", "u64", "usize", "uintptr"],
}


def function_section(text, name):
    match = re.search(
        rf"(?m)^[ \t]*def {re.escape(name)}\([^\n]*\)[^\n]*:[ \t]*\n(.*?)(?=^[ \t]*def |\Z)",
        text,
        re.DOTALL,
    )
    if not match:
        raise SystemExit(f"source policy is missing {name}")
    return match.group(1)


def compact(text):
    return "".join("".join(line.split("#", 1)[0].split()) for line in text.splitlines())


policy_text = POLICY.read_text()
default_policy_text = DEFAULT_POLICY.read_text()
driver_text = DRIVER.read_text()
proof_text = POSITIVE.read_text()
if 'include "./elisac_pymodule_default_scalar_type_policy.elisa"' not in driver_text:
    raise SystemExit("PyModule driver no longer includes the scalar type-name policy")
if 'include "../../src/driver/elisac_pymodule_default_hashable_policy.elisa"' not in proof_text:
    raise SystemExit("the scalar group partition proof no longer includes the hashable-type policy")
for name, expected_names in groups.items():
    section = function_section(policy_text, name)
    contract = re.search(r"(?m)^\s*ensure result == \(when type_name:\s*\n(.*?)^\s*\)", section, re.DOTALL)
    implementation = re.search(r"(?m)^\s*return match type_name:\s*\n(.*)", section, re.DOTALL)
    if not contract or not implementation:
        raise SystemExit(f"{name} must have both a match contract and a match implementation")
    for description, body, arrow in (
        ("contract", contract.group(1), "->"),
        ("implementation", implementation.group(1), ":"),
    ):
        arms = []
        for line in body.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            match = re.fullmatch(
                r'("[^"\\]+"(?:\s*\|\s*"[^"\\]+")*|_)\s*'
                + re.escape(arrow)
                + r'\s*(true|false)',
                stripped,
            )
            if not match:
                raise SystemExit(f"{name} has a malformed {description} arm")
            arms.append(match.groups())
        if not arms or arms[-1] != ("_", "false"):
            raise SystemExit(f"{name} lost its false fallback")
        found = []
        for pattern, result in arms[:-1]:
            if result != "true":
                raise SystemExit(f"{name} has a non-true allowlist arm")
            found.extend(re.findall(r'"([^"\\]+)"', pattern))
        if found != expected_names:
            raise SystemExit(f"{name} differs from its expected closed type set")

for helper in groups:
    if f"PymoduleDefaultScalarTypePolicy::{helper}(type_name)" not in default_policy_text:
        raise SystemExit(f"PyModule default checking no longer uses {helper}")
if "PymoduleDefaultScalarTypePolicy::is_float_type_name(scalar_type_name)" not in default_policy_text:
    raise SystemExit("PyModule default scalar emission no longer uses the float classifier")
if "PymoduleDefaultScalarTypePolicy::is_unsigned_integer_type_name(scalar_type_name)" not in default_policy_text:
    raise SystemExit("PyModule default scalar emission no longer uses the unsigned classifier")
if "PymoduleDefaultScalarTypePolicy::is_text_type_name(scalar_type_name)" not in default_policy_text:
    raise SystemExit("PyModule default scalar emission no longer uses the text classifier")

expected_proofs = {
    "scalar_type_groups_are_pairwise_disjoint": """
        ensure result == true
        return (
            not (PymoduleDefaultScalarTypePolicy::is_text_type_name(type_name) and PymoduleDefaultScalarTypePolicy::is_float_type_name(type_name))
            and not (PymoduleDefaultScalarTypePolicy::is_text_type_name(type_name) and PymoduleDefaultScalarTypePolicy::is_signed_integer_type_name(type_name))
            and not (PymoduleDefaultScalarTypePolicy::is_text_type_name(type_name) and PymoduleDefaultScalarTypePolicy::is_unsigned_integer_type_name(type_name))
            and not (PymoduleDefaultScalarTypePolicy::is_float_type_name(type_name) and PymoduleDefaultScalarTypePolicy::is_signed_integer_type_name(type_name))
            and not (PymoduleDefaultScalarTypePolicy::is_float_type_name(type_name) and PymoduleDefaultScalarTypePolicy::is_unsigned_integer_type_name(type_name))
            and not (PymoduleDefaultScalarTypePolicy::is_signed_integer_type_name(type_name) and PymoduleDefaultScalarTypePolicy::is_unsigned_integer_type_name(type_name))
        )
    """,
    "scalar_type_groups_plus_bool_equal_hashable_policy": """
        ensure result == true
        can Abort.Panic:
            return (
                (
                    PymoduleDefaultScalarTypePolicy::is_text_type_name(type_name)
                    or PymoduleDefaultScalarTypePolicy::is_float_type_name(type_name)
                    or PymoduleDefaultScalarTypePolicy::is_signed_integer_type_name(type_name)
                    or PymoduleDefaultScalarTypePolicy::is_unsigned_integer_type_name(type_name)
                    or type_name == "bool"
                )
                == PymoduleDefaultHashablePolicy::is_python_hashable_type(type_name)
            )
    """,
}
for name, expected in expected_proofs.items():
    if compact(function_section(proof_text, name)) != compact(expected):
        raise SystemExit(f"proof body {name} changed without updating its source gate")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("PyModule scalar type-name proofs require a strict proof build")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
source_closure = source_include_closure([POSITIVE, NEGATIVE])
inputs = [
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV",
    stage1_product, stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
    DRIVER, DEFAULT_POLICY, *source_closure,
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
assert positive == run(POSITIVE)[1], "proof report changed across repeated runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
expected = {
    "is_text_type_name", "is_float_type_name", "is_signed_integer_type_name",
    "is_unsigned_integer_type_name", "text_type_name_classifier_is_exact",
    "float_type_name_classifier_is_exact", "signed_integer_type_name_classifier_is_exact",
    "unsigned_integer_type_name_classifier_is_exact", "scalar_type_groups_are_pairwise_disjoint",
    "scalar_type_groups_plus_bool_equal_hashable_policy",
}
assert expected <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert {row["name"] for row in negative["findings"]} == {
    "i128_must_be_a_signed_integer_type", "f16_must_be_a_float_type",
    "cstr_optional_must_be_a_text_type", "i8_must_be_an_unsigned_integer_type",
}
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert require_current_product(BIN, PROVER) == manifest, "proof product changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "closed PyModule default scalar type-name groups",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(row["name"] for row in negative["findings"]),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
