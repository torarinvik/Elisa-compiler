"""Admit source-linked proofs of the semantic comparison-operator policy."""
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
HELPER = ROOT / "src/semantic/comparison_operator_policy.elisa"
STATIC_ASSERT = ROOT / "src/semantic/check_static_assert.elisa"
LITERAL_COMPARISON = ROOT / "src/semantic/check_literal_comparison_impossible.elisa"
TOKENS = ROOT / "src/lexer/tokens.elisa"
TOKEN_PROJECTION = HERE / "parser_token_kind_projection.elisa"
POSITIVE = HERE / "comparison_operator_policy.elisa"
NEGATIVE = HERE / "comparison_operator_policy_rejected.elisa"
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
PROOF_TIMEOUT_SECONDS = 120
EXPECTED_PRODUCTION_MATCHES = 2

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    return "".join(text.split())


def function_section(text: str, name: str) -> str:
    match = re.search(rf"(?m)^\s*def {re.escape(name)}\([^\n]*\n(.*?)(?=^\s*def |\Z)", text, re.DOTALL)
    if not match:
        raise SystemExit(f"missing source function {name}")
    return match.group(1)


def enum_variants(text: str) -> list[str]:
    match = re.search(r"(?ms)^\s*const enum TokenKind of u8:\n(.*?)(?=^\s*(?:struct|const enum|def) |\Z)", text)
    if not match:
        raise SystemExit("complete TokenKind enum projection is missing")
    return [line.strip() for line in match.group(1).splitlines()
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", line.strip())]


def operator_match_blocks(text: str) -> list[list[str]]:
    lines = text.splitlines()
    blocks = []
    for index, line in enumerate(lines):
        if not re.search(r"\bwhen operator:$", line.strip()):
            continue
        base_indent = len(line) - len(line.lstrip())
        arms = []
        for arm in lines[index + 1:]:
            if not arm.strip():
                continue
            indent = len(arm) - len(arm.lstrip())
            if indent <= base_indent:
                break
            if indent != base_indent + 4:
                raise SystemExit("comparison match contains a nested or malformed arm")
            arms.append(arm.strip())
        blocks.append(arms)
    return blocks


expected_arms = [
    "Lexer::TokenKind.EqEq | Lexer::TokenKind.BangEq | Lexer::TokenKind.Lt | Lexer::TokenKind.Gt | Lexer::TokenKind.LtEq | Lexer::TokenKind.GtEq -> true",
    "_ -> false",
]


def validate_classifier(text: str) -> None:
    section = function_section(text, "is_comparison")
    if operator_match_blocks(section) != [expected_arms] * EXPECTED_PRODUCTION_MATCHES:
        raise SystemExit("comparison classifier contract and implementation differ from the exact match")


helper_text = HELPER.read_text()
validate_classifier(helper_text)
if operator_match_blocks(POSITIVE.read_text()) != [expected_arms]:
    raise SystemExit("comparison proof does not state the exact closed TokenKind set")
if enum_variants(TOKENS.read_text()) != enum_variants(TOKEN_PROJECTION.read_text()):
    raise SystemExit("proof TokenKind projection differs from the production enum order")
for path in (STATIC_ASSERT, LITERAL_COMPARISON):
    source = path.read_text()
    if 'include "./comparison_operator_policy.elisa"' not in source:
        raise SystemExit(f"{path.name} no longer imports the proved comparison classifier")
    if source.count("ComparisonOperatorPolicy::is_comparison(operator)") != 1:
        raise SystemExit(f"{path.name} must use the shared comparison classifier once")
    if "operator == TokenKind.EqEq or operator == TokenKind.BangEq" in source:
        raise SystemExit(f"{path.name} retains the duplicated comparison-token OR chain")

positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()
if 'include "./parser_token_kind_projection.elisa"' not in positive_text:
    raise SystemExit("positive proof no longer includes the complete TokenKind projection")
if 'include "../../src/semantic/comparison_operator_policy.elisa"' not in positive_text:
    raise SystemExit("positive proof no longer imports the production policy")
if 'include "./comparison_operator_policy.elisa"' not in negative_text:
    raise SystemExit("negative claims no longer challenge the source-linked proof")
positive_names = {
    "source_classifier_has_exact_comparison_set",
    "every_comparison_operator_is_classified",
    "non_comparison_operators_remain_unclassified",
}
negative_names = {
    "logical_and_is_a_comparison_operator",
    "assignment_is_a_comparison_operator",
}
for name in positive_names:
    if not re.search(rf"(?m)^def {re.escape(name)}\(", positive_text):
        raise SystemExit(f"positive proof is missing {name}")
for name in negative_names:
    if not re.search(rf"(?m)^def {re.escape(name)}\(", negative_text):
        raise SystemExit(f"negative proof is missing {name}")

mutations = (
    helper_text.replace("Lexer::TokenKind.EqEq", "Lexer::TokenKind.Assign", 1),
    helper_text.replace("_ -> false", "_ -> true", 1),
    helper_text.replace("Lexer::TokenKind.LtEq", "Lexer::TokenKind.RangeLt", 1),
    helper_text.replace("\n                _ -> false", "\n                Lexer::TokenKind.And -> true\n                _ -> false", 1),
)
for mutated in mutations:
    try:
        validate_classifier(mutated)
    except SystemExit:
        pass
    else:
        raise SystemExit("comparison-token source mutation escaped the exact-match check")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("comparison-operator proof requires a strict proof build")

stage1_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
source_closure = source_include_closure([POSITIVE, NEGATIVE, STATIC_ASSERT, LITERAL_COMPARISON])
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV",
    stage1_product, stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
    TOKENS, TOKEN_PROJECTION, *source_closure,
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=PROOF_TIMEOUT_SECONDS)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["obligations"] == positive["summary"]["proven"] == len(positive_names)
assert not positive["findings"]
assert positive_names <= {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert positive == run(POSITIVE)[1], "comparison-operator proof report changed across identical runs"

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product
print(json.dumps({
    "admitted": True,
    "scope": "closed comparison-token classification shared by static-assert and literal-range checks",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
