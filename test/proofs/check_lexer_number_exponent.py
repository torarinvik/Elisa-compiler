"""Admit the numeric exponent-tail predicate against the production lexer paths."""
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
HELPER = ROOT / "src/lexer/lexer_number_exponent.elisa"
LEXER = ROOT / "src/lexer/lexer_numbers.elisa"
POSITIVE = HERE / "lexer_number_exponent.elisa"
NEGATIVE = HERE / "lexer_number_exponent_rejected.elisa"

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


def require_ordered(body: str, fragments: tuple[str, ...], label: str) -> None:
    compact_body = compact(body)
    positions = [compact_body.find(compact(fragment)) for fragment in fragments]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        raise SystemExit(f"{label} no longer follows the checked exponent-tail path")


helper_text = HELPER.read_text()
helper_fn = compact(function_section(helper_text, "follows"))
if compact(
    "ensure result == (first in '0'..='9' or ((first == '+' or first == '-') and second in '0'..='9'))"
) not in helper_fn:
    raise SystemExit("production exponent-tail contract changed")
if compact(
    "return when first: '+' | '-' -> second in '0'..='9' _ -> first in '0'..='9'"
) not in helper_fn:
    raise SystemExit("production exponent-tail decision table changed")

lexer_text = LEXER.read_text()
if 'include "./lexer_number_exponent.elisa"' not in lexer_text:
    raise SystemExit("numeric scanner no longer imports the proved exponent-tail predicate")
require_ordered(function_section(lexer_text, "exponent_follows"), (
    "exponent_next_char: char = lexer.peek(1)",
    "return LexerNumberExponent::follows(exponent_next_char, lexer.peek(2))",
), "number-state exponent classification")
classify_source = function_section(lexer_text, "classify_number_input")
require_ordered(classify_source, (
    "-> ValidExponent if (c == 'e' or c == 'E') and lexer.exponent_follows()",
    "-> Plain",
    "ValidExponent:",
    "=> NumberClass.ExpMarkValid",
), "number-state exponent classification")
require_ordered(function_section(lexer_text, "should_read_float_fraction"), (
    "CheckExponent:",
    "exp_sign_or_digit: char = lexer.peek(2)",
    "-> Answer(LexerNumberExponent::follows(exp_sign_or_digit, lexer.peek(3)))",
), "decimal-fraction exponent classification")
read_number = compact(function_section(lexer_text, "read_number"))
exponent_cases = (
    "Whole, NumberClass.ExpMarkValid: lexer <- lexer.advance_char() lexer.number_kind <- TokenKind.FloatLit -> ExpLead",
    "Fraction, NumberClass.ExpMarkValid: lexer <- lexer.advance_char() -> ExpLead",
    "ExpLead, NumberClass.Sign: lexer <- lexer.advance_char() -> ExpDigits",
    "ExpLead, NumberClass.Digit | NumberClass.HexPrefix: lexer <- lexer.advance_char() -> ExpDigits",
    "ExpDigits, NumberClass.Digit | NumberClass.HexPrefix | NumberClass.DecimalSeparator: lexer <- lexer.advance_char() -> ExpDigits",
)
case_positions = [read_number.find(compact(case)) for case in exponent_cases]
if any(position < 0 for position in case_positions) or case_positions != sorted(case_positions):
    raise SystemExit("exponent-token consumption no longer follows the checked exponent-tail path")

positive_names = {
    "every_decimal_digit_starts_a_valid_exponent_tail",
    "signed_exponent_tail_matches_the_following_digit",
    "plus_sign_followed_by_digit_is_valid",
    "minus_sign_followed_by_digit_is_valid",
    "either_sign_without_a_digit_is_invalid",
    "a_non_digit_non_sign_cannot_start_an_exponent_tail",
    "exponent_marker_letter_is_not_a_digit_tail",
    "non_ascii_decimal_digit_is_not_an_exponent_digit",
}
negative_names = {
    "a_sign_without_a_digit_is_valid",
    "an_exponent_marker_is_a_valid_unsigned_tail",
    "a_non_ascii_decimal_digit_is_valid_as_a_tail",
}


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


for path, expected in ((POSITIVE, positive_names), (NEGATIVE, negative_names)):
    if declarations(path) != expected:
        raise SystemExit(f"{path.name} proof declaration inventory changed")
    if 'include "../../src/lexer/lexer_number_exponent.elisa"' not in path.read_text():
        raise SystemExit(f"{path.name} no longer proves the production exponent helper")

positive_shapes = {
    "every_decimal_digit_starts_a_valid_exponent_tail": "requires character in '0'..='9' ensure result == true return LexerNumberExponent::follows(character, 'x')",
    "signed_exponent_tail_matches_the_following_digit": "requires sign == '+' or sign == '-' ensure result == (following in '0'..='9') return LexerNumberExponent::follows(sign, following)",
    "plus_sign_followed_by_digit_is_valid": "ensure result == true return LexerNumberExponent::follows('+', '9')",
    "minus_sign_followed_by_digit_is_valid": "ensure result == true return LexerNumberExponent::follows('-', '0')",
    "either_sign_without_a_digit_is_invalid": "requires sign == '+' or sign == '-' ensure result == true return not LexerNumberExponent::follows(sign, 'x')",
    "a_non_digit_non_sign_cannot_start_an_exponent_tail": "requires not (first in '0'..='9') and first != '+' and first != '-' ensure result == true return not LexerNumberExponent::follows(first, second)",
    "exponent_marker_letter_is_not_a_digit_tail": "ensure result == true return not LexerNumberExponent::follows('e', '5')",
    "non_ascii_decimal_digit_is_not_an_exponent_digit": "ensure result == true return not LexerNumberExponent::follows('١', 'x')",
}
negative_shapes = {
    "a_sign_without_a_digit_is_valid": "ensure result == true return LexerNumberExponent::follows('+', 'x')",
    "an_exponent_marker_is_a_valid_unsigned_tail": "ensure result == true return LexerNumberExponent::follows('e', '5')",
    "a_non_ascii_decimal_digit_is_valid_as_a_tail": "ensure result == true return LexerNumberExponent::follows('١', 'x')",
}
for path, shapes in ((POSITIVE, positive_shapes), (NEGATIVE, negative_shapes)):
    proof_text = path.read_text()
    for name, shape in shapes.items():
        if compact(shape) not in compact(function_section(proof_text, name)):
            raise SystemExit(f"{name} no longer states the intended exponent-tail law")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("lexer exponent proof requires a strict proof build")
compiler = product["compiler"]
stage1_product = Path(compiler["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", HELPER, LEXER,
    POSITIVE, NEGATIVE, *source_include_closure([POSITIVE, NEGATIVE, LEXER]),
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    result = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                            text=True, timeout=60)
    report = json.loads(result.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return result.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["declarations"] == len(positive_names) + 1
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "lexer exponent proof report changed across repeated runs"
assert positive_names | {"follows"} <= {
    item["name"] for item in positive["declaration_details"] if item.get("verified")
}

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["verification_state"] == "disproved"
assert negative["summary"]["declarations"] == len(negative_names) + 1
assert {(finding["kind"], finding["name"]) for finding in negative["findings"]} == {
    ("ensure-unproven", name) for name in negative_names
}
assert all(finding["status"] == "disproved" and finding["counterexample_found"]
           for finding in negative["findings"])
assert "follows" in {item["name"] for item in negative["declaration_details"] if item.get("verified")}
assert product == require_current_product(BIN, PROVER)
if hashes_before != {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}:
    raise SystemExit("lexer exponent proof inputs changed during replay")

print(json.dumps({
    "admitted": True,
    "scope": "unsigned and signed exponent-tail recognition at both numeric lexer call sites",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": compiler.get("source_revision"),
    "inputs_sha256": hashes_before,
}, sort_keys=True))
