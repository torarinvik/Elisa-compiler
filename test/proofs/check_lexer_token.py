"""Replay the source-linked token constructor span proof with a fresh strict product."""
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
POSITIVE = HERE / "lexer_token.elisa"
NEGATIVE = HERE / "lexer_token_rejected.elisa"
MODEL = HERE / "lexer_token_proof_model.elisa"
FACADE = ROOT / "src/lexer/lexer.elisa"
TOKEN_SOURCE = ROOT / "src/lexer/tokens.elisa"
POSITION_SOURCE = ROOT / "src/lexer/lexer_position.elisa"
IMPLEMENTATION = ROOT / "src/lexer/lexer_token.elisa"
SPAN_IMPLEMENTATION = ROOT / "src/lexer/lexer_token_span.elisa"
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
COMPILER_PIN = PROVER / "ELISA_COMPILER_REV"

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


def function_body_statements(path: Path, header: str) -> list[str]:
    lines = path.read_text().splitlines()
    for index, line in enumerate(lines):
        if line.strip() != header:
            continue
        indent = len(line) - len(line.lstrip(" "))
        statements = []
        for body_line in lines[index + 1:]:
            if not body_line.strip() or body_line.lstrip().startswith("#"):
                continue
            body_indent = len(body_line) - len(body_line.lstrip(" "))
            if body_indent <= indent:
                break
            statements.append(re.sub(r"\s+", " ", body_line.strip()))
        return statements
    raise AssertionError(f"function not found in {path}: {header}")


expected_fields = {
    "line": "mutableu32",
    "column": "mutableu32",
    "start": "mutableu32",
    "length": "mutableu32",
    "suffix_length": "mutableu16",
    "kind": "mutableTokenKind",
    "flags": "bitset:",
}
if struct_fields(TOKEN_SOURCE, "Token") != expected_fields:
    raise AssertionError("production Token layout changed; update the proof projection")
if struct_fields(MODEL, "Token") != expected_fields:
    raise AssertionError("proof Token projection differs from the production layout")
expected_position = {"line": "mutableint", "column": "mutableint", "offset": "mutableusize"}
if struct_fields(POSITION_SOURCE, "LexerPosition") != expected_position:
    raise AssertionError("production LexerPosition layout changed; update the proof projection")
if struct_fields(MODEL, "LexerPosition") != expected_position:
    raise AssertionError("proof LexerPosition projection differs from production")
expected_span_fields = {
    "line": "u32", "column": "u32", "start": "u32",
    "length": "u32", "suffix_length": "u16",
}
if struct_fields(TOKEN_SOURCE, "TokenSpan") != expected_span_fields:
    raise AssertionError("production TokenSpan layout changed; update the proof projection")
if struct_fields(MODEL, "TokenSpan") != expected_span_fields:
    raise AssertionError("proof TokenSpan projection differs from production")

def enum_shape(path: Path) -> tuple[str, list[str]]:
    lines = path.read_text().splitlines()
    header = re.compile(r"^( *)const enum TokenKind of ([A-Za-z_]\w*)\s*:\s*$")
    for index, line in enumerate(lines):
        match = header.match(line)
        if not match:
            continue
        indent = len(match.group(1))
        variants = []
        for variant_line in lines[index + 1:]:
            if not variant_line.strip() or variant_line.lstrip().startswith("#"):
                continue
            variant_indent = len(variant_line) - len(variant_line.lstrip(" "))
            if variant_indent <= indent:
                break
            if variant_indent == indent + 4:
                variants.append(variant_line.strip())
        return match.group(2), variants
    raise AssertionError(f"TokenKind declaration not found in {path}")


if enum_shape(TOKEN_SOURCE) != enum_shape(MODEL):
    raise AssertionError("proof TokenKind projection differs from the production enum")
if not re.search(r"flags:\s*bitset:\s*\n\s+has_suffix\s*$", TOKEN_SOURCE.read_text(), re.MULTILINE):
    raise AssertionError("production Token.flags no longer contains exactly has_suffix")
if not re.search(r"flags:\s*bitset:\s*\n\s+has_suffix\s*$", MODEL.read_text(), re.MULTILINE):
    raise AssertionError("proof Token.flags projection differs from production")

facade = FACADE.read_text()
proof_text = POSITIVE.read_text()
for required in (
    'include "./lexer_token_span.elisa"',
    'include "./lexer_token.elisa"',
    'include "../../src/lexer/lexer_token_span.elisa"',
    'include "./lexer_token_proof_model.elisa"',
):
    if required not in facade + proof_text + MODEL.read_text():
        raise AssertionError(f"production or proof no longer includes the source contract: {required}")
if facade.index('include "./lexer_token_span.elisa"') > facade.index('include "./lexer_token.elisa"'):
    raise AssertionError("TokenSpan contract must be included before Token construction")
span_implementation_text = SPAN_IMPLEMENTATION.read_text()
required_contracts = (
    "ensure result.line == line",
    "ensure result.column == column",
    "ensure result.start == start",
    "ensure result.length == length",
    "ensure result.suffix_length == suffix_length",
)
for contract in required_contracts:
    if contract not in span_implementation_text:
        raise AssertionError(f"production span-helper contract missing: {contract}")
five_argument_body = [
    "span: TokenSpan = token_span_fields(position.line.u32(), position.column.u32(), start.u32(), (text_end - start).u32(), (suffix_end - text_end).u16())",
    "token: mutable Token = zeroed",
    "token.kind <- kind",
    "token.line <- span.line",
    "token.column <- span.column",
    "token.start <- span.start",
    "token.length <- span.length",
    "token.suffix_length <- span.suffix_length",
    "token.flags.has_suffix <- suffix_end > text_end",
    "return token",
]
if function_body_statements(IMPLEMENTATION, "def Token(kind: TokenKind, position: LexerPosition, start: usize, text_end: usize, suffix_end: usize) -> Token:") != five_argument_body:
    raise AssertionError("Token constructor no longer assembles fields from the proved span projection")
if function_body_statements(IMPLEMENTATION, "def Token(kind: TokenKind, position: LexerPosition, start: usize, text_end: usize) -> Token:") != [
    "return Token(kind, position, start, text_end, text_end)",
]:
    raise AssertionError("default Token constructor no longer delegates with an empty suffix span")
for declaration in (
    "token_span_preserves_line", "token_span_preserves_column",
    "token_span_preserves_start", "token_span_preserves_text_length",
    "token_span_preserves_suffix_length",
):
    if not re.search(rf"\bdef\s+{declaration}\s*\(", proof_text):
        raise AssertionError(f"positive proof declaration missing: {declaration}")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
SOURCES = [Path(__file__), HERE / "proof_product_gate.py", POSITIVE, NEGATIVE, MODEL,
           FACADE, TOKEN_SOURCE, POSITION_SOURCE, IMPLEMENTATION, SPAN_IMPLEMENTATION]
INPUTS = [BIN, MANIFEST, MANIFEST_CHECKSUM, COMPILER_PIN, stage1_product,
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
assert positive["summary"]["proven"] == positive["summary"]["obligations"] == 16
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "proof report changed across repeated runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
expected = {
    "token_span_fields", "token_span_preserves_line", "token_span_preserves_column",
    "token_span_preserves_start", "token_span_preserves_text_length",
    "token_span_preserves_suffix_length",
}
assert expected <= verified
assert all(row.get("verified") for row in positive["declaration_details"] if row["kind"] == "function")
positive_details = {row["name"]: row for row in positive["declaration_details"]}
assert positive_details["token_span_fields"]["ensures"] == 5
assert all(positive_details[name]["ensures"] == 1 for name in expected - {"token_span_fields"})

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["proven"] == 7 and negative["summary"]["obligations"] == 8
assert [(finding["kind"], finding["name"]) for finding in negative["findings"]] == [
    ("ensure-unproven", "token_line_is_column")]
assert "token_line_is_column" not in {
    row["name"] for row in negative["declaration_details"] if row.get("verified")}

assert require_current_product(BIN, PROVER) == manifest, "proof-product provenance changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in INPUTS}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({"admitted": True,
                  "scope": "pure lexer TokenSpan arithmetic, source-constructor linkage, and false-claim rejection",
                  "positive_obligations": positive["summary"]["proven"],
                  "independently_replayed": positive["replay"]["replayed"],
                  "false_claims_rejected": ["token_line_is_column"],
                  "proof_binary_sha256": hashlib.sha256(BIN.read_bytes()).hexdigest(),
                  "proof_revision": manifest["proof"].get("head"),
                  "compiler_revision": manifest["compiler"].get("source_revision"),
                  "sources_sha256": hashes_before}, sort_keys=True))
