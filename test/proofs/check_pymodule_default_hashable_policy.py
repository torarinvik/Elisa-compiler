"""Admit source-linked proofs of the PyModule default hashable-type boundary."""
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
POSITIVE = HERE / "pymodule_default_hashable_policy.elisa"
NEGATIVE = HERE / "pymodule_default_hashable_policy_rejected.elisa"
POLICY = ROOT / "src/driver/pymodule/default_hashable_policy.elisa"
DEFAULT_POLICY = ROOT / "src/driver/pymodule/default_policy.elisa"
DRIVER = ROOT / "src/driver/elisac.elisa"
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")


if not __debug__:
    raise SystemExit("run without Python -O")

names = (
    "cstr", "sview", "bool", "f32", "f64", "i8", "i16", "i32", "i64",
    "int", "isize", "char", "u8", "u16", "u32", "u64", "usize", "uintptr",
)
policy_text = POLICY.read_text()
proof_text = POSITIVE.read_text()


def check_when_contract(text, description):
    match = re.search(
        r"(?m)^\s*ensure result == \(when type_name:\s*\n(.*?)^\s*\)",
        text,
        re.DOTALL,
    )
    if not match:
        raise SystemExit(f"{description} must specify the allowlist with pattern matching")
    arms = []
    for line in match.group(1).splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        arm = re.fullmatch(r'("[^"\\]+"(?:\s*\|\s*"[^"\\]+")*|_)\s*->\s*(true|false)', stripped)
        if not arm:
            raise SystemExit(f"{description} has a malformed hashable-type contract arm")
        arms.append(arm.groups())
    if not arms or arms[-1] != ("_", "false"):
        raise SystemExit(f"{description} lost its false fallback")
    found = []
    for pattern, result in arms[:-1]:
        if result != "true":
            raise SystemExit(f"{description} has a non-true allowlist arm")
        found.extend(re.findall(r'"([^"\\]+)"', pattern))
    if found != list(names):
        raise SystemExit(f"{description} allowlist differs from the ordered closed type set")


def check_match_implementation(text, description):
    match = re.search(r"(?m)^\s*return match type_name:\s*\n(.*)", text, re.DOTALL)
    if not match:
        raise SystemExit(f"{description} lost its exhaustive literal match")
    arms = []
    for line in match.group(1).splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        arm = re.fullmatch(r'("[^"\\]+"(?:\s*\|\s*"[^"\\]+")*|_):\s*(true|false)', stripped)
        if not arm:
            raise SystemExit(f"{description} has a malformed match arm")
        arms.append(arm.groups())
    if not arms or arms[-1] != ("_", "false"):
        raise SystemExit(f"{description} lost its false fallback")
    found = []
    for pattern, result in arms[:-1]:
        if result != "true":
            raise SystemExit(f"{description} has a non-true allowlist arm")
        found.extend(re.findall(r'"([^"\\]+)"', pattern))
    if found != list(names):
        raise SystemExit(f"{description} implementation differs from the ordered closed type set")


check_when_contract(policy_text, "production hashable-type policy contract")
check_match_implementation(policy_text, "production hashable-type policy")
check_when_contract(proof_text, "proof hashable-type contract")
if 'include "./pymodule/default_hashable_policy.elisa"' not in DRIVER.read_text():
    raise SystemExit("PyModule driver no longer includes the proved policy")
wrapper = re.search(
    r"(?m)^def pymodule_default_python_hashable_type\(type_name: sview\) -> bool can\[Abort\.Panic\]:\s*\n(.*?)(?=^def |\Z)",
    DEFAULT_POLICY.read_text(),
    re.DOTALL,
)
if not wrapper or "return PymoduleDefaultHashablePolicy::is_python_hashable_type(type_name)" not in wrapper.group(1):
    raise SystemExit("PyModule default checking no longer delegates to the proved policy")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("PyModule hashable-type proof requires a strict proof build")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
source_closure = source_include_closure([POSITIVE, NEGATIVE])
inputs = [
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV",
    stage1_product, stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
    DRIVER, DEFAULT_POLICY,
    *source_closure,
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
    "is_python_hashable_type",
    "hashable_classifier_matches_the_closed_type_set",
    "all_declared_hashable_types_are_accepted",
    "nearby_non_hashable_types_are_rejected",
}
assert expected <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert {row["name"] for row in negative["findings"]} == {
    "dstr_must_not_be_hashable", "wide_integer_must_not_be_hashable"
}
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert require_current_product(BIN, PROVER) == manifest, "proof product changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "closed Python hashable-type set used by PyModule defaults",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": ["dstr_must_not_be_hashable", "wide_integer_must_not_be_hashable"],
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
