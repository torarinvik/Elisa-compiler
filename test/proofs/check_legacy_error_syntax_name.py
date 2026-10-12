"""Admit the source-linked proof of the deprecated error-pattern marker map."""
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
HELPER = ROOT / "src/semantic/legacy_error_syntax_name.elisa"
CHECK = ROOT / "src/semantic/check_legacy_error_syntax.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
PARSER = ROOT / "src/parser/parser_types_entry.elisa"
POSITIVE = HERE / "legacy_error_syntax_name.elisa"
NEGATIVE = HERE / "legacy_error_syntax_name_rejected.elisa"

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
    return source[start:end]


marker_map = (
    'when marker: "__legacy_error_wildcard" -> "wildcard" '
    '"__legacy_error_pipe" -> "pipe" "__legacy_error_open" -> "open" _ -> ""'
)
helper_text = HELPER.read_text()
proof_text = POSITIVE.read_text()
if compact(marker_map) not in compact(function_section(helper_text, "diagnostic_name")):
    raise SystemExit("production diagnostic-name helper no longer matches the closed marker map")
if compact(marker_map) not in compact(function_section(proof_text, "source_marker_map_matches_spec")):
    raise SystemExit("proof contract no longer states the exact parser-marker map")
if compact("return " + marker_map) not in compact(function_section(helper_text, "diagnostic_name")):
    raise SystemExit("production marker-map implementation differs from its contract")

semantic_text = SEMANTIC.read_text()
check_text = CHECK.read_text()
parser_text = PARSER.read_text()
if 'include "./legacy_error_syntax_name.elisa"' not in semantic_text:
    raise SystemExit("semantic root no longer imports the proved marker-name helper")
if 'include "./check_legacy_error_syntax.elisa"' not in semantic_text:
    raise SystemExit("legacy error-pattern check is no longer part of semantic analysis")
if "LegacyErrorSyntaxName::diagnostic_name(annotation.name)" not in check_text:
    raise SystemExit("legacy error-pattern check no longer uses the proved marker-name helper")
if "DiagnosticKind.LegacyErrorSyntax" not in check_text or 'diagnostic_name != ""' not in check_text:
    raise SystemExit("legacy error-pattern diagnostic no longer follows the proved mapping")
for obsolete in ("__legacy_error_wildcard", "__legacy_error_pipe", "__legacy_error_open"):
    if obsolete in check_text:
        raise SystemExit("legacy error-pattern consumer reintroduced an unproved marker comparison")
for marker in ("__legacy_error_wildcard", "__legacy_error_pipe", "__legacy_error_open"):
    if marker not in parser_text:
        raise SystemExit(f"parser no longer emits marker {marker}")
for path in (POSITIVE, NEGATIVE):
    if 'include "../../src/semantic/legacy_error_syntax_name.elisa"' not in path.read_text():
        raise SystemExit(f"{path.name} no longer imports the production marker mapper")

expected_positive = {
    "source_marker_map_matches_spec",
    "every_legacy_pattern_gets_its_diagnostic_name",
    "unrelated_markers_have_no_legacy_diagnostic_name",
}
expected_negative = {
    "unknown_marker_is_reported_as_wildcard",
    "pipe_marker_is_reported_as_open",
}


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


if declarations(POSITIVE) != expected_positive or declarations(NEGATIVE) != expected_negative:
    raise SystemExit("legacy error-pattern proof declaration inventory changed")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("legacy error-pattern proof requires a strict proof build")
compiler_head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                               check=True, capture_output=True, text=True).stdout.strip()
if compiler_head != product["compiler"]["source_revision"]:
    raise SystemExit("proof product was built from a different compiler revision")

stage1_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN,
    MANIFEST,
    MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV",
    stage1_product,
    stage1_provenance,
    Path(__file__),
    HERE / "proof_product_gate.py",
    HELPER,
    CHECK,
    SEMANTIC,
    PARSER,
    POSITIVE,
    NEGATIVE,
    *source_include_closure([POSITIVE, NEGATIVE, SEMANTIC, PARSER]),
]))
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


positive_code, positive = run(POSITIVE)
assert positive_code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "legacy error-pattern proof report changed across repeated runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert expected_positive | {"diagnostic_name"} <= verified

negative_code, negative = run(NEGATIVE)
assert negative_code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert negative["summary"]["proven"] + len(expected_negative) == negative["summary"]["obligations"]
assert {row["name"] for row in negative["findings"]} == expected_negative
assert all(row["kind"] == "ensure-unproven" and row["status"] == "disproved" and row["counterexample_found"]
           for row in negative["findings"])

assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product
print(json.dumps({
    "admitted": True,
    "scope": "closed mapping from parser legacy-error markers to semantic diagnostic names",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(expected_negative),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"]["source_revision"],
    "inputs_sha256": hashes_before,
}, sort_keys=True))
