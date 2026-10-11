"""Admit source-linked token-kind wire names against a strict proof product."""
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
POSITIVE = HERE / "token_kind_spelling.elisa"
NEGATIVE = HERE / "token_kind_spelling_rejected.elisa"
MODEL = HERE / "lexer_token_proof_model.elisa"
TOKEN_SOURCE = ROOT / "src/lexer/tokens.elisa"
SPAN_SOURCE = ROOT / "src/lexer/lexer_token_span.elisa"
SPELLING_SOURCE = ROOT / "src/parser/token_kind_spelling.elisa"
FIXTURE = ROOT / "test/fixtures/lexer/token_model_cases.elisa"
COMPILER_PIN = PROVER / "ELISA_COMPILER_REV"

if not __debug__:
    raise SystemExit("run without Python -O")
if not MANIFEST.is_file():
    raise SystemExit(f"missing proof build manifest: {MANIFEST}")


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
proof_text = POSITIVE.read_text()
if 'include "./lexer_token_proof_model.elisa"' not in proof_text:
    raise AssertionError("proof no longer includes its TokenKind projection")
if 'include "../../src/parser/token_kind_spelling.elisa"' not in proof_text:
    raise AssertionError("proof no longer includes the production spelling implementation")
if 'include "../../src/lexer/lexer_token_span.elisa"' not in MODEL.read_text():
    raise AssertionError("proof projection no longer includes the production span module")


def kind_codes(path: Path, header: str) -> dict[str, int]:
    source = path.read_text()
    start = source.find(header)
    if start < 0:
        raise AssertionError(f"function not found in {path}: {header}")
    body = source[start + len(header):]
    next_function = re.search(r"^def\s+", body, re.MULTILINE)
    if next_function:
        body = body[:next_function.start()]
    constants = {name: int(value) for name, value in re.findall(
        r"^const\s+(\w+)\s*:\s*u64\s*=\s*(\d+)\s*$", source, re.MULTILINE)}
    result = {}
    arms = re.findall(
        r"^\s*TokenKind\.(\w+)\s*:\s*\n\s*return\s+([A-Za-z_]\w*|\d+)\s*$",
        body, re.MULTILINE,
    )
    for name, expression in arms:
        if name in result:
            raise AssertionError(f"duplicate TokenKind arm {name} in {path}")
        try:
            result[name] = int(expression) if expression.isdigit() else constants[expression]
        except KeyError as error:
            raise AssertionError(f"unresolved token code constant {expression} in {path}") from error
    return result


production_codes = kind_codes(SPELLING_SOURCE, "def emit_tokens_kind_code(kind: TokenKind) -> u64:")
fixture_codes = kind_codes(FIXTURE, "def frontend_token_kind_code(kind: TokenKind) -> u64:")
expected_kinds = set(enum_shape(TOKEN_SOURCE)[1])
if set(production_codes) != expected_kinds:
    raise AssertionError("production kind-code map is not exhaustive for TokenKind")
if fixture_codes != production_codes:
    raise AssertionError("lexer fixture kind-code map differs from the production mapping")
if len(set(production_codes.values())) != len(production_codes):
    raise AssertionError("production kind-code map aliases distinct TokenKind variants")

spelling_text = SPELLING_SOURCE.read_text()
for required in (
    "const TOKEN_KIND_CODE_RANGE_LE: u64 = 110",
    "const TOKEN_KIND_CODE_OWNED: u64 = 114",
    "ensure kind == TokenKind.RangeLe implies result == TOKEN_KIND_CODE_RANGE_LE",
    "ensure kind == TokenKind.Owned implies result == TOKEN_KIND_CODE_OWNED",
    'ensure code == TOKEN_KIND_DISPLAY_INDEX_RANGE_LE implies result == "..="',
    'ensure code == TOKEN_KIND_DISPLAY_INDEX_OWNED implies result == "owned"',
    "TokenKind.Owned:\n            return TOKEN_KIND_CODE_OWNED",
    "TokenKind.RangeLe:\n            return TOKEN_KIND_CODE_RANGE_LE",
    '109: "..="',
    '113: "owned"',
):
    if required not in spelling_text:
        raise AssertionError(f"production token-kind mapping lost a required clause: {required}")
fixture_text = FIXTURE.read_text()
if "const TOKEN_KIND_CODE_OWNED: u64 = 114" not in fixture_text:
    raise AssertionError("token fixture does not reserve the distinct Owned code")
if "const TOKEN_KIND_CODE_RANGE_LE: u64 = 110" not in fixture_text:
    raise AssertionError("token fixture does not match the inclusive-range wire code")
if "TokenKind.Owned:\n            return TOKEN_KIND_CODE_OWNED" not in fixture_text:
    raise AssertionError("fixture does not use the named Owned code")
if "TokenKind.RangeLe:\n            return TOKEN_KIND_CODE_RANGE_LE" not in fixture_text:
    raise AssertionError("fixture does not use the named inclusive-range code")
for declaration in (
    "rangele_uses_its_stage0_spelling",
    "owned_has_a_distinct_stage1_code_and_spelling",
    "fstring_uses_its_stage1_spelling",
    "loop_label_uses_its_stage1_spelling",
    "token_kind_code_is_injective",
):
    if not re.search(rf"\bdef\s+{declaration}\s*\(", POSITIVE.read_text()):
        raise AssertionError(f"positive theorem missing: {declaration}")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("token-kind spelling proof requires a strict proof build")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
INPUTS = [BIN, MANIFEST, MANIFEST_CHECKSUM, COMPILER_PIN, stage1_product,
          stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
          POSITIVE, NEGATIVE, MODEL, TOKEN_SOURCE, SPAN_SOURCE, SPELLING_SOURCE, FIXTURE]
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
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "proof report changed across repeated runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
expected = {
    "rangele_uses_its_stage0_spelling",
    "owned_has_a_distinct_stage1_code_and_spelling",
    "fstring_uses_its_stage1_spelling",
    "loop_label_uses_its_stage1_spelling",
    "token_kind_code_is_injective",
}
assert expected <= verified
assert all(row.get("verified") for row in positive["declaration_details"]
           if row["kind"] == "function")

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["proven"] + 2 == negative["summary"]["obligations"]
assert [(finding["kind"], finding["name"]) for finding in negative["findings"]] == [
    ("ensure-unproven", "rangele_is_reported_as_semicolon"),
    ("ensure-unproven", "owned_shares_the_rangele_code"),
]

assert require_current_product(BIN, PROVER) == manifest, "proof-product provenance changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in INPUTS}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "source-linked token kind code and display-name round trips",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": ["rangele_is_reported_as_semicolon", "owned_shares_the_rangele_code"],
    "proof_binary_sha256": hashlib.sha256(BIN.read_bytes()).hexdigest(),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
