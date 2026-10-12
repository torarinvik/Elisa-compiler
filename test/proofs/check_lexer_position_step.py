"""Admit the source-linked lexer cursor transition proof against a strict product."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
PROVER = ROOT.parent / "elisa-proof"
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
POSITIVE = HERE / "lexer_position_step.elisa"
NEGATIVE = HERE / "lexer_position_step_rejected.elisa"
OFFSET_POSITIVE = HERE / "lexer_position_offset_scalar.elisa"
OFFSET_NEGATIVE = HERE / "lexer_position_offset_scalar_rejected.elisa"
LINE_POSITIVE = HERE / "lexer_position_line_column_scalar.elisa"
LINE_NEGATIVE = HERE / "lexer_position_line_column_scalar_rejected.elisa"
HELPER = ROOT / "src/lexer/lexer_position_step.elisa"
FACADE = ROOT / "src/lexer/lexer.elisa"
CORE = ROOT / "src/lexer/lexer_core.elisa"
CURSOR = ROOT / "src/lexer/lexer_cursor_domain.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(source: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in source.splitlines())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def declaration_names(path: Path) -> set[str]:
    names = re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text())
    if len(names) != len(set(names)):
        raise SystemExit(f"duplicate proof declaration in {path.name}")
    return set(names)


source_offset = compact(function_section(HELPER.read_text(), "advanced_offset"))
scalar_offset = compact(function_section(OFFSET_POSITIVE.read_text(), "bounded_advance_offset"))
offset_transition = "offset+1ifoffset<source_lengthelseoffset"
if f"ensureresult==({offset_transition})" not in source_offset or \
        f"return{offset_transition}" not in source_offset or \
        f"ensureresult==({offset_transition})" not in scalar_offset or \
        f"return{offset_transition}" not in scalar_offset:
    raise SystemExit("scalar offset proof no longer matches the production transition contract and body")
offset_positive_names = {
    "bounded_advance_offset",
    "cursor_step_stays_inside_source",
    "cursor_step_makes_strict_progress",
    "cursor_step_preserves_offset_at_source_end",
    "cursor_step_preserves_offset_beyond_source_end",
}
offset_negative_names = {"false_claim_cursor_advances_at_source_end"}
if declaration_names(OFFSET_POSITIVE) != offset_positive_names or \
        declaration_names(OFFSET_NEGATIVE) != offset_negative_names or \
        'include "./lexer_position_offset_scalar.elisa"' not in OFFSET_NEGATIVE.read_text():
    raise SystemExit("scalar offset proof inventory changed")

line_source = compact(function_section(HELPER.read_text(), "advanced_line"))
newline_column_source = compact(function_section(HELPER.read_text(), "column_after_newline"))
column_source = compact(function_section(HELPER.read_text(), "advanced_column"))
line_scalar = compact(function_section(LINE_POSITIVE.read_text(), "stepped_line"))
newline_column_scalar = compact(function_section(LINE_POSITIVE.read_text(), "column_after_line_step"))
column_scalar = compact(function_section(LINE_POSITIVE.read_text(), "advanced_column"))
line_formula = "line+1ifis_newlineelseline"
newline_column_formula = "1ifis_newlineelse0"
column_formula = "column+1"
if f"ensureresult==({line_formula})" not in line_source or f"return{line_formula}" not in line_source or \
        f"ensureresult==({line_formula})" not in line_scalar or f"return{line_formula}" not in line_scalar or \
        f"ensureresult==({newline_column_formula})" not in newline_column_source or \
        f"return{newline_column_formula}" not in newline_column_source or \
        f"ensureresult==({newline_column_formula})" not in newline_column_scalar or \
        f"return{newline_column_formula}" not in newline_column_scalar or \
        f"ensureresult=={column_formula}" not in column_source or f"return{column_formula}" not in column_source or \
        f"ensureresult=={column_formula}" not in column_scalar or f"return{column_formula}" not in column_scalar:
    raise SystemExit("line/column scalar proofs no longer match the production transition formulas")
line_positive_names = {
    "stepped_line",
    "column_after_line_step",
    "advanced_column",
    "newline_step_updates_line_and_resets_column",
    "ordinary_step_preserves_line_and_advances_column",
}
line_negative_names = {"false_claim_newline_column_preserves_old"}
if declaration_names(LINE_POSITIVE) != line_positive_names or \
        declaration_names(LINE_NEGATIVE) != line_negative_names or \
        'include "./lexer_position_line_column_scalar.elisa"' not in LINE_NEGATIVE.read_text():
    raise SystemExit("line/column scalar proof inventory changed")

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
    OFFSET_POSITIVE,
    OFFSET_NEGATIVE,
    LINE_POSITIVE,
    LINE_NEGATIVE,
    HELPER,
    CURSOR,
    CORE,
    FACADE,
]
inputs.extend(source_include_closure([
    POSITIVE, NEGATIVE, OFFSET_POSITIVE, OFFSET_NEGATIVE, LINE_POSITIVE, LINE_NEGATIVE,
]))
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

code, offset_positive = run(OFFSET_POSITIVE)
assert code == 0 and offset_positive["status"] == offset_positive["verification_state"] == "proved"
assert offset_positive["summary"]["declarations"] == len(offset_positive_names)
assert offset_positive["summary"]["proven"] == offset_positive["summary"]["obligations"]
assert not offset_positive["findings"]
assert offset_positive == run(OFFSET_POSITIVE)[1], "scalar offset proof report changed across repeated runs"
assert {row["name"] for row in offset_positive["declaration_details"] if row.get("verified")} == offset_positive_names

code, offset_negative = run(OFFSET_NEGATIVE)
assert code == 1 and offset_negative["status"] == "failed"
assert offset_negative["summary"]["declarations"] == len(offset_positive_names) + len(offset_negative_names)
assert offset_negative["summary"]["proven"] + len(offset_negative_names) == offset_negative["summary"]["obligations"]
assert {finding["name"] for finding in offset_negative["findings"]} == offset_negative_names
assert all(finding["kind"] == "ensure-unproven" for finding in offset_negative["findings"])
assert not offset_negative_names & {row["name"] for row in offset_negative["declaration_details"] if row.get("verified")}

code, line_positive = run(LINE_POSITIVE)
assert code == 0 and line_positive["status"] == line_positive["verification_state"] == "proved"
assert line_positive["summary"]["declarations"] == len(line_positive_names)
assert line_positive["summary"]["proven"] == line_positive["summary"]["obligations"]
assert not line_positive["findings"]
assert line_positive == run(LINE_POSITIVE)[1], "line/column proof report changed across repeated runs"
assert {row["name"] for row in line_positive["declaration_details"] if row.get("verified")} == line_positive_names

code, line_negative = run(LINE_NEGATIVE)
assert code == 1 and line_negative["status"] == "failed"
assert line_negative["summary"]["declarations"] == len(line_positive_names) + len(line_negative_names)
assert line_negative["summary"]["proven"] + len(line_negative_names) == line_negative["summary"]["obligations"]
assert {finding["name"] for finding in line_negative["findings"]} == line_negative_names
assert all(finding["kind"] == "ensure-unproven" for finding in line_negative["findings"])
assert not line_negative_names & {row["name"] for row in line_negative["declaration_details"] if row.get("verified")}

assert require_current_product(BIN, PROVER) == manifest, "proof-product provenance changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "lexer EOF guard, cursor progress, line/column update, and source bound",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": ["cursor_step_does_not_advance"],
    "scalar_offset_obligations": offset_positive["summary"]["proven"],
    "scalar_offset_false_claims_rejected": sorted(offset_negative_names),
    "line_column_obligations": line_positive["summary"]["proven"],
    "line_column_false_claims_rejected": sorted(line_negative_names),
    "proof_binary_sha256": hashlib.sha256(BIN.read_bytes()).hexdigest(),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
