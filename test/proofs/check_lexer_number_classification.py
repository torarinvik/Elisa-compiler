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
SEPARATOR_MODEL = HERE / "lexer_number_separator_model.elisa"
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
require_fragments(function_section(numbers_text, "classify_number_input"), (
    "if c == '_' and lexer.position > 0:",
    "previous: char = lexer.source[lexer.position - 1].char()",
    "following: char = lexer.peek(1)",
    "return NumberClass.DecimalSeparator if previous.is_digit() and following.is_digit()",
    "return NumberClass.HexSeparator if previous.is_hex_digit() and following.is_hex_digit()",
), "contextual underscore classification")
underscore_source = compact(function_section(numbers_text, "classify_number_input"))
underscore_steps = (
    "if c == '_' and lexer.position > 0:",
    "previous: char = lexer.source[lexer.position - 1].char()",
    "following: char = lexer.peek(1)",
    "return NumberClass.DecimalSeparator if previous.is_digit() and following.is_digit()",
    "return NumberClass.HexSeparator if previous.is_hex_digit() and following.is_hex_digit()",
)
underscore_positions = [underscore_source.find(compact(step)) for step in underscore_steps]
if any(position < 0 for position in underscore_positions) or underscore_positions != sorted(underscore_positions):
    raise SystemExit("contextual underscore classification no longer preserves its guarded decimal-first order")
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
    "adjacent_decimal_digits_are_decimal_separators",
    "adjacent_hex_letters_are_hex_separators",
    "decimal_digits_take_precedence_over_the_hex_class",
    "a_mixed_decimal_and_hex_pair_uses_the_hex_class",
    "a_pair_without_a_shared_digit_class_is_other",
}
negative_names = {
    "false_claim_unicode_digit_is_ascii_digit",
    "false_claim_exponent_marker_is_plain_hex_alpha",
    "false_claim_decimal_point_is_a_fraction_opening_class",
    "false_claim_plus_sign_is_a_valid_exponent_marker_class",
    "false_claim_decimal_digit_pair_is_a_hex_separator",
    "false_claim_mixed_decimal_hex_pair_is_a_decimal_separator",
}
for path, expected in ((POSITIVE, positive_names), (NEGATIVE, negative_names)):
    proof_text = path.read_text()
    if declarations(path) != expected:
        raise SystemExit(f"{path.name} proof declaration inventory changed")
    if 'include "./lexer_number_separator_model.elisa"' not in proof_text:
        raise SystemExit(f"{path.name} no longer includes the adjacent-character separator model")
if 'include "../../src/lexer/lexer_number_classification.elisa"' not in SEPARATOR_MODEL.read_text():
    raise SystemExit("underscore model no longer uses the production character predicates")
separator_model = compact(function_section(SEPARATOR_MODEL.read_text(), "numeric_separator_model"))
separator_condition = "LexerNumberClassification::is_decimal_digit(previous) and LexerNumberClassification::is_decimal_digit(following)"
hex_condition = "LexerNumberClassification::is_hex_digit(previous) and LexerNumberClassification::is_hex_digit(following)"
expected_separator_model = compact(
    "def numeric_separator_model(previous: char, following: char) -> LexerNumberClassification::NumberClass: "
    f"ensure result == (LexerNumberClassification::NumberClass.DecimalSeparator if {separator_condition} "
    f"else LexerNumberClassification::NumberClass.HexSeparator if {hex_condition} "
    "else LexerNumberClassification::NumberClass.Other) "
    f"return LexerNumberClassification::NumberClass.DecimalSeparator if {separator_condition} "
    f"else LexerNumberClassification::NumberClass.HexSeparator if {hex_condition} "
    "else LexerNumberClassification::NumberClass.Other"
)
if separator_model != expected_separator_model:
    raise SystemExit("underscore proof model no longer has the decimal-first/hex-second decision table")

positive_shapes = {
    "every_character_uses_its_exact_closed_class": "ensure result == true return match character: '0'..='9': LexerNumberClassification::classify_char(character) == LexerNumberClassification::NumberClass.Digit 'e' | 'E': LexerNumberClassification::classify_char(character) == LexerNumberClassification::NumberClass.ExpMarkOther 'a'..='d' | 'f' | 'A'..='D' | 'F': LexerNumberClassification::classify_char(character) == LexerNumberClassification::NumberClass.HexAlpha '.': LexerNumberClassification::classify_char(character) == LexerNumberClassification::NumberClass.OtherDot '+' | '-': LexerNumberClassification::classify_char(character) == LexerNumberClassification::NumberClass.Sign _: LexerNumberClassification::classify_char(character) == LexerNumberClassification::NumberClass.Other",
    "decimal_digit_predicate_agrees_with_the_digit_class": "ensure result == true return LexerNumberClassification::is_decimal_digit(character) == (LexerNumberClassification::classify_char(character) == LexerNumberClassification::NumberClass.Digit)",
    "decimal_digit_predicate_is_exact": "ensure result == true return LexerNumberClassification::is_decimal_digit(character) == (character in '0'..='9')",
    "hexadecimal_digit_predicate_is_exact": "ensure result == true return LexerNumberClassification::is_hex_digit(character) == (character in '0'..='9' or character in 'a'..='f' or character in 'A'..='F')",
    "exponent_mark_is_hex_digit_but_not_hex_alpha": "ensure result == true return LexerNumberClassification::is_hex_digit('e') and LexerNumberClassification::classify_char('e') == LexerNumberClassification::NumberClass.ExpMarkOther",
    "non_ascii_decimal_digit_is_outside_ascii_number_classes": "ensure result == true return not LexerNumberClassification::is_decimal_digit('١') and LexerNumberClassification::classify_char('١') == LexerNumberClassification::NumberClass.Other",
    "contextual_classes_are_not_static_character_classes": "ensure result == true return LexerNumberClassification::classify_char(character) != LexerNumberClassification::NumberClass.ExpMarkValid and LexerNumberClassification::classify_char(character) != LexerNumberClassification::NumberClass.FractionDot and LexerNumberClassification::classify_char(character) != LexerNumberClassification::NumberClass.HexPrefix and LexerNumberClassification::classify_char(character) != LexerNumberClassification::NumberClass.DecimalSeparator and LexerNumberClassification::classify_char(character) != LexerNumberClassification::NumberClass.HexSeparator",
    "adjacent_decimal_digits_are_decimal_separators": "requires LexerNumberClassification::is_decimal_digit(previous) and LexerNumberClassification::is_decimal_digit(following) ensure result == true return numeric_separator_model(previous, following) == LexerNumberClassification::NumberClass.DecimalSeparator",
    "adjacent_hex_letters_are_hex_separators": "requires previous in 'a'..='f' and following in 'A'..='F' ensure result == true return numeric_separator_model(previous, following) == LexerNumberClassification::NumberClass.HexSeparator",
    "decimal_digits_take_precedence_over_the_hex_class": "requires LexerNumberClassification::is_decimal_digit(previous) and LexerNumberClassification::is_decimal_digit(following) ensure result == true return numeric_separator_model(previous, following) == LexerNumberClassification::NumberClass.DecimalSeparator",
    "a_mixed_decimal_and_hex_pair_uses_the_hex_class": "ensure result == true return numeric_separator_model('1', 'a') == LexerNumberClassification::NumberClass.HexSeparator",
    "a_pair_without_a_shared_digit_class_is_other": "ensure result == true return numeric_separator_model('g', '9') == LexerNumberClassification::NumberClass.Other",
}
negative_shapes = {
    "false_claim_unicode_digit_is_ascii_digit": "ensure result == true return LexerNumberClassification::is_decimal_digit('١')",
    "false_claim_exponent_marker_is_plain_hex_alpha": "ensure result == true return LexerNumberClassification::classify_char('e') == LexerNumberClassification::NumberClass.HexAlpha",
    "false_claim_decimal_point_is_a_fraction_opening_class": "ensure result == true return LexerNumberClassification::classify_char('.') == LexerNumberClassification::NumberClass.FractionDot",
    "false_claim_plus_sign_is_a_valid_exponent_marker_class": "ensure result == true return LexerNumberClassification::classify_char('+') == LexerNumberClassification::NumberClass.ExpMarkValid",
    "false_claim_decimal_digit_pair_is_a_hex_separator": "ensure result == true return numeric_separator_model('1', '9') == LexerNumberClassification::NumberClass.HexSeparator",
    "false_claim_mixed_decimal_hex_pair_is_a_decimal_separator": "ensure result == true return numeric_separator_model('1', 'a') == LexerNumberClassification::NumberClass.DecimalSeparator",
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
assert positive["summary"]["declarations"] == len(positive_names) + 4
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "numeric-character proof report changed across repeated runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert positive_names | {"classify_char", "is_decimal_digit", "is_hex_digit", "numeric_separator_model"} <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["verification_state"] == "disproved"
assert negative["summary"]["declarations"] == len(negative_names) + 4
assert {(row["kind"], row["name"]) for row in negative["findings"]} == {
    ("ensure-unproven", name) for name in negative_names
}
assert all(row["status"] == "disproved" and row["counterexample_found"]
           for row in negative["findings"])
assert {"classify_char", "is_decimal_digit", "is_hex_digit"} <= {
    row["name"] for row in negative["declaration_details"] if row.get("verified")
}
assert "numeric_separator_model" in {
    row["name"] for row in negative["declaration_details"] if row.get("verified")
}
assert product == require_current_product(BIN, PROVER)
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "numeric-character proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "closed ASCII character classes, digit predicates, and decimal-first contextual underscore classification used by the numeric lexer FSM",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": compiler.get("source_revision"),
    "inputs_sha256": hashes_before,
}, sort_keys=True))
