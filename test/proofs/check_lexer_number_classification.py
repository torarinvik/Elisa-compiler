"""Admit source-linked proofs of the numeric lexer character classifier."""
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
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
CLASSIFIER = ROOT / "src/lexer/lexer_number_classification.elisa"
NUMBERS = ROOT / "src/lexer/lexer_numbers.elisa"
LEXER = ROOT / "src/lexer/lexer.elisa"
POSITIVE = HERE / "lexer_number_classification.elisa"
NEGATIVE = HERE / "lexer_number_classification_rejected.elisa"
PROOF_REPLAY_TIMEOUT_SECONDS = 60

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


def declarations(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


def require_fragments(source: str, fragments: tuple[str, ...], label: str) -> None:
    normalized = compact(source)
    missing = [fragment for fragment in fragments if compact(fragment) not in normalized]
    if missing:
        raise SystemExit(f"{label} no longer follows the proved numeric-character classification")


expected_classifier = (
    "ensure character in '0'..='9' implies result == NumberClass.Digit",
    "ensure character == 'e' or character == 'E' implies result == NumberClass.ExpMarkOther",
    "ensure character in 'a'..='d' or character == 'f' or character in 'A'..='D' or character == 'F' implies result == NumberClass.HexAlpha",
    "ensure character == '.' implies result == NumberClass.OtherDot",
    "ensure character == '+' or character == '-' implies result == NumberClass.Sign",
    "ensure not (character in '0'..='9' or character == 'e' or character == 'E' or character in 'a'..='d' or character == 'f' or character in 'A'..='D' or character == 'F' or character == '.' or character == '+' or character == '-') implies result == NumberClass.Other",
    "return match character: '0'..='9': NumberClass.Digit 'e' | 'E': NumberClass.ExpMarkOther 'a'..='d' | 'f' | 'A'..='D' | 'F': NumberClass.HexAlpha '.': NumberClass.OtherDot '+' | '-': NumberClass.Sign _: NumberClass.Other",
)
require_fragments(function_section(CLASSIFIER.read_text(), "classify_char"),
                  expected_classifier, "production classifier")
require_fragments(function_section(CLASSIFIER.read_text(), "is_decimal_digit"), (
    "ensure result == (character in '0'..='9')",
    "return match character: '0'..='9': true _: false",
), "production decimal-digit predicate")
require_fragments(function_section(CLASSIFIER.read_text(), "is_hex_digit"), (
    "ensure result == (character in '0'..='9' or character in 'a'..='f' or character in 'A'..='F')",
    "return match character: '0'..='9' | 'a'..='f' | 'A'..='F': true _: false",
), "production hexadecimal-digit predicate")

numbers_text = NUMBERS.read_text()
if 'include "./lexer_number_classification.elisa"' not in numbers_text:
    raise SystemExit("numeric scanner no longer imports the proved character classifier")
if compact("type NumberClass = LexerNumberClassification::NumberClass") not in compact(numbers_text):
    raise SystemExit("numeric FSM no longer uses the source classifier's enum")
require_fragments(function_section(numbers_text, "classify_number_char"), (
    "return LexerNumberClassification::classify_char(c)",
), "numeric FSM character classification")
require_fragments(function_section(numbers_text, "classify_number_input"), (
    "Plain: => classify_number_char(c)",
), "lookahead-sensitive numeric FSM classification")
require_fragments(function_section(numbers_text, "is_digit"), (
    "return LexerNumberClassification::is_decimal_digit(character)",
), "numeric FSM decimal-digit predicate")
require_fragments(function_section(numbers_text, "is_hex_digit"), (
    "return LexerNumberClassification::is_hex_digit(character)",
), "numeric FSM hexadecimal-digit predicate")
if 'include "./lexer_numbers.elisa"' not in LEXER.read_text():
    raise SystemExit("production lexer no longer imports the numeric scanner")
read_number = compact(function_section(numbers_text, "read_number"))
for variant in ("Digit", "ExpMarkValid", "ExpMarkOther", "HexAlpha", "FractionDot",
                "OtherDot", "Sign", "HexPrefix", "DecimalSeparator", "HexSeparator", "Other"):
    if f"NumberClass.{variant}" not in read_number:
        raise SystemExit(f"numeric FSM stopped consuming the {variant} class")

positive_names = {
    "every_character_uses_its_exact_closed_class",
    "decimal_digit_predicate_agrees_with_the_digit_class",
    "decimal_digit_predicate_is_exact",
    "hexadecimal_digit_predicate_is_exact",
    "exponent_mark_is_hex_digit_but_not_hex_alpha",
    "non_ascii_decimal_digit_is_outside_ascii_number_classes",
    "contextual_classes_are_not_static_character_classes",
}
negative_names = {
    "false_claim_unicode_digit_is_ascii_digit",
    "false_claim_exponent_marker_is_plain_hex_alpha",
    "false_claim_decimal_point_is_a_fraction_opening_class",
    "false_claim_plus_sign_is_a_valid_exponent_marker_class",
}
for path, expected in ((POSITIVE, positive_names), (NEGATIVE, negative_names)):
    proof_text = path.read_text()
    if declarations(path) != expected:
        raise SystemExit(f"{path.name} proof declaration inventory changed")
    if 'include "../../src/lexer/lexer_number_classification.elisa"' not in proof_text:
        raise SystemExit(f"{path.name} no longer includes the production classifier")

positive_shapes = {
    "every_character_uses_its_exact_closed_class": "ensure result == true return match character: '0'..='9': LexerNumberClassification::classify_char(character) == LexerNumberClassification::NumberClass.Digit 'e' | 'E': LexerNumberClassification::classify_char(character) == LexerNumberClassification::NumberClass.ExpMarkOther 'a'..='d' | 'f' | 'A'..='D' | 'F': LexerNumberClassification::classify_char(character) == LexerNumberClassification::NumberClass.HexAlpha '.': LexerNumberClassification::classify_char(character) == LexerNumberClassification::NumberClass.OtherDot '+' | '-': LexerNumberClassification::classify_char(character) == LexerNumberClassification::NumberClass.Sign _: LexerNumberClassification::classify_char(character) == LexerNumberClassification::NumberClass.Other",
    "decimal_digit_predicate_agrees_with_the_digit_class": "ensure result == true return LexerNumberClassification::is_decimal_digit(character) == (LexerNumberClassification::classify_char(character) == LexerNumberClassification::NumberClass.Digit)",
    "decimal_digit_predicate_is_exact": "ensure result == true return LexerNumberClassification::is_decimal_digit(character) == (character in '0'..='9')",
    "hexadecimal_digit_predicate_is_exact": "ensure result == true return LexerNumberClassification::is_hex_digit(character) == (character in '0'..='9' or character in 'a'..='f' or character in 'A'..='F')",
    "exponent_mark_is_hex_digit_but_not_hex_alpha": "ensure result == true return LexerNumberClassification::is_hex_digit('e') and LexerNumberClassification::classify_char('e') == LexerNumberClassification::NumberClass.ExpMarkOther",
    "non_ascii_decimal_digit_is_outside_ascii_number_classes": "ensure result == true return not LexerNumberClassification::is_decimal_digit('١') and LexerNumberClassification::classify_char('١') == LexerNumberClassification::NumberClass.Other",
    "contextual_classes_are_not_static_character_classes": "ensure result == true return LexerNumberClassification::classify_char(character) != LexerNumberClassification::NumberClass.ExpMarkValid and LexerNumberClassification::classify_char(character) != LexerNumberClassification::NumberClass.FractionDot and LexerNumberClassification::classify_char(character) != LexerNumberClassification::NumberClass.HexPrefix and LexerNumberClassification::classify_char(character) != LexerNumberClassification::NumberClass.DecimalSeparator and LexerNumberClassification::classify_char(character) != LexerNumberClassification::NumberClass.HexSeparator",
}
negative_shapes = {
    "false_claim_unicode_digit_is_ascii_digit": "ensure result == true return LexerNumberClassification::is_decimal_digit('١')",
    "false_claim_exponent_marker_is_plain_hex_alpha": "ensure result == true return LexerNumberClassification::classify_char('e') == LexerNumberClassification::NumberClass.HexAlpha",
    "false_claim_decimal_point_is_a_fraction_opening_class": "ensure result == true return LexerNumberClassification::classify_char('.') == LexerNumberClassification::NumberClass.FractionDot",
    "false_claim_plus_sign_is_a_valid_exponent_marker_class": "ensure result == true return LexerNumberClassification::classify_char('+') == LexerNumberClassification::NumberClass.ExpMarkValid",
}
for path, shapes in ((POSITIVE, positive_shapes), (NEGATIVE, negative_shapes)):
    proof_text = path.read_text()
    for name, shape in shapes.items():
        if compact(shape) not in compact(function_section(proof_text, name)):
            raise SystemExit(f"{name} no longer states the intended classifier law")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("numeric-character proof requires a strict proof build")
compiler = product["compiler"]
stage1_product = Path(compiler["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV",
    stage1_product, stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
    *source_include_closure([POSITIVE, NEGATIVE, LEXER]),
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=PROOF_REPLAY_TIMEOUT_SECONDS)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["declarations"] == len(positive_names) + 3
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "numeric-character proof report changed across repeated runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert positive_names | {"classify_char", "is_decimal_digit", "is_hex_digit"} <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["verification_state"] == "disproved"
assert negative["summary"]["declarations"] == len(negative_names) + 3
assert {(row["kind"], row["name"]) for row in negative["findings"]} == {
    ("ensure-unproven", name) for name in negative_names
}
assert all(row["status"] == "disproved" and row["counterexample_found"]
           for row in negative["findings"])
assert {"classify_char", "is_decimal_digit", "is_hex_digit"} <= {
    row["name"] for row in negative["declaration_details"] if row.get("verified")
}
assert product == require_current_product(BIN, PROVER)
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "numeric-character proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "closed ASCII character classification and digit predicates used by the numeric lexer FSM",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": compiler.get("source_revision"),
    "inputs_sha256": hashes_before,
}, sort_keys=True))
