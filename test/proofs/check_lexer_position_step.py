"""Admit the source-linked lexer cursor transition proof against a strict product."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

from proof_product_gate import require_current_product


ROOT = Path(__file__).resolve().parents[2]
PROVER = ROOT.parent / "elisa-proof"
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
POSITIVE = HERE / "lexer_position_step.elisa"
NEGATIVE = HERE / "lexer_position_step_rejected.elisa"
HELPER = ROOT / "src/lexer/lexer_position_step.elisa"
FACADE = ROOT / "src/lexer/lexer.elisa"
CORE = ROOT / "src/lexer/lexer_core.elisa"
CURSOR = ROOT / "src/lexer/lexer_cursor_domain.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")
if 'include "./lexer_position_step.elisa"' not in FACADE.read_text():
    raise SystemExit("lexer facade no longer imports the proved cursor transition")
if 'include "../../src/lexer/lexer_position_step.elisa"' not in POSITIVE.read_text():
    raise SystemExit("proof no longer imports the production cursor transition")
if 'include "../../src/lexer/lexer_cursor_domain.elisa"' not in POSITIVE.read_text():
    raise SystemExit("proof no longer imports the source-end predicate used by the production guard")

core = CORE.read_text()
if 'include "./lexer_cursor_domain.elisa"' not in core:
    raise SystemExit("lexer core no longer imports the proved source-end predicate")
if "ensure result == (lexer.position >= lexer.source_length)" not in core:
    raise SystemExit("lexer end guard no longer has the verified cursor-boundary contract")
if "return LexerCursorDomain::cursor_at_or_past_source_end(lexer.position, lexer.source_length)" not in core:
    raise SystemExit("lexer end guard no longer delegates to the proved boundary predicate")

facade = FACADE.read_text()
advance_body = facade.split("def advance_char(lexer: lmut Lexer) -> void:", 1)[1].split(
    "def advance_chars(", 1
)[0]
required_body = [
    "lexer.position <- LexerPositionStep::advanced_offset(lexer.position, lexer.source_length)",
    "lexer.line <- LexerPositionStep::advanced_line(lexer.line, is_newline)",
    "if is_newline:",
    "LexerPositionStep::column_after_newline(is_newline)",
    "LexerPositionStep::advanced_column(lexer.column)",
]
if not all(fragment in advance_body for fragment in required_body):
    raise SystemExit("Lexer.advance_char no longer applies the proved position transition")
ordered_body = [
    "return if lexer.is_end_of_source()",
    "character: char = lexer.current_char()",
    "is_newline: bool = character == '\\n'",
    required_body[0],
    required_body[1],
    "if is_newline:",
]
positions = [advance_body.index(fragment) for fragment in ordered_body]
if positions != sorted(positions):
    raise SystemExit("Lexer.advance_char applies the bounded step before checking end of source")
newline_branch = (
    "            if is_newline:\n"
    "                lexer.column <- LexerPositionStep::column_after_newline(is_newline)\n"
    "            else:\n"
    "                lexer.column <- LexerPositionStep::advanced_column(lexer.column)"
)
if newline_branch not in advance_body:
    raise SystemExit("Lexer.advance_char no longer assigns newline and ordinary columns through their proofs")
if "lexer.line <- lexer.line + 1 if is_newline" in advance_body or "lexer.column <- 1 if is_newline" in advance_body:
    raise SystemExit("Lexer.advance_char has bypassed the verified transition")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("lexer position-step proof requires a strict proof build")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [
    BIN,
    MANIFEST,
    MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV",
    stage1_product,
    stage1_provenance,
    Path(__file__),
    HERE / "proof_product_gate.py",
    POSITIVE,
    NEGATIVE,
    HELPER,
    CURSOR,
    CORE,
    FACADE,
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
    "cursor_at_or_past_source_end",
    "end_boundary_predicate_matches_unsigned_order",
    "advanced_line",
    "advanced_column",
    "column_after_newline",
    "advanced_offset",
    "newline_step_advances_line_and_resets_column",
    "ordinary_step_preserves_line_and_advances_column",
    "cursor_step_stays_inside_source",
    "cursor_step_makes_strict_progress",
    "cursor_step_preserves_offset_at_source_end",
}
assert expected <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["proven"] + 1 == negative["summary"]["obligations"]
assert [(finding["kind"], finding["name"]) for finding in negative["findings"]] == [
    ("ensure-unproven", "cursor_step_does_not_advance")
]

assert require_current_product(BIN, PROVER) == manifest, "proof-product provenance changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "lexer EOF guard, cursor progress, line/column update, and source bound",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": ["cursor_step_does_not_advance"],
    "proof_binary_sha256": hashlib.sha256(BIN.read_bytes()).hexdigest(),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
