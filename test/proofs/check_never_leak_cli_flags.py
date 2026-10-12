"""Admit source-linked proofs for the never-leak CLI flag classifier."""
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
POSITIVE = HERE / "never_leak_cli_flags.elisa"
NEGATIVE = HERE / "never_leak_cli_flags_rejected.elisa"
CLASSIFIER = ROOT / "src/driver/never_leak_cli_flags.elisa"
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


ALIASES = {
    "Warn": ("-Wnever-leak", "never-leak"),
    "WarnGentle": ("-Wnever-leak=gentle", "never-leak=gentle"),
    "WarnStrict": ("-Wnever-leak=strict", "never-leak=strict"),
    "Error": ("-Werror=never-leak", "error=never-leak"),
    "ErrorGentle": ("-Werror=never-leak=gentle", "error=never-leak=gentle"),
    "ErrorStrict": ("-Werror=never-leak=strict", "error=never-leak=strict"),
}
ACTION_ORDER = ("Unrecognized", *ALIASES)
CLASSIFIER_TEXT = CLASSIFIER.read_text()
HANDLER_TEXT = HANDLER.read_text()
DRIVER_TEXT = DRIVER.read_text()
POSITIVE_TEXT = POSITIVE.read_text()
NEGATIVE_TEXT = NEGATIVE.read_text()


def expected_when_arms(result_prefix: str) -> list[tuple[str, str]]:
    arms = [(" | ".join(f'"{alias}"' for alias in aliases), f"{result_prefix}.{action}")
            for action, aliases in ALIASES.items()]
    arms.append(("_", f"{result_prefix}.Unrecognized"))
    return arms


def parse_when(text: str, marker: str, result_prefix: str) -> list[tuple[str, str]]:
    start = text.find(marker)
    if start < 0:
        raise SystemExit(f"missing {marker}")
    tail = text[start + len(marker):]
    arms = []
    for line in tail.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped == ")":
            break
        arm = re.fullmatch(r'("[^"\\]+"(?:\s*\|\s*"[^"\\]+")*|_)\s*->\s*(Action\.[A-Za-z]+)', stripped)
        if arm is None:
            raise SystemExit(f"malformed classifier arm: {stripped}")
        pattern, action = arm.groups()
        arms.append((pattern, f"{result_prefix}.{action.split('.', 1)[1]}"))
    return arms


enum = re.search(r"(?ms)^        const enum Action of u8:\s*\n(.*?)(?=^        def )", CLASSIFIER_TEXT)
if enum is None:
    raise SystemExit("CLI action enum is missing")
variants = [line.strip() for line in enum.group(1).splitlines() if line.strip()]
if variants != list(ACTION_ORDER):
    raise SystemExit(f"CLI action variants changed: {variants}")

classify = function_chunk(CLASSIFIER_TEXT, "classify")
expected_arms = expected_when_arms("NeverLeakCliFlags::Action")
implementation_marker = "return when flag:"
if parse_when(classify, implementation_marker, "NeverLeakCliFlags::Action") != expected_arms:
    raise SystemExit("classifier no longer implements the exact flag-to-action map")

if DRIVER_TEXT.count('include "./never_leak_cli_flags.elisa"') != 1:
    raise SystemExit("driver must include the CLI classifier exactly once")
if DRIVER_TEXT.index('include "./never_leak_cli_flags.elisa"') > DRIVER_TEXT.index('include "./elisac_never_leak.elisa"'):
    raise SystemExit("CLI classifier must be included before its handler")

handler = function_chunk(HANDLER_TEXT, "never_leak_cli_flag")
if compact("const NL_SETENV_OVERWRITE_EXISTING: i32 = 1") not in compact(HANDLER_TEXT):
    raise SystemExit("setenv overwrite mode must be named rather than a magic number")
if compact("match NeverLeakCliFlags::classify(flag):") not in compact(handler):
    raise SystemExit("CLI handler no longer dispatches on the proved classifier")
if "flag==" in compact(handler):
    raise SystemExit("CLI handler added an unproved string-comparison path")

handler_arms = {}
lines = handler.splitlines()
for index, line in enumerate(lines):
    header = re.fullmatch(r"\s*NeverLeakCliFlags::Action\.([A-Za-z]+):\s*", line)
    if header is None:
        continue
    arm_name = header.group(1)
    arm_indent = len(line) - len(line.lstrip())
    end = next((stop for stop in range(index + 1, len(lines))
                if lines[stop].strip()
                and len(lines[stop]) - len(lines[stop].lstrip()) <= arm_indent), len(lines))
    handler_arms[arm_name] = compact("\n".join(lines[index + 1:end]))
if set(handler_arms) != set(ACTION_ORDER):
    raise SystemExit("CLI handler no longer handles every classifier action exactly once")

overwrite = "NL_SETENV_OVERWRITE_EXISTING"
expected_handler_arms = {
    "Unrecognized": "returnfalse",
    "Warn": f'_ = setenv("ELISA_STAGE1_NEVER_LEAK", "warn", {overwrite})',
    "WarnGentle": f'_ = setenv("ELISA_STAGE1_NEVER_LEAK", "warn", {overwrite}) _ = setenv("ELISA_STAGE1_NEVER_LEAK_LEVEL", "gentle", {overwrite})',
    "WarnStrict": f'_ = setenv("ELISA_STAGE1_NEVER_LEAK", "warn", {overwrite}) _ = setenv("ELISA_STAGE1_NEVER_LEAK_LEVEL", "strict", {overwrite})',
    "Error": f'_ = setenv("ELISA_STAGE1_NEVER_LEAK", "error", {overwrite})',
    "ErrorGentle": f'_ = setenv("ELISA_STAGE1_NEVER_LEAK", "error", {overwrite}) _ = setenv("ELISA_STAGE1_NEVER_LEAK_LEVEL", "gentle", {overwrite})',
    "ErrorStrict": f'_ = setenv("ELISA_STAGE1_NEVER_LEAK", "error", {overwrite}) _ = setenv("ELISA_STAGE1_NEVER_LEAK_LEVEL", "strict", {overwrite})',
}
for action, expected in expected_handler_arms.items():
    if handler_arms[action] != compact(expected):
        raise SystemExit(f"CLI side effects changed for {action}")
if "returntrue" not in compact(handler):
    raise SystemExit("recognized CLI actions no longer report success")

expected_positive = {
    "warning_aliases_select_warning_mode",
    "error_aliases_select_error_mode",
    "unknown_flags_are_unrecognized",
}
expected_negative = {
    "strict_warning_alias_is_unrecognized",
    "error_alias_selects_warning_mode",
    "unrelated_flag_is_accepted",
}


def declarations(text: str) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", text))


if declarations(POSITIVE_TEXT) != expected_positive or declarations(NEGATIVE_TEXT) != expected_negative:
    raise SystemExit("CLI flag proof theorem inventory changed")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("CLI flag proof requires a strict proof build")

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
    "scope": "never-leak CLI alias classification and its warning/error action dispatch",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(expected_negative),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
