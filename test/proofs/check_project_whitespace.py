"""Admit source-linked proofs of ProjectSystem's exact whitespace byte set."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product


ROOT = Path(__file__).resolve().parents[2]
PROVER = ROOT.parent / "elisa-proof"
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
POSITIVE = HERE / "project_whitespace.elisa"
NEGATIVE = HERE / "project_whitespace_rejected.elisa"
CONTROL_BYTES = HERE / "project_whitespace_control_bytes.elisa"
PROJECT = ROOT / "src/driver/project.elisa"
DRIVER = ROOT / "src/driver/elisac.elisa"
JSON_PARSER = ROOT / "src/driver/project_json_parse.elisa"

EXPECTED_VALUES = {
    "ASCII_SPACE": 32,
    "ASCII_HORIZONTAL_TAB": 9,
    "ASCII_LINE_FEED": 10,
    "ASCII_CARRIAGE_RETURN": 13,
}
EXPECTED_NAMES = tuple(EXPECTED_VALUES)

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    return " ".join(text.split())


project_text = PROJECT.read_text()
positive_text = POSITIVE.read_text()
function_marker = "def bytes_is_space(byte: u8) -> bool:"
if function_marker not in project_text:
    raise SystemExit("production project whitespace predicate is missing")
function_body = project_text.split(function_marker, 1)[1].split("# First index that is not whitespace", 1)[0]
expected_contract = compact("ensure result == ( " + " or ".join(
    f"byte == ProjectSystemWhitespaceByte::{name}" for name in EXPECTED_NAMES
) + " )")
if expected_contract not in compact(function_body):
    raise SystemExit("production predicate contract does not state its exact named byte set")
expected_return = (
    "return ( "
    + " or ".join(f"byte == ProjectSystemWhitespaceByte::{name}" for name in EXPECTED_NAMES)
    + " )"
)
if expected_return not in compact(function_body):
    raise SystemExit("production predicate no longer checks the exact named byte set")
for name, value in EXPECTED_VALUES.items():
    if not re.search(rf"\b{name}: u8 = {value}\b", project_text):
        raise SystemExit(f"missing or changed named byte constant: {name} = {value}")
if 'include "../../src/driver/project.elisa"' not in positive_text:
    raise SystemExit("positive proof no longer includes the production project system")
if 'include "./project.elisa"' not in DRIVER.read_text():
    raise SystemExit("compiler driver no longer imports the proved project system")
if not re.search(r"bytes_is_space\(data\[cursor\.position\]\)", JSON_PARSER.read_text()):
    raise SystemExit("project JSON parser no longer uses the proved whitespace predicate")
if not all(f"ProjectSystemWhitespaceByte::{name}" in positive_text for name in EXPECTED_NAMES):
    raise SystemExit("positive proof does not cover every named production whitespace byte")


def include_closure(roots: list[Path]) -> list[Path]:
    include = re.compile(r'^\s*include\s+"([^"]+)"', re.MULTILINE)
    pending = list(roots)
    seen: set[Path] = set()
    while pending:
        path = pending.pop().resolve(strict=True)
        if path in seen:
            continue
        seen.add(path)
        for relative in include.findall(path.read_text()):
            child = (path.parent / relative).resolve(strict=True)
            if child not in seen:
                pending.append(child)
    return sorted(seen)


try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("project whitespace proof requires a strict proof build")
compiler_head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                               check=True, capture_output=True, text=True).stdout.strip()
if compiler_head != manifest["compiler"]["source_revision"]:
    raise SystemExit("proof product was built from a different compiler revision")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [
    BIN,
    MANIFEST,
    MANIFEST_CHECKSUM,
    PROVER / "ELISA_COMPILER_REV",
    stage1_product,
    stage1_provenance,
    Path(__file__),
    HERE / "proof_product_gate.py",
    CONTROL_BYTES,
    DRIVER,
    JSON_PARSER,
    *include_closure([POSITIVE, NEGATIVE, PROJECT]),
]
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=120)
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
assert positive == run(POSITIVE)[1], "positive proof report changed across repeated runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert {
    "bytes_is_space",
    "production_predicate_matches_its_exact_byte_set",
    "all_project_whitespace_bytes_are_recognized",
    "nearby_ascii_controls_are_not_project_whitespace",
} <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert [(row["kind"], row["name"]) for row in negative["findings"]] == [
    ("ensure-unproven", "vertical_tab_is_project_whitespace"),
    ("ensure-unproven", "form_feed_is_project_whitespace"),
    ("ensure-unproven", "exclamation_mark_is_project_whitespace"),
]
assert require_current_product(BIN, PROVER) == manifest, "proof product changed during replay"
assert subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                      check=True, capture_output=True, text=True).stdout.strip() == compiler_head
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "exact source-linked project whitespace byte predicate",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": [row["name"] for row in negative["findings"]],
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
