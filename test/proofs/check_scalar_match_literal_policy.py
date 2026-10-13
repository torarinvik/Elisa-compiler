"""Bind the scalar-match compatibility proof to the parser and production decision."""
from __future__ import annotations

import argparse
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
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve()
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
SOURCE = ROOT / "src/semantic/scalar_match_literal_policy.elisa"
CONSUMER = ROOT / "src/semantic/resolve_types_match.elisa"
PARSER = ROOT / "src/parser/parser_stmt_pattern.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
POSITIVE = HERE / "scalar_match_literal_policy.elisa"
NEGATIVE = HERE / "scalar_match_literal_policy_rejected.elisa"

parser = argparse.ArgumentParser()
parser.add_argument("--source-only", action="store_true",
                    help="check source and fixture bindings without invoking the proof product")
ARGS = parser.parse_args()

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(source: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in source.splitlines())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)(?:ghost )?def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}(?:ghost )?def [A-Za-z_][A-Za-z0-9_]*\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def declarations(source: str) -> set[str]:
    return set(re.findall(r"(?m)^[ \t]*(?:ghost )?def ([A-Za-z_][A-Za-z0-9_]*)\(", source))


source_text = SOURCE.read_text()
consumer_text = CONSUMER.read_text()
semantic_text = SEMANTIC.read_text()
parser_text = PARSER.read_text()
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()

expected_classifier = '''
def starts_like_numeric_literal(text: sview) -> bool can[Abort.Panic]:
    ensure result == (text.length > 0 and (
        (text[0] >= ASCII_DIGIT_ZERO and text[0] <= ASCII_DIGIT_NINE)
        or text[0] == ASCII_MINUS
    ))
    can Abort.Panic:
        return false if text.length == 0
        first: u8 = text[0]
        return (first >= ASCII_DIGIT_ZERO and first <= ASCII_DIGIT_NINE) or first == ASCII_MINUS
'''
expected_family_policy = '''
def valid_for_family(text: sview, scalar_family: sview) -> bool can[Abort.Panic]:
    ensure result == (scalar_family == "string" or starts_like_numeric_literal(text))
    can Abort.Panic:
        return true if scalar_family == "string"
        return starts_like_numeric_literal(text)
'''
expected_pattern_policy = '''
def pattern_valid(pattern: Pattern, scalar_family: sview) -> bool can[Abort.Panic]:
    can Abort.Panic:
        return match pattern:
            Pattern.Wildcard: true
            Pattern.Literal(text): valid_for_family(text, scalar_family)
            Pattern.Or(options): all option in options where pattern_valid(option, scalar_family)
            Pattern.Range(range_lo, range_hi, range_inclusive): scalar_family == "int"
            Pattern.Pin(binding_name): scalar_family == "int"
            _: false
'''
expected_consumer_wrapper = '''
def scalar_match_pattern_valid(pattern: Ast::Pattern, scalar_family: sview) -> bool:
    ensure result == SemanticScalarMatchLiteralPolicy::pattern_valid(pattern, scalar_family)
    can Abort.Panic:
        return SemanticScalarMatchLiteralPolicy::pattern_valid(pattern, scalar_family)
'''
if "moduleSemanticScalarMatchLiteralPolicy:" not in compact(source_text):
    raise SystemExit("scalar literal policy moved outside its source-linked module")
if compact(function_section(source_text, "starts_like_numeric_literal")) != compact(expected_classifier):
    raise SystemExit("first-byte classifier changed without updating its proof contract")
if compact(function_section(source_text, "valid_for_family")) != compact(expected_family_policy):
    raise SystemExit("family classifier changed without updating its proof contract")
if compact(function_section(source_text, "pattern_valid")) != compact(expected_pattern_policy):
    raise SystemExit("scalar match pattern cases changed without updating their source-bound proofs")
if "constASCII_DIGIT_ZERO:u8=48" not in compact(source_text) or \
        "constASCII_DIGIT_NINE:u8=57" not in compact(source_text) or \
        "constASCII_MINUS:u8=45" not in compact(source_text):
    raise SystemExit("ASCII first-byte constants changed without updating the source proof")
if consumer_text.count('include "./scalar_match_literal_policy.elisa"') != 1:
    raise SystemExit("scalar match resolver must import the proved literal policy exactly once")
if compact(function_section(consumer_text, "scalar_match_pattern_valid")) != compact(expected_consumer_wrapper):
    raise SystemExit("semantic scalar match checker no longer delegates to the proved pattern policy")
if "notscalar_match_pattern_valid(arm.pattern,scalar_family)" not in compact(
        function_section(consumer_text, "check_scalar_match_arm_types")):
    raise SystemExit("scalar match arm diagnostics no longer consume the proved pattern policy")
if semantic_text.count('include "./resolve_types_match.elisa"') != 1:
    raise SystemExit("semantic root must include the scalar match resolver exactly once")
pattern_parser = compact(function_section(parser_text, "parse_pattern_primary"))
shared_literal_group = "TokenKind.IntLit|TokenKind.HexLit|TokenKind.FloatLit|TokenKind.StringLit|TokenKind.CharLit|TokenKind.True|TokenKind.False|TokenKind.Null:"
if shared_literal_group not in pattern_parser:
    raise SystemExit("literal-token provenance boundary changed; revisit the compatibility proof scope")
literal_start = pattern_parser.index(shared_literal_group)
error_arm = pattern_parser.find("TokenKind.Error:", literal_start)
if error_arm < 0:
    raise SystemExit("could not find the end of the shared literal-pattern arm")
literal_arm = pattern_parser[literal_start:error_arm]
if "Lexer::text_or_empty(token,parser.source,parser.source_length)" not in literal_arm or \
        "return(Ast::Pattern.Literal(lit_text))" not in literal_arm:
    raise SystemExit("shared literal arm no longer stores token text in Pattern.Literal")
if "ifkind==TokenKind.CharLit" not in literal_arm or "ifkind==TokenKind.StringLit" in literal_arm:
    raise SystemExit("parser no longer has the documented char-only quoting distinction")
if 'include "../../src/semantic/scalar_match_literal_policy.elisa"' not in positive_text or \
        'include "./scalar_match_literal_policy.elisa"' not in negative_text:
    raise SystemExit("scalar literal proofs must import the production classifier")

positive_names = {
    "first_byte_classifier_matches_its_exact_specification",
    "family_classifier_matches_its_exact_specification",
    "digit_and_minus_prefixes_are_integer_shaped",
    "empty_and_non_numeric_prefixes_are_not_integer_shaped",
    "strings_accept_literal_text_regardless_of_its_first_byte",
    "integer_family_uses_the_first_byte_screen",
    "numeric_looking_literal_text_is_accepted_for_both_families",
    "wildcard_patterns_are_valid_for_both_scalar_families",
    "literal_patterns_use_the_family_specific_first_byte_rule",
    "integer_ranges_and_pins_are_limited_to_integer_family",
    "every_or_pattern_alternative_must_be_valid",
    "unsupported_top_level_pattern_kinds_are_rejected",
}
negative_names = {
    "false_claim_empty_text_is_integer_shaped",
    "false_claim_plus_prefix_is_integer_shaped",
    "false_claim_text_literal_is_rejected_for_strings",
    "false_claim_letter_prefix_is_valid_for_integer_family",
    "false_claim_string_range_is_valid",
    "false_claim_or_pattern_ignores_an_invalid_alternative",
    "false_claim_numeric_looking_string_text_is_rejected_for_int",
}
if declarations(positive_text) != positive_names or declarations(negative_text) != negative_names:
    raise SystemExit("scalar match literal proof inventory changed")

positive_cases = {
    "first_byte_classifier_matches_its_exact_specification": '''
def first_byte_classifier_matches_its_exact_specification(text: sview) -> bool can[Abort.Panic]:
    ensure result == true
    can Abort.Panic:
        return SemanticScalarMatchLiteralPolicy::starts_like_numeric_literal(text) == (
            text.length > 0 and (
                (text[0] >= SemanticScalarMatchLiteralPolicy::ASCII_DIGIT_ZERO
                    and text[0] <= SemanticScalarMatchLiteralPolicy::ASCII_DIGIT_NINE)
                or text[0] == SemanticScalarMatchLiteralPolicy::ASCII_MINUS
            )
        )
''',
    "family_classifier_matches_its_exact_specification": '''
def family_classifier_matches_its_exact_specification(text: sview, scalar_family: sview) -> bool can[Abort.Panic]:
    ensure result == true
    can Abort.Panic:
        return SemanticScalarMatchLiteralPolicy::valid_for_family(text, scalar_family) == (
            scalar_family == "string" or (
                text.length > 0 and (
                    (text[0] >= SemanticScalarMatchLiteralPolicy::ASCII_DIGIT_ZERO
                        and text[0] <= SemanticScalarMatchLiteralPolicy::ASCII_DIGIT_NINE)
                    or text[0] == SemanticScalarMatchLiteralPolicy::ASCII_MINUS
                )
            )
        )
''',
    "digit_and_minus_prefixes_are_integer_shaped": '''
def digit_and_minus_prefixes_are_integer_shaped() -> bool can[Abort.Panic]:
    ensure result == true
    can Abort.Panic:
        return SemanticScalarMatchLiteralPolicy::starts_like_numeric_literal("0")
            and SemanticScalarMatchLiteralPolicy::starts_like_numeric_literal("9tail")
            and SemanticScalarMatchLiteralPolicy::starts_like_numeric_literal("-")
            and SemanticScalarMatchLiteralPolicy::starts_like_numeric_literal("-text")
''',
    "empty_and_non_numeric_prefixes_are_not_integer_shaped": '''
def empty_and_non_numeric_prefixes_are_not_integer_shaped() -> bool can[Abort.Panic]:
    ensure result == true
    can Abort.Panic:
        return not SemanticScalarMatchLiteralPolicy::starts_like_numeric_literal("")
            and not SemanticScalarMatchLiteralPolicy::starts_like_numeric_literal("+1")
            and not SemanticScalarMatchLiteralPolicy::starts_like_numeric_literal(".5")
            and not SemanticScalarMatchLiteralPolicy::starts_like_numeric_literal("word")
''',
    "strings_accept_literal_text_regardless_of_its_first_byte": '''
def strings_accept_literal_text_regardless_of_its_first_byte() -> bool can[Abort.Panic]:
    ensure result == true
    can Abort.Panic:
        return SemanticScalarMatchLiteralPolicy::valid_for_family("", "string")
            and SemanticScalarMatchLiteralPolicy::valid_for_family("word", "string")
            and SemanticScalarMatchLiteralPolicy::valid_for_family("42", "string")
''',
    "integer_family_uses_the_first_byte_screen": '''
def integer_family_uses_the_first_byte_screen() -> bool can[Abort.Panic]:
    ensure result == true
    can Abort.Panic:
        return SemanticScalarMatchLiteralPolicy::valid_for_family("7suffix", "int")
            and not SemanticScalarMatchLiteralPolicy::valid_for_family("word", "int")
''',
    "numeric_looking_literal_text_is_accepted_for_both_families": '''
def numeric_looking_literal_text_is_accepted_for_both_families() -> bool can[Abort.Panic]:
    ensure result == true
    can Abort.Panic:
        shared_text_pattern: Pattern = Pattern.Literal("42")
        return SemanticScalarMatchLiteralPolicy::pattern_valid(shared_text_pattern, "int")
            and SemanticScalarMatchLiteralPolicy::pattern_valid(shared_text_pattern, "string")
''',
    "wildcard_patterns_are_valid_for_both_scalar_families": '''
def wildcard_patterns_are_valid_for_both_scalar_families() -> bool can[Abort.Panic]:
    ensure result == true
    can Abort.Panic:
        return SemanticScalarMatchLiteralPolicy::pattern_valid(Pattern.Wildcard, "int")
            and SemanticScalarMatchLiteralPolicy::pattern_valid(Pattern.Wildcard, "string")
''',
    "literal_patterns_use_the_family_specific_first_byte_rule": '''
def literal_patterns_use_the_family_specific_first_byte_rule() -> bool can[Abort.Panic]:
    ensure result == true
    can Abort.Panic:
        return SemanticScalarMatchLiteralPolicy::pattern_valid(Pattern.Literal("8tail"), "int")
            and not SemanticScalarMatchLiteralPolicy::pattern_valid(Pattern.Literal("word"), "int")
            and SemanticScalarMatchLiteralPolicy::pattern_valid(Pattern.Literal("word"), "string")
''',
    "integer_ranges_and_pins_are_limited_to_integer_family": '''
def integer_ranges_and_pins_are_limited_to_integer_family() -> bool can[Abort.Panic]:
    ensure result == true
    can Abort.Panic:
        return SemanticScalarMatchLiteralPolicy::pattern_valid(Pattern.Range("0", "9", false), "int")
            and SemanticScalarMatchLiteralPolicy::pattern_valid(Pattern.Pin("target"), "int")
            and not SemanticScalarMatchLiteralPolicy::pattern_valid(Pattern.Range("0", "9", false), "string")
            and not SemanticScalarMatchLiteralPolicy::pattern_valid(Pattern.Pin("target"), "string")
''',
    "every_or_pattern_alternative_must_be_valid": '''
def every_or_pattern_alternative_must_be_valid() -> bool can[Abort.Panic]:
    ensure result == true
    can Abort.Panic:
        integer_options: darray[Pattern] = [Pattern.Literal("3"), Pattern.Pin("target")]
        mixed_options: darray[Pattern] = [Pattern.Literal("3"), Pattern.Pin("target")]
        return SemanticScalarMatchLiteralPolicy::pattern_valid(Pattern.Or(integer_options), "int")
            and not SemanticScalarMatchLiteralPolicy::pattern_valid(Pattern.Or(mixed_options), "string")
''',
    "unsupported_top_level_pattern_kinds_are_rejected": '''
def unsupported_top_level_pattern_kinds_are_rejected() -> bool can[Abort.Panic]:
    ensure result == true
    can Abort.Panic:
        return not SemanticScalarMatchLiteralPolicy::pattern_valid(Pattern.Binding("value"), "int")
            and not SemanticScalarMatchLiteralPolicy::pattern_valid(Pattern.Variant("E.V", []), "int")
            and not SemanticScalarMatchLiteralPolicy::pattern_valid(Pattern.Binding("value"), "string")
''',
}
negative_cases = {
    "false_claim_empty_text_is_integer_shaped": '''
def false_claim_empty_text_is_integer_shaped() -> bool can[Abort.Panic]:
    ensure result == true
    can Abort.Panic:
        return SemanticScalarMatchLiteralPolicy::starts_like_numeric_literal("")
''',
    "false_claim_plus_prefix_is_integer_shaped": '''
def false_claim_plus_prefix_is_integer_shaped() -> bool can[Abort.Panic]:
    ensure result == true
    can Abort.Panic:
        return SemanticScalarMatchLiteralPolicy::starts_like_numeric_literal("+1")
''',
    "false_claim_text_literal_is_rejected_for_strings": '''
def false_claim_text_literal_is_rejected_for_strings() -> bool can[Abort.Panic]:
    ensure result == true
    can Abort.Panic:
        return not SemanticScalarMatchLiteralPolicy::valid_for_family("word", "string")
''',
    "false_claim_letter_prefix_is_valid_for_integer_family": '''
def false_claim_letter_prefix_is_valid_for_integer_family() -> bool can[Abort.Panic]:
    ensure result == true
    can Abort.Panic:
        return SemanticScalarMatchLiteralPolicy::valid_for_family("word", "int")
''',
    "false_claim_string_range_is_valid": '''
def false_claim_string_range_is_valid() -> bool can[Abort.Panic]:
    ensure result == true
    can Abort.Panic:
        return SemanticScalarMatchLiteralPolicy::pattern_valid(Pattern.Range("0", "9", false), "string")
''',
    "false_claim_or_pattern_ignores_an_invalid_alternative": '''
def false_claim_or_pattern_ignores_an_invalid_alternative() -> bool can[Abort.Panic]:
    ensure result == true
    can Abort.Panic:
        options: darray[Pattern] = [Pattern.Literal("1"), Pattern.Pin("target")]
        return SemanticScalarMatchLiteralPolicy::pattern_valid(Pattern.Or(options), "string")
''',
    "false_claim_numeric_looking_string_text_is_rejected_for_int": '''
def false_claim_numeric_looking_string_text_is_rejected_for_int() -> bool can[Abort.Panic]:
    ensure result == true
    can Abort.Panic:
        string_origin_text: Pattern = Pattern.Literal("42")
        return not SemanticScalarMatchLiteralPolicy::pattern_valid(string_origin_text, "int")
''',
}
for name, expected in positive_cases.items():
    if compact(function_section(positive_text, name)) != compact(expected):
        raise SystemExit(f"positive proof {name} changed without updating the source-bound gate")
for name, expected in negative_cases.items():
    if compact(function_section(negative_text, name)) != compact(expected):
        raise SystemExit(f"false-claim control {name} changed without updating the source-bound gate")

source_closure = source_include_closure([POSITIVE, NEGATIVE])
if ARGS.source_only:
    print(json.dumps({"scope": "current literal-text compatibility; token kind is erased",
                      "source_bound": True, "positive": len(positive_names),
                      "false_claim_controls": len(negative_names)}, sort_keys=True))
    raise SystemExit(0)

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("scalar match literal proofs require a strict proof build")

stage1_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", SOURCE, CONSUMER, PARSER, SEMANTIC,
    POSITIVE, NEGATIVE, *source_closure,
]))
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
assert positive["summary"]["declarations"] == len(positive_names)
assert positive["summary"]["obligations"] == positive["summary"]["proven"]
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "scalar match literal proof report changed across identical runs"
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == positive_names

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert negative["summary"]["declarations"] == len(positive_names) + len(negative_names)
assert negative["summary"]["proven"] + len(negative_names) == negative["summary"]["obligations"]
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert not negative_names & {row["name"] for row in negative["declaration_details"] if row.get("verified")}

hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_after == hashes_before, "proof inputs changed during admission"
