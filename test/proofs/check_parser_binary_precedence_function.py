"""Admit a direct proof of the production parser's precedence classifier."""
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
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
TOKENS = ROOT / "src/lexer/tokens.elisa"
PROJECTION = HERE / "parser_token_kind_projection.elisa"
MODEL = ROOT / "src/parser/parser_binary_precedence.elisa"
PARSER = ROOT / "src/parser/parser_expr_binary.elisa"
PARSER_OPS = ROOT / "src/parser/parser_expr_ops.elisa"
PARSER_FACADE = ROOT / "src/parser/parser.elisa"
POSITIVE = HERE / "parser_binary_precedence_function.elisa"
NEGATIVE = HERE / "parser_binary_precedence_function_rejected.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    return "".join(text.split())


expected_levels = {
    "ARROW_OR": (1, ["Arrow", "Or"]),
    "AND": (2, ["And"]),
    "COMPARISON": (3, ["EqEq", "BangEq", "Lt", "Gt", "LtEq", "GtEq", "In", "Is", "As"]),
    "RANGE": (4, ["Range", "RangeLt", "RangeGt", "RangeLe"]),
    "BITWISE_OR": (5, ["Pipe"]),
    "BITWISE_XOR": (6, ["Caret"]),
    "BITWISE_AND": (7, ["Ampersand"]),
    "SHIFT": (8, ["LShift", "RShift"]),
    "ADDITIVE": (9, ["Plus", "Minus"]),
    "MULTIPLICATIVE": (10, ["Star", "Slash", "Percent"]),
}


levels = list(expected_levels.items())
parts = []
for level_name, (_, names) in levels:
    condition = " or ".join(f"kind == Lexer::TokenKind.{name}" for name in names)
    parts.append(f"ParserBinaryPrecedence::{level_name} if {condition}")
expected_spec = compact("ensure result == (" + " else ".join(parts) + " else 0)")
positive_text = POSITIVE.read_text()
model_text = MODEL.read_text()
if expected_spec not in compact(positive_text):
    raise SystemExit("direct proof contract no longer states the complete precedence specification")

const_pattern = re.compile(r"(?m)^\s*const ([A-Z_]+): int = ([0-9]+)\s*$")
actual_levels = {name: int(value) for name, value in const_pattern.findall(model_text)}
required_levels = {name: value for name, (value, _) in expected_levels.items()}
if actual_levels != required_levels:
    raise SystemExit("production precedence constants differ from the specified binding-power levels")

function = re.search(r"(?m)^\s*def precedence\(kind: Lexer::TokenKind\) -> int:\n(.*?)(?=^\s*def |\Z)", model_text, re.DOTALL)
if not function:
    raise SystemExit("production precedence function is missing")
actual_arms = {}
for line in function.group(1).splitlines():
    arm = re.fullmatch(r"\s*(Lexer::TokenKind\.[A-Za-z_][A-Za-z0-9_]*(?:\s*\|\s*Lexer::TokenKind\.[A-Za-z_][A-Za-z0-9_]*)*)\s*->\s*([A-Z_]+)\s*", line)
    if not arm:
        continue
    for token in re.findall(r"Lexer::TokenKind\.([A-Za-z_][A-Za-z0-9_]*)", arm.group(1)):
        if token in actual_arms:
            raise SystemExit(f"duplicate precedence case for Lexer::TokenKind.{token}")
        actual_arms[token] = arm.group(2)
expected_arms = {token: name for name, (_, tokens) in expected_levels.items() for token in tokens}
if actual_arms != expected_arms:
    raise SystemExit("production precedence match differs from the complete token-family partition")
if not re.search(r"(?m)^\s*_\s*->\s*0\s*$", function.group(1)):
    raise SystemExit("production precedence classifier lost its zero fallback")


def enum_variants(path: Path) -> list[str]:
    text = path.read_text()
    match = re.search(
        r"(?ms)^\s*const enum TokenKind of u8:\n(.*?)(?=^\s*(?:struct|const enum|def) |\Z)",
        text,
    )
    if not match:
        raise SystemExit(f"TokenKind enum projection is missing in {path}")
    variants = []
    for line in match.group(1).splitlines():
        stripped = line.strip()
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", stripped):
            variants.append(stripped)
    return variants


if enum_variants(TOKENS) != enum_variants(PROJECTION):
    raise SystemExit("proof TokenKind projection differs from the complete production enum order")

if 'include "./parser_binary_precedence.elisa"' not in PARSER.read_text():
    raise SystemExit("expression parser no longer imports the proved precedence function")
if "ParserBinaryPrecedence::precedence(kind)" not in PARSER.read_text():
    raise SystemExit("precedence-climbing loop no longer uses the proved token classifier")
if 'include "./parser_expr_binary.elisa"' not in PARSER_OPS.read_text():
    raise SystemExit("expression parser aggregator no longer imports the precedence-climbing loop")
if 'include "./parser_expr_ops.elisa"' not in PARSER_FACADE.read_text():
    raise SystemExit("parser facade no longer imports the expression parser aggregation")
if 'include "./parser_token_kind_projection.elisa"' not in positive_text:
    raise SystemExit("positive proof no longer imports the verified TokenKind projection")
if 'include "../../src/parser/parser_binary_precedence.elisa"' not in positive_text:
    raise SystemExit("positive proof no longer imports the production precedence function")
if 'include "./parser_binary_precedence_function.elisa"' not in NEGATIVE.read_text():
    raise SystemExit("negative controls no longer import the positive source-linked proof")

try:
    product_manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product_manifest.get("compile_mode") != "strict":
    raise SystemExit("precedence classifier proof requires a strict proof build")

stage1_product = Path(product_manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
source_closure = source_include_closure([POSITIVE, NEGATIVE, PARSER])
inputs = [
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", TOKENS, PROJECTION, MODEL, PARSER,
    PARSER_OPS, PARSER_FACADE,
    *source_closure,
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
assert positive == run(POSITIVE)[1], "production precedence proof changed across repeated runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert {
    "precedence",
    "production_precedence_matches_exact_decision_table",
    "every_binary_operator_uses_its_named_precedence_level",
    "non_operator_tokens_keep_zero_precedence",
} <= verified

code, negative = run(NEGATIVE)
negative_names = {
    "a_left_shift_has_bitwise_and_precedence",
    "compound_shift_has_binary_shift_precedence",
    "unknown_token_has_comparison_precedence",
}
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert not negative_names & {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert require_current_product(BIN, PROVER) == product_manifest
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
print(json.dumps({
    "admitted": True,
    "scope": "production parser TokenKind-to-binding-power classification",
    "operator_cases": sum(len(tokens) for _, tokens in expected_levels.values()),
    "false_claims_rejected": sorted(negative_names),
    "positive_obligations": positive["summary"]["proven"],
    "proof_revision": product_manifest["proof"].get("head"),
    "compiler_revision": product_manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
