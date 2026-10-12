"""Replay the exact parser token-to-AST-position contract on a current strict product."""
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
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
COMPILER_PIN = PROVER / "ELISA_COMPILER_REV"
POSITIVE = HERE / "parser_token_position.elisa"
NEGATIVE = HERE / "parser_token_position_rejected.elisa"
MODEL = HERE / "parser_token_position_proof_model.elisa"
PARSER_FACADE = ROOT / "src/parser/parser.elisa"
AST_SOURCE = ROOT / "src/parser/parser_tokens.elisa"
POSITION_SOURCE = ROOT / "src/parser/parser_token_position.elisa"
TOKEN_SOURCE = ROOT / "src/lexer/tokens.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def struct_fields(path: Path, name: str) -> dict[str, str]:
    lines = path.read_text().splitlines()
    declaration = re.compile(rf"^( *)struct {re.escape(name)}:\s*$")
    for index, line in enumerate(lines):
        match = declaration.match(line)
        if not match:
            continue
        indent = len(match.group(1))
        fields = {}
        for field_line in lines[index + 1:]:
            if not field_line.strip() or field_line.lstrip().startswith("#"):
                continue
            field_indent = len(field_line) - len(field_line.lstrip(" "))
            if field_indent <= indent:
                break
            if field_indent != indent + 4:
                continue
            field = re.match(r"^\s*([A-Za-z_]\w*):\s*(.*?)\s*$", field_line)
            if field:
                fields[field.group(1)] = re.sub(r"\s+", "", field.group(2))
        return fields
    raise AssertionError(f"struct {name} not found in {path}")


expected_pos = {
    "line": "mutableu32", "column": "mutableu32", "offset": "mutableu32",
    "end_line": "mutableu32", "end_column": "mutableu32", "end_offset": "mutableu32",
}
if struct_fields(AST_SOURCE, "Pos") != expected_pos:
    raise AssertionError("production Ast::Pos layout changed; update the proof projection")
if struct_fields(MODEL, "Pos") != expected_pos:
    raise AssertionError("proof Ast::Pos projection differs from production")
expected_token_fields = {
    "line": "mutableu32", "column": "mutableu32",
    "start": "mutableu32", "length": "mutableu32",
}
production_token_fields = struct_fields(TOKEN_SOURCE, "Token")
for name, expected in expected_token_fields.items():
    if production_token_fields.get(name) != expected:
        raise AssertionError(f"production Lexer::Token.{name} changed: {production_token_fields.get(name)!r}")
if struct_fields(MODEL, "Token") != expected_token_fields:
    raise AssertionError("proof Lexer::Token projection differs from production fields used by pos_of_token")

facade = PARSER_FACADE.read_text()
ast_source = AST_SOURCE.read_text()
proof_text = POSITIVE.read_text()
model_text = MODEL.read_text()
if 'include "./parser_token_position.elisa"' not in facade:
    raise AssertionError("parser facade no longer includes the verified position implementation")
if facade.index('include "./parser_tokens.elisa"') > facade.index('include "./parser_token_position.elisa"'):
    raise AssertionError("Ast::Pos must be declared before pos_of_token is included")
if any(f"def {name}(" in ast_source for name in ("pos_at_line", "pos_of_token", "pos_of_quoted_token", "pos_span")):
    raise AssertionError("remove uncontracted position helpers from parser_tokens.elisa")
if 'include "../../src/parser/parser_token_position.elisa"' not in model_text:
    raise AssertionError("proof no longer includes the production pos_of_token implementation")
if 'include "./parser_token_position_proof_model.elisa"' not in proof_text:
    raise AssertionError("positive proof no longer loads its checked projection")
required_contracts = (
    "ensure result.line == line",
    "ensure result.column == 0",
    "ensure result.offset == 0",
    "ensure result.end_line == line",
    "ensure result.end_column == 0",
    "ensure result.end_offset == 0",
    "ensure result.line == token.line",
    "ensure result.column == token.column",
    "ensure result.offset == token.start",
    "ensure result.end_line == token.line",
    "ensure result.end_column == token.column + token.length",
    "ensure result.end_offset == token.start + token.length",
    "ensure result.line == token.line",
    "ensure result.column == token.column",
    "ensure result.offset == token.start - 1",
    "ensure result.end_line == token.line",
    "ensure result.end_column == token.column + token.length + 2",
    "ensure result.end_offset == token.start + token.length + 1",
    "ensure result.line == start.line",
    "ensure result.column == start.column",
    "ensure result.offset == start.offset",
    "ensure result.end_line == end.end_line",
    "ensure result.end_column == end.end_column",
    "ensure result.end_offset == end.end_offset",
)
for contract in required_contracts:
    if contract not in POSITION_SOURCE.read_text():
        raise AssertionError(f"production pos_of_token contract missing: {contract}")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
SOURCES = [Path(__file__), HERE / "proof_product_gate.py", POSITIVE, NEGATIVE, MODEL,
           PARSER_FACADE, AST_SOURCE, POSITION_SOURCE, TOKEN_SOURCE]
INPUTS = [*source_include_closure([POSITIVE, NEGATIVE]), BIN, MANIFEST, MANIFEST_CHECKSUM, COMPILER_PIN, stage1_product,
          stage1_provenance, *SOURCES]
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in INPUTS}


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
assert positive["summary"]["proven"] == positive["summary"]["obligations"] == 28
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "proof report changed across repeated runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert "pos_of_token" in verified
position_details = {row["name"]: row for row in positive["declaration_details"]
                    if row["name"] in {"pos_at_line", "pos_of_token", "pos_of_quoted_token", "pos_span"}}
assert set(position_details) == {"pos_at_line", "pos_of_token", "pos_of_quoted_token", "pos_span"}
assert all(row["ensures"] == 6 for row in position_details.values())
assert all(row.get("verified") for row in positive["declaration_details"] if row["kind"] == "function")

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["proven"] == 29 and negative["summary"]["obligations"] == 30
assert [(finding["kind"], finding["name"]) for finding in negative["findings"]] == [
    ("ensure-unproven", "token_position_line_is_column")]
assert "token_position_line_is_column" not in {
    row["name"] for row in negative["declaration_details"] if row.get("verified")}

try:
    manifest_after = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance changed during replay: {error}") from error
assert manifest_after == manifest, "proof product manifest changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in INPUTS}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({"admitted": True,
                  "scope": "line-only fallback, ordinary and quoted token positions, and AST span composition",
                  "positive_obligations": positive["summary"]["proven"],
                  "independently_replayed": positive["replay"]["replayed"],
                  "false_claims_rejected": ["token_position_line_is_column"],
                  "proof_binary_sha256": hashlib.sha256(BIN.read_bytes()).hexdigest(),
                  "proof_revision": manifest["proof"].get("head"),
                  "compiler_revision": manifest["compiler"].get("source_revision"),
                  "sources_sha256": hashes_before}, sort_keys=True))
