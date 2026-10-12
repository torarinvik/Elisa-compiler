"""Admit source-linked proofs for never-leak environment-value interpretation."""
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
POSITIVE = HERE / "never_leak_env_values.elisa"
NEGATIVE = HERE / "never_leak_env_values_rejected.elisa"
CLASSIFIER = ROOT / "src/driver/never_leak_env_values.elisa"
HANDLER = ROOT / "src/driver/elisac_never_leak.elisa"
DRIVER = ROOT / "src/driver/elisac.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    without_comments = "\n".join(line.split("#", 1)[0] for line in text.splitlines())
    return re.sub(r"\s+", "", without_comments)


def function_chunk(text: str, name: str) -> str:
    match = re.search(rf"(?m)^[ \t]*def {re.escape(name)}\s*\(", text)
    if match is None:
        raise SystemExit(f"missing function {name}")
    following = re.search(r"(?m)^[ \t]*def ", text[match.end():])
    end = match.end() + following.start() if following else len(text)
    return text[match.start():end]


CLASSIFIER_TEXT = CLASSIFIER.read_text()
HANDLER_TEXT = HANDLER.read_text()
DRIVER_TEXT = DRIVER.read_text()
POSITIVE_TEXT = POSITIVE.read_text()
NEGATIVE_TEXT = NEGATIVE.read_text()

expected_constants = {
    "NL_ENV_MODE_OFF": 0,
    "NL_ENV_MODE_WARN": 1,
    "NL_ENV_MODE_ERROR": 2,
}
for name, value in expected_constants.items():
    if not re.search(rf"(?m)^        const {name}: u8 = {value}\s*$", CLASSIFIER_TEXT):
        raise SystemExit(f"named environment mode constant {name} changed")


def exact_when(function_name: str, expected: list[tuple[str, str]]) -> None:
    body = function_chunk(CLASSIFIER_TEXT, function_name)
    if "return when value:" not in body:
        raise SystemExit(f"{function_name} must classify with pattern matching")
    following = body.split("return when value:", 1)[1]
    actual = []
    for line in following.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        arm = re.fullmatch(r'("[^"\\]*"(?:\s*\|\s*"[^"\\]*")*|_)\s*->\s*([A-Za-z_][A-Za-z0-9_:]*)', stripped)
        if arm is None:
            break
        actual.append(arm.groups())
    if actual != expected:
        raise SystemExit(f"{function_name} match arms changed: {actual}")


exact_when("mode", [
    ('"" | "0"', "NL_ENV_MODE_OFF"),
    ('"error"', "NL_ENV_MODE_ERROR"),
    ("_", "NL_ENV_MODE_WARN"),
])
exact_when("is_strict", [( '"strict"', "true"), ("_", "false")])

if DRIVER_TEXT.count('include "./never_leak_env_values.elisa"') != 1:
    raise SystemExit("compiler driver must include the environment classifier exactly once")
if DRIVER_TEXT.index('include "./never_leak_env_values.elisa"') > DRIVER_TEXT.index('include "./elisac_never_leak.elisa"'):
    raise SystemExit("environment classifier must precede the never-leak handler")

mode = compact(function_chunk(HANDLER_TEXT, "never_leak_mode"))
if 'getenv("ELISA_STAGE1_NEVER_LEAK")isvalue_bytes' not in mode:
    raise SystemExit("mode reader no longer checks the exact environment variable")
if "(value_bytes).cast[cstr]canUnsafe.PointerCast" not in mode or "NeverLeakEnvValues::mode(setting)" not in mode:
    raise SystemExit("mode reader no longer casts and classifies the exact environment value")
if "NL_ENV_MODE_OFFreturnifenv_flag_enabled" not in mode or "returnNeverLeakEnvValues::NL_ENV_MODE_OFF" not in mode:
    raise SystemExit("absent or permissive mode must remain disabled")

strict = compact(function_chunk(HANDLER_TEXT, "never_leak_strict"))
if 'getenv("ELISA_STAGE1_NEVER_LEAK_LEVEL")isvalue_bytes' not in strict:
    raise SystemExit("strict-level reader no longer checks the exact environment variable")
if "(value_bytes).cast[cstr]canUnsafe.PointerCast" not in strict or "NeverLeakEnvValues::is_strict(setting)" not in strict:
    raise SystemExit("strict-level reader no longer classifies the exact environment value")
if "returnfalse" not in strict:
    raise SystemExit("absent strict-level setting must remain false")

run_never_leak = compact(function_chunk(HANDLER_TEXT, "run_never_leak"))
if "mode==NeverLeakEnvValues::NL_ENV_MODE_OFF" not in run_never_leak:
    raise SystemExit("lint runner no longer gates the off mode by its named constant")
if "mode==NeverLeakEnvValues::NL_ENV_MODE_ERROR" not in run_never_leak:
    raise SystemExit("lint runner no longer treats only the named error mode as fatal")
if "setting.count==" in mode or "setting[0]" in mode or "setting.count==" in strict or "setting[0]" in strict:
    raise SystemExit("prefix-only byte checks remain in an environment parser")

expected_positive = {
    "empty_and_zero_mode_values_disable",
    "error_mode_requires_exact_spelling",
    "other_nonempty_modes_are_warnings",
    "strict_level_requires_exact_spelling",
}
expected_negative = {
    "error_prefix_selects_error_mode",
    "strict_prefix_selects_strict_level",
    "unknown_mode_disables_lint",
}


def declarations(text: str) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", text))


if declarations(POSITIVE_TEXT) != expected_positive or declarations(NEGATIVE_TEXT) != expected_negative:
    raise SystemExit("environment-value proof theorem inventory changed")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("environment-value proof requires a strict proof build")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
source_closure = source_include_closure([POSITIVE, NEGATIVE, DRIVER, HANDLER])
inputs = [
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", DRIVER, HANDLER, *source_closure,
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
    "scope": "exact never-leak mode values, strict-level interpretation, and runner exit mode",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(expected_negative),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
