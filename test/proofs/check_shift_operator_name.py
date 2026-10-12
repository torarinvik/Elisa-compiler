"""Admit the source-linked proof of the semantic shift-operator classifier."""
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
HELPER = ROOT / "src/semantic/shift_operator_name.elisa"
CHECK = ROOT / "src/semantic/check_shift_non_integral.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
TOKENS = ROOT / "src/lexer/tokens.elisa"
PROJECTION = HERE / "parser_token_kind_projection.elisa"
POSITIVE = HERE / "shift_operator_name.elisa"
NEGATIVE = HERE / "shift_operator_name_rejected.elisa"
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")

if not __debug__:
    raise SystemExit("run without Python -O")


def match_names(text: str, function_name: str) -> list[list[str]]:
    match = re.search(
        rf"(?m)^\s*def {re.escape(function_name)}\(operator: Lexer::TokenKind\) -> bool(?: can\[[^\]\n]+\])?:\n(.*?)(?=^\s*def |\Z)",
        text,
        re.DOTALL,
    )
    if not match:
        raise SystemExit(f"shift classifier {function_name} is missing")
    lines = match.group(1).splitlines()
    groups = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if re.match(r"^\s*(?:return\s+)?when operator:\s*$", line):
            indent = len(line) - len(line.lstrip())
            index += 1
            arms = []
            while index < len(lines):
                arm_line = lines[index]
                if arm_line.strip() and len(arm_line) - len(arm_line.lstrip()) <= indent:
                    break
                if arm_line.strip():
                    arms.append(arm_line.strip())
                index += 1
            if not arms or arms[-1] != "_ -> false":
                raise SystemExit(f"{function_name} lost its false pattern fallback")
            names = []
            for arm in arms[:-1]:
                if not re.fullmatch(r"Lexer::TokenKind\.[A-Za-z_][A-Za-z0-9_]*(?:\s*\|\s*Lexer::TokenKind\.[A-Za-z_][A-Za-z0-9_]*)*\s*->\s*true", arm):
                    raise SystemExit(f"{function_name} contains a non-enum or non-true match arm")
                names.extend(re.findall(r"Lexer::TokenKind\.([A-Za-z_][A-Za-z0-9_]*)", arm))
            groups.append(names)
            continue
        index += 1
    return groups


expected = ["LShift", "RShift"]
if match_names(HELPER.read_text(), "is_shift_operator") != [expected]:
    raise SystemExit("production shift-operator match differs from its exact two-token contract")
def compact(text: str) -> str:
    return "".join(text.split())

expected_contract = compact("ensure result == (operator == Lexer::TokenKind.LShift or operator == Lexer::TokenKind.RShift)")
for description, text in (("production", HELPER.read_text()), ("proof", POSITIVE.read_text())):
    if expected_contract not in compact(text):
        raise SystemExit(f"{description} contract differs from the exact two-token shift specification")
token_text = TOKENS.read_text()
for token in ("LShift", "RShift", "LShiftEq", "RShiftEq", "Plus", "Percent"):
    if not re.search(rf"(?m)^\s+{token}\s*$", token_text):
        raise SystemExit(f"TokenKind.{token} is missing from the source enum")


def enum_variants(text: str) -> list[str]:
    match = re.search(
        r"(?ms)^\s*const enum TokenKind of u8:\n(.*?)(?=^\s*(?:struct|const enum|def) |\Z)",
        text,
    )
    if not match:
        raise SystemExit("complete TokenKind enum projection is missing")
    return [line.strip() for line in match.group(1).splitlines()
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", line.strip())]


if enum_variants(token_text) != enum_variants(PROJECTION.read_text()):
    raise SystemExit("proof TokenKind projection differs from the complete production enum order")
if 'include "./shift_operator_name.elisa"' not in CHECK.read_text():
    raise SystemExit("semantic shift checker no longer imports the proved classifier")
if "ShiftOperatorName::is_shift_operator(operator)" not in CHECK.read_text():
    raise SystemExit("semantic shift checker no longer routes through the proved classifier")
if 'include "./check_shift_non_integral.elisa"' not in SEMANTIC.read_text():
    raise SystemExit("semantic shift checker is no longer in the production pipeline")
if 'include "./parser_token_kind_projection.elisa"' not in POSITIVE.read_text():
    raise SystemExit("positive proof no longer imports the verified TokenKind projection")
if f'include "../../src/semantic/shift_operator_name.elisa"' not in POSITIVE.read_text():
    raise SystemExit("positive proof no longer imports the production classifier")
if 'include "./shift_operator_name.elisa"' not in NEGATIVE.read_text():
    raise SystemExit("negative controls no longer import the positive source-linked proof")

try:
    product_manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product_manifest.get("compile_mode") != "strict":
    raise SystemExit("shift-operator proof requires a strict proof build")

stage1_product = Path(product_manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
source_closure = source_include_closure([POSITIVE, NEGATIVE, CHECK])
inputs = [
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", TOKENS, PROJECTION, SEMANTIC, *source_closure,
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
assert positive == run(POSITIVE)[1], "shift-operator proof changed across repeated runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert {
    "is_shift_operator",
    "source_shift_operator_match_is_exact",
    "both_shift_directions_are_recognized",
    "nearby_non_shift_tokens_are_excluded",
} <= verified

code, negative = run(NEGATIVE)
negative_names = {
    "addition_must_not_be_a_shift_operator",
    "compound_left_shift_must_not_be_a_plain_shift_operator",
    "modulo_must_not_be_a_shift_operator",
}
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert not negative_names & {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert require_current_product(BIN, PROVER) == product_manifest
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
print(json.dumps({
    "admitted": True,
    "scope": "exact LShift/RShift classification for non-integral shift diagnostics",
    "false_claims_rejected": sorted(negative_names),
    "positive_obligations": positive["summary"]["proven"],
    "proof_revision": product_manifest["proof"].get("head"),
    "compiler_revision": product_manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
