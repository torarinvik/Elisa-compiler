"""Replay the source-linked proofs for the lexer's UTF-8 scalar decoders."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from collections import Counter

from utf8_proof_reports import validate_utf8_reports
from utf8_decoder_expectations import (
    check_decoder,
    helper_constants,
    helper_contracts,
    aggregator_includes,
    two_byte_guard,
    expected_identifier_start_returns,
    expected_identifier_char_returns,
)
from utf8_scalar_proof_expectations import (
    expected_start_returns,
    sequence_guard_models,
    two_byte_formula,
    latin1_return,
    payload_bound_models,
    sequence_rejected_cases,
    sequence_truncated_cases,
    three_guard_return,
    four_guard_return,
    three_byte_scalar_guard_premises,
    three_byte_scalar_decode,
    three_byte_scalar_predicate,
    four_byte_source_guards,
    four_byte_source_decode,
    four_byte_scalar_guard_premises,
    four_byte_scalar_decode,
    negative_scalar_claims,
)
from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
POSITIVE = HERE / "lexer_utf8_codepoint.elisa"
TWO_BYTE_RANGES = HERE / "lexer_utf8_two_byte_ranges.elisa"
WIDE_POSITIVE = HERE / "lexer_utf8_codepoint_wide.elisa"
THREE_BYTE_SCALAR_BOUNDS = HERE / "lexer_utf8_three_byte_scalar_bounds.elisa"
THREE_BYTE_SURROGATE_REJECTED = HERE / "lexer_utf8_three_byte_surrogate_rejected.elisa"
FOUR_BYTE_SCALAR_BOUNDS = HERE / "lexer_utf8_four_byte_scalar_bounds.elisa"
FOUR_BYTE_SCALAR_REJECTED = HERE / "lexer_utf8_four_byte_scalar_bounds_rejected.elisa"
PAYLOAD_BOUNDS = HERE / "lexer_utf8_payload_bounds.elisa"
GUARDS_POSITIVE = HERE / "lexer_utf8_codepoint_guards.elisa"
SEQUENCE_GUARDS_POSITIVE = HERE / "lexer_utf8_sequence_guards.elisa"
SEQUENCE_F4_GUARD_POSITIVE = HERE / "lexer_utf8_sequence_f4_guard.elisa"
SEQUENCE_REJECTED = HERE / "lexer_utf8_sequence_rejected.elisa"
SEQUENCE_TRUNCATED = HERE / "lexer_utf8_sequence_truncated.elisa"
NEGATIVE = HERE / "lexer_utf8_codepoint_rejected.elisa"
FACADE = ROOT / "src/lexer/lexer.elisa"
CORE = ROOT / "src/lexer/lexer_core.elisa"
HELPER = ROOT / "src/lexer/lexer_utf8_codepoint.elisa"
CONSTANTS = ROOT / "src/lexer/lexer_utf8_codepoint_constants.elisa"
TWO_BYTE_HELPER = ROOT / "src/lexer/lexer_utf8_codepoint_two.elisa"
WIDE_HELPER = ROOT / "src/lexer/lexer_utf8_codepoint_wide.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def function_body(source: str, name: str, following: str) -> str:
    try:
        return source.split(f"def {name}(", 1)[1].split(f"def {following}(", 1)[0]
    except IndexError as error:
        raise SystemExit(f"missing source function {name}") from error


constant_text = CONSTANTS.read_text()
two_byte_helper_text = TWO_BYTE_HELPER.read_text()
wide_helper_text = WIDE_HELPER.read_text()
facade_text = FACADE.read_text()
core_text = CORE.read_text()
positive_text = POSITIVE.read_text()
two_byte_ranges_text = TWO_BYTE_RANGES.read_text()
negative_text = NEGATIVE.read_text()
payload_bounds_text = PAYLOAD_BOUNDS.read_text()
four_byte_scalar_bounds_text = FOUR_BYTE_SCALAR_BOUNDS.read_text()
four_byte_scalar_rejected_text = FOUR_BYTE_SCALAR_REJECTED.read_text()
three_byte_scalar_bounds_text = THREE_BYTE_SCALAR_BOUNDS.read_text()
three_byte_surrogate_rejected_text = THREE_BYTE_SURROGATE_REJECTED.read_text()

for name, value in helper_constants.items():
    if f"const {name}: i64 = {value}" not in constant_text:
        raise SystemExit(f"{name} no longer names the proof-checked UTF-8 bound or place value")

for name, fragments in helper_contracts.items():
    owning_source = two_byte_helper_text if name.endswith("_two") else wide_helper_text
    body = owning_source.split(f"def {name}(", 1)[1].split("\n@inline(always)", 1)[0]
    if not all(fragment in body for fragment in fragments):
        raise SystemExit(f"{name} no longer has the proof-checked UTF-8 contract")

helper_include = 'include "./lexer_utf8_codepoint.elisa"'
core_include = 'include "./lexer_core.elisa"'
if helper_include not in facade_text or core_include not in facade_text:
    raise SystemExit("lexer facade no longer includes the UTF-8 contracts and decoder core")
if facade_text.index(helper_include) > facade_text.index(core_include):
    raise SystemExit("UTF-8 contracts must be included before the lexer decoder core")
aggregator_text = HELPER.read_text()
if not all(item in aggregator_text for item in aggregator_includes) or [aggregator_text.index(item) for item in aggregator_includes] != sorted(aggregator_text.index(item) for item in aggregator_includes):
    raise SystemExit("production UTF-8 aggregator must include shared constants and both proof units in order")
if 'include "../../src/lexer/lexer_utf8_codepoint_constants.elisa"' not in positive_text or 'include "../../src/lexer/lexer_utf8_codepoint_two.elisa"' not in positive_text:
    raise SystemExit("two-byte proof no longer imports its production constants and helper")
if 'include "../../src/lexer/lexer_utf8_codepoint_constants.elisa"' not in two_byte_ranges_text:
    raise SystemExit("two-byte range lemmas no longer use the production decoder constants")
if 'include "../../src/lexer/lexer_utf8_codepoint_two.elisa"' in two_byte_ranges_text:
    raise SystemExit("two-byte range lemmas must prove the source formula independently of helper summaries")
wide_positive_text = WIDE_POSITIVE.read_text()
if 'include "../../src/lexer/lexer_utf8_codepoint_constants.elisa"' not in wide_positive_text or 'include "../../src/lexer/lexer_utf8_codepoint_wide.elisa"' not in wide_positive_text:
    raise SystemExit("wide proof no longer imports its production constants and helper")
if "include \"../../src/lexer/lexer_utf8_codepoint_wide.elisa\"" in payload_bounds_text:
    raise SystemExit("payload arithmetic lemmas must remain independent of the helper contracts they justify")
guards_positive_text = GUARDS_POSITIVE.read_text()
if 'include "../../src/lexer/lexer_utf8_codepoint_constants.elisa"' not in guards_positive_text:
    raise SystemExit("decoder guard proof no longer imports the production UTF-8 constants")
sequence_guards_text = SEQUENCE_GUARDS_POSITIVE.read_text()
sequence_f4_guard_text = SEQUENCE_F4_GUARD_POSITIVE.read_text()
sequence_rejected_text = SEQUENCE_REJECTED.read_text()
sequence_truncated_text = SEQUENCE_TRUNCATED.read_text()
for proof_text in (sequence_guards_text, sequence_f4_guard_text, sequence_rejected_text, sequence_truncated_text):
    if 'include "../../src/lexer/lexer_utf8_codepoint_constants.elisa"' not in proof_text:
        raise SystemExit("sequence guard proof no longer imports the production UTF-8 constants")
if 'def is_latin1_letter_codepoint(value: int) -> bool:' not in core_text:
    raise SystemExit("Latin-1 identifier classification must receive the decoded scalar value")

identifier_start = function_body(core_text, "unicode_identifier_start_width", "unicode_identifier_char_width")
identifier_char = function_body(core_text, "unicode_identifier_char_width", "starts_unicode_identifier")
two_byte_latin1 = "two_byte_codepoint.is_latin1_letter_codepoint()"
two_byte_letter = "two_byte_codepoint.is_unicode2_letter_codepoint()"
if two_byte_latin1 not in identifier_start or two_byte_letter not in identifier_start:
    raise SystemExit("two-byte identifier paths no longer use the proved scalar decoder")
two_byte_decode = "two_byte_codepoint: int = lexer_decode_utf8_two(first.i64(), second.i64()).int()"
if (two_byte_guard not in identifier_start or identifier_start.count(two_byte_decode) != 1 or
        identifier_start.index(two_byte_guard) > identifier_start.index(two_byte_decode)):
    raise SystemExit("two-byte identifier-start path no longer uses one guarded scalar decode")
if (two_byte_guard not in identifier_char or identifier_char.count(two_byte_decode) != 1 or
        "two_byte_codepoint.is_unicode2_digit_codepoint()" not in identifier_char):
    raise SystemExit("two-byte digit path no longer uses the proved scalar decoder")
if not all(fragment in identifier_start for fragment in (
    "first.i64() >= UTF8_TWO_BYTE_LEAD_MIN",
    "first.i64() <= UTF8_TWO_BYTE_LEAD_MAX",
    "first.i64() <= UTF8_TWO_BYTE_LATIN1_LEAD_MAX",
    "second.is_utf8_continuation()",
)):
    raise SystemExit("two-byte identifier paths no longer enforce lead and continuation bounds")
if int(helper_constants["UTF8_TWO_BYTE_LATIN1_LEAD_MAX"], 16) + 1 != int(
        helper_constants["UTF8_TWO_BYTE_UNICODE2_LEAD_MIN"], 16):
    raise SystemExit("two-byte identifier branch boundary no longer partitions Latin-1 and Unicode-2 leads")
if not (identifier_start.index(two_byte_guard) < identifier_start.index(two_byte_decode) <
        identifier_start.index("if first.i64() <= UTF8_TWO_BYTE_LATIN1_LEAD_MAX:") <
        identifier_start.index(two_byte_latin1) <
        identifier_start.index("else:", identifier_start.index("if first.i64() <= UTF8_TWO_BYTE_LATIN1_LEAD_MAX:")) <
        identifier_start.index(two_byte_letter)):
    raise SystemExit("two-byte identifier-start classification no longer follows its guarded scalar decode")
if not all(fragment in identifier_char for fragment in (
    "first.i64() >= UTF8_TWO_BYTE_ARABIC_DIGIT_LEAD_MIN",
    "first.i64() <= UTF8_TWO_BYTE_LEAD_MAX",
    "second.is_utf8_continuation()",
)):
    raise SystemExit("two-byte digit path no longer enforces lead and continuation bounds")
if not (identifier_char.index(two_byte_guard) < identifier_char.index(two_byte_decode) <
        identifier_char.index("if first.i64() <= UTF8_TWO_BYTE_LATIN1_LEAD_MAX:") <
        identifier_char.index("two_byte_codepoint.is_latin1_letter_codepoint()") <
        identifier_char.index("else:", identifier_char.index("if first.i64() <= UTF8_TWO_BYTE_LATIN1_LEAD_MAX:")) <
        identifier_char.index("two_byte_codepoint.is_unicode2_letter_codepoint()") <
        identifier_char.index("first.i64() >= UTF8_TWO_BYTE_ARABIC_DIGIT_LEAD_MIN and two_byte_codepoint.is_unicode2_digit_codepoint()")):
    raise SystemExit("two-byte classification no longer uses one guarded decoded scalar")

identifier_start_returns = tuple(
    line.strip() for line in identifier_start.splitlines()
    if "return" in line and not line.lstrip().startswith("#")
)
if identifier_start_returns != expected_identifier_start_returns:
    raise SystemExit("Unicode identifier-start width has an unexpected or unguarded return")
if identifier_start.count("lexer.source[") != 2:
    raise SystemExit("Unicode identifier-start width gained or lost a byte load")
if not (identifier_start.index("return 0 if lexer.position >= lexer.source_length") <
        identifier_start.index("remaining: usize = lexer.source_length - lexer.position") <
        identifier_start.index("first: u8 = lexer.source[lexer.position]") <
        identifier_start.index("has_second: bool = remaining > 1") <
        identifier_start.index("second: u8 = lexer.source[lexer.position + 1] if has_second else 0")):
    raise SystemExit("Unicode identifier-start width must guard its cursor before byte loads")

identifier_char_returns = tuple(
    line.strip() for line in identifier_char.splitlines()
    if "return" in line and not line.lstrip().startswith("#")
)
if identifier_char_returns != expected_identifier_char_returns:
    raise SystemExit("Unicode identifier-character width has an unexpected or unguarded return")
if identifier_char.count("lexer.source[") != 2:
    raise SystemExit("Unicode identifier-character width gained or lost a byte load")
if not (identifier_char.index("return 0 if lexer.position >= lexer.source_length") <
        identifier_char.index("remaining: usize = lexer.source_length - lexer.position") <
        identifier_char.index("first: u8 = lexer.source[lexer.position]") <
        identifier_char.index("has_second: bool = remaining > 1") <
        identifier_char.index("second: u8 = lexer.source[lexer.position + 1] if has_second else 0")):
    raise SystemExit("Unicode identifier-character width must guard its cursor before byte loads")

advance_identifier = function_body(core_text, "advance_latin1_identifier_char", "valid_suffix")
advance_identifier_compact = "".join(advance_identifier.split())
expected_advance_identifier = "".join("".join((
    "lexer: lmut Lexer):",
    "width: u8 = lexer.unicode_identifier_char_width()",
    "match width:",
    "0:",
    "pass",
    "1:",
    "lexer <- lexer.advance_char()",
    "_:",
    "lexer <- lexer.advance_chars(width)",
)).split())
if not advance_identifier_compact.endswith("@inline(always)") or \
        advance_identifier_compact[:-len("@inline(always)")] != expected_advance_identifier:
    raise SystemExit("Unicode identifier advancement no longer consumes exactly the classified byte width")

three = function_body(core_text, "three_byte_codepoint_at_cursor", "four_byte_codepoint_at_cursor")
four = function_body(core_text, "four_byte_codepoint_at_cursor", "is_utf8_continuation")
continuation = function_body(core_text, "is_utf8_continuation", "starts_valid_utf8_sequence")
starts_valid = function_body(core_text, "starts_valid_utf8_sequence", "unicode_identifier_start_width")


check_decoder(
    three,
    indices=("second_byte_index", "third_byte_index"),
    lead_guard="return -1 if first.i64() < UTF8_THREE_BYTE_LEAD_MIN or first.i64() > UTF8_THREE_BYTE_LEAD_MAX",
    continuations=("second.i64() < UTF8_CONTINUATION_MIN or second.i64() > UTF8_CONTINUATION_MAX or third.i64() < UTF8_CONTINUATION_MIN or third.i64() > UTF8_CONTINUATION_MAX",),
    special_guards=(
        "first.i64() == UTF8_THREE_BYTE_LEAD_MIN and second.i64() < UTF8_E0_SECOND_MIN",
        "first.i64() == UTF8_SURROGATE_LEAD and second.i64() > UTF8_ED_SECOND_MAX",
    ),
    helper_call="return lexer_decode_utf8_three(first.i64() - UTF8_THREE_BYTE_LEAD_MIN, second.i64() - UTF8_CONTINUATION_MIN, third.i64() - UTF8_CONTINUATION_MIN).int()",
)
check_decoder(
    four,
    indices=("second_byte_index", "third_byte_index", "fourth_byte_index"),
    lead_guard="return -1 if first.i64() < UTF8_FOUR_BYTE_LEAD_MIN or first.i64() > UTF8_FOUR_BYTE_LEAD_MAX",
    continuations=(
        "second.i64() < UTF8_CONTINUATION_MIN or second.i64() > UTF8_CONTINUATION_MAX or third.i64() < UTF8_CONTINUATION_MIN or third.i64() > UTF8_CONTINUATION_MAX or fourth.i64() < UTF8_CONTINUATION_MIN or fourth.i64() > UTF8_CONTINUATION_MAX",
    ),
    special_guards=(
        "first.i64() == UTF8_FOUR_BYTE_LEAD_MIN and second.i64() < UTF8_F0_SECOND_MIN",
        "first.i64() == UTF8_FOUR_BYTE_LEAD_MAX and second.i64() > UTF8_F4_SECOND_MAX",
    ),
    helper_call="return lexer_decode_utf8_four(first.i64() - UTF8_FOUR_BYTE_LEAD_MIN, second.i64() - UTF8_CONTINUATION_MIN, third.i64() - UTF8_CONTINUATION_MIN, fourth.i64() - UTF8_CONTINUATION_MIN).int()",
)

if "return byte.i64() >= UTF8_CONTINUATION_MIN and byte.i64() <= UTF8_CONTINUATION_MAX" not in continuation:
    raise SystemExit("UTF-8 continuation predicate no longer uses the shared byte bounds")
observed_start_returns = tuple(
    line.strip() for line in starts_valid.splitlines()
    if "return" in line and not line.lstrip().startswith("#")
)
if observed_start_returns != expected_start_returns:
    raise SystemExit("UTF-8 sequence validator has an unexpected or unguarded return")
if starts_valid.count("lexer.source[") != 21:
    raise SystemExit("UTF-8 sequence validator gained or lost a byte load")
start_bound = "return false if lexer.position >= lexer.source_length"
remaining_assignment = "remaining: usize = lexer.source_length - lexer.position"
first_load = "first: u8 = lexer.source[lexer.position]"
if not (starts_valid.index(start_bound) < starts_valid.index(remaining_assignment) < starts_valid.index(first_load)):
    raise SystemExit("UTF-8 sequence validator must establish a nonempty bounded cursor before reading")


def sequence_guard_predicate(source_return: str) -> str:
    safety, lead = source_return.split(" return if ", 1)
    for index, byte_name in enumerate(("first", "second", "third", "fourth")):
        source_call = f"is_utf8_continuation(lexer.source[lexer.position + {index}])"
        safety = safety.replace(
            source_call,
            f"({byte_name} >= UTF8_CONTINUATION_MIN and {byte_name} <= UTF8_CONTINUATION_MAX)",
        )
    for index, byte_name in enumerate(("first", "second", "third", "fourth")):
        safety = safety.replace(f"lexer.source[lexer.position + {index}].i64()", byte_name)
        safety = safety.replace(f"lexer.source[lexer.position + {index}]", byte_name)
    safety = safety.replace("first.i64()", "first")
    lead = lead.replace("first.i64()", "first")
    return f"{safety} and ({lead})"


def proof_function_section(source: str, name: str) -> str:
    try:
        return f"def {name}(" + source.split(f"def {name}(", 1)[1].split("\ndef ", 1)[0]
    except IndexError as error:
        raise SystemExit(f"missing sequence guard theorem {name}") from error


if f"ensure result == {two_byte_formula}" not in two_byte_helper_text or f"return {two_byte_formula}" not in two_byte_helper_text:
    raise SystemExit("two-byte decoder no longer implements the formula used by its range proofs")

two_byte_range_models = {
    "latin1_byte_pair_decode_range": (
        "latin1_byte_pair_decode_range(first: i64, second: i64) -> bool:",
        "requires first >= UTF8_TWO_BYTE_LEAD_MIN and first <= UTF8_TWO_BYTE_LATIN1_LEAD_MAX",
        "requires second >= UTF8_CONTINUATION_MIN and second <= UTF8_CONTINUATION_MAX",
        f"decoded: i64 = {two_byte_formula}",
        "return decoded >= UTF8_TWO_BYTE_SCALAR_MIN and decoded <= 255",
    ),
    "unicode2_byte_pair_decode_range": (
        "unicode2_byte_pair_decode_range(first: i64, second: i64) -> bool:",
        "requires first >= UTF8_TWO_BYTE_UNICODE2_LEAD_MIN and first <= UTF8_TWO_BYTE_LEAD_MAX",
        "requires second >= UTF8_CONTINUATION_MIN and second <= UTF8_CONTINUATION_MAX",
        f"decoded: i64 = {two_byte_formula}",
        "return decoded >= 256 and decoded <= UTF8_TWO_BYTE_SCALAR_MAX",
    ),
    "arabic_indic_digit_byte_pair_decode_range": (
        "arabic_indic_digit_byte_pair_decode_range(first: i64, second: i64) -> bool:",
        "requires first == 217 and second >= 160 and second <= 169",
        f"decoded: i64 = {two_byte_formula}",
        "return decoded >= 1632 and decoded <= 1641",
    ),
    "extended_arabic_indic_digit_byte_pair_decode_range": (
        "extended_arabic_indic_digit_byte_pair_decode_range(first: i64, second: i64) -> bool:",
        "requires first == 219 and second >= 176 and second <= 185",
        f"decoded: i64 = {two_byte_formula}",
        "return decoded >= 1776 and decoded <= 1785",
    ),
    "nko_digit_byte_pair_decode_range": (
        "nko_digit_byte_pair_decode_range(first: i64, second: i64) -> bool:",
        "requires first == 223 and second >= 128 and second <= 137",
        f"decoded: i64 = {two_byte_formula}",
        "return decoded >= 1984 and decoded <= 1993",
    ),
}
for name, fragments in two_byte_range_models.items():
    section = proof_function_section(two_byte_ranges_text, name)
    if any(fragment not in section for fragment in fragments):
        raise SystemExit(f"{name} no longer proves the production two-byte scalar interval")
if {name for name in re.findall(r"^def ([A-Za-z_][A-Za-z0-9_]*)\(", two_byte_ranges_text, re.MULTILINE)} != set(two_byte_range_models):
    raise SystemExit("two-byte range proof contains a missing or unreviewed theorem")

latin1_classifier = function_body(core_text, "is_latin1_letter_codepoint", "is_unicode2_letter_codepoint")
digit_classifier = function_body(core_text, "is_unicode2_digit_codepoint", "three_byte_codepoint_at_cursor")
digit_return = "return value in 0x0660..0x0669 or value in 0x06F0..0x06F9 or value in 0x07C0..0x07C9"
if latin1_return not in latin1_classifier or digit_return not in digit_classifier:
    raise SystemExit("two-byte scalar classes no longer match their proof-checked Unicode intervals")


for name, fragments in payload_bound_models.items():
    section = proof_function_section(payload_bounds_text, name)
    if any(fragment not in section for fragment in fragments):
        raise SystemExit(f"{name} no longer proves the source-derived payload arithmetic")
if {name for name in re.findall(r"^def ([A-Za-z_][A-Za-z0-9_]*)\(", payload_bounds_text, re.MULTILINE)} != set(payload_bound_models):
    raise SystemExit("payload-bound proof contains a missing or unreviewed theorem")


for name, source_return_index, parameters, consequences in sequence_guard_models:
    proof_text = sequence_f4_guard_text if source_return_index == 7 else sequence_guards_text
    section = proof_function_section(proof_text, name)
    if f"{name}({parameters}) -> bool:" not in proof_text:
        raise SystemExit(f"{name} no longer uses the source-checked byte and remaining parameters")
    if any(line.strip().startswith("requires ") for line in section.splitlines()):
        raise SystemExit(f"{name} must establish its guard implications without assumptions")
    expected_predicate = sequence_guard_predicate(expected_start_returns[source_return_index])
    observed_returns = [line.strip() for line in section.splitlines() if line.strip().startswith("return ")]
    if observed_returns != [f"return {expected_predicate}"]:
        raise SystemExit(f"{name} no longer mirrors its exact production UTF-8 acceptance arm")
    if f"ensure result == ({expected_predicate})" not in section:
        raise SystemExit(f"{name} no longer proves the exact acceptance predicate")
    if not all(f"ensure result implies {claim}" in section for claim in consequences):
        raise SystemExit(f"{name} no longer proves every byte and cursor guard consequence")

sequence_acceptance_predicate = " or ".join(
    f"({sequence_guard_predicate(source_return)})"
    for source_return in expected_start_returns[1:-1]
)
def check_sequence_rejection_cases(proof_text: str, cases: tuple) -> None:
    for name, inputs_for_case in cases:
        section = proof_function_section(proof_text, name)
        if f"{name}() -> bool:" not in proof_text:
            raise SystemExit(f"{name} no longer checks a concrete malformed UTF-8 input")
        if any(line.strip().startswith("requires ") for line in section.splitlines()):
            raise SystemExit(f"{name} must reject its malformed UTF-8 input without assumptions")
        expected_expression = sequence_acceptance_predicate
        for variable, value in zip(("remaining", "first", "second", "third", "fourth"), inputs_for_case):
            expected_expression = re.sub(rf"\b{variable}\b", str(value), expected_expression)
        observed_returns = [line.strip() for line in section.splitlines() if line.strip().startswith("return ")]
        if name in {"reject_truncated_two_byte_sequence", "reject_truncated_three_byte_sequence"}:
            observed_acceptance = [line.strip() for line in section.splitlines() if line.strip().startswith("accepted: bool =")]
            if observed_acceptance != [f"accepted: bool = {expected_expression}"] or observed_returns != ["return accepted"]:
                raise SystemExit(f"{name} no longer evaluates all source-derived UTF-8 acceptance arms")
        elif observed_returns != [f"return {expected_expression}"]:
            raise SystemExit(f"{name} no longer evaluates all source-derived UTF-8 acceptance arms")
        if "ensure result == false" not in section:
            raise SystemExit(f"{name} no longer proves rejection of its malformed UTF-8 input")


check_sequence_rejection_cases(sequence_rejected_text, sequence_rejected_cases)
check_sequence_rejection_cases(sequence_truncated_text, sequence_truncated_cases)

# The arithmetic decoder's exact early-return predicates are mirrored by universal guard
# contracts. Keep the model tied to the production predicates so the proof cannot drift into a
# standalone UTF-8 recognizer with different accepted bytes.
three_guard_model = function_body(guards_positive_text, "proof_three_byte_guard_contract", "proof_four_byte_guard_contract")
four_guard_model = guards_positive_text.split("def proof_four_byte_guard_contract(", 1)[1]
three_guard_returns = [line.strip() for line in three_guard_model.splitlines() if line.strip().startswith("return ")]
four_guard_returns = [line.strip() for line in four_guard_model.splitlines() if line.strip().startswith("return ")]
if three_guard_returns != [three_guard_return]:
    raise SystemExit("three-byte guard theorem no longer matches the canonical decoder predicates")
if four_guard_returns != [four_guard_return]:
    raise SystemExit("four-byte guard theorem no longer matches the canonical decoder predicates")
if f"ensure result == ({three_guard_return.removeprefix('return ')})" not in three_guard_model:
    raise SystemExit("three-byte guard theorem no longer specifies the exact accepted byte predicate")
if f"ensure result == ({four_guard_return.removeprefix('return ')})" not in four_guard_model:
    raise SystemExit("four-byte guard theorem no longer specifies the exact accepted byte predicate")

if 'include "../../src/lexer/lexer_utf8_codepoint_constants.elisa"' not in negative_text or 'include "../../src/lexer/lexer_utf8_codepoint_wide.elisa"' not in negative_text:
    raise SystemExit("negative control no longer imports the production decoder contracts")

if 'include "../../src/lexer/lexer_utf8_codepoint_constants.elisa"' not in four_byte_scalar_bounds_text or \
        'include "../../src/lexer/lexer_utf8_codepoint_wide.elisa"' not in four_byte_scalar_bounds_text:
    raise SystemExit("four-byte scalar proof no longer imports the production decoder contracts")
if 'include "../../src/lexer/lexer_utf8_codepoint_constants.elisa"' not in four_byte_scalar_rejected_text or \
        'include "../../src/lexer/lexer_utf8_codepoint_wide.elisa"' not in four_byte_scalar_rejected_text:
    raise SystemExit("four-byte scalar rejection control no longer imports the production decoder contracts")
if 'include "../../src/lexer/lexer_utf8_codepoint_constants.elisa"' not in three_byte_scalar_bounds_text or \
        'include "../../src/lexer/lexer_utf8_codepoint_wide.elisa"' not in three_byte_scalar_bounds_text:
    raise SystemExit("three-byte scalar proof no longer imports the production decoder contracts")
if 'include "../../src/lexer/lexer_utf8_codepoint_constants.elisa"' not in three_byte_surrogate_rejected_text or \
        'include "../../src/lexer/lexer_utf8_codepoint_wide.elisa"' not in three_byte_surrogate_rejected_text:
    raise SystemExit("three-byte surrogate control no longer imports the production decoder contracts")

three_byte_scalar_theorem = proof_function_section(
    three_byte_scalar_bounds_text, "valid_three_byte_sequence_decodes_to_non_surrogate_scalar")
if "def valid_three_byte_sequence_decodes_to_non_surrogate_scalar(first: i64, second: i64, third: i64) -> bool:" not in three_byte_scalar_bounds_text:
    raise SystemExit("three-byte scalar theorem no longer quantifies over the three raw UTF-8 bytes")
if any(fragment not in three_byte_scalar_theorem for fragment in three_byte_scalar_guard_premises) or \
        three_byte_scalar_theorem.count(three_byte_scalar_decode) != 1 or \
        f"ensure result == ({three_byte_scalar_predicate})" not in three_byte_scalar_theorem or \
        "ensure result implies decoded >= UTF8_THREE_BYTE_SCALAR_MIN" not in three_byte_scalar_theorem or \
        "ensure result implies decoded <= UTF8_THREE_BYTE_SCALAR_MAX" not in three_byte_scalar_theorem or \
        "ensure result implies (decoded < UNICODE_SURROGATE_MIN or decoded > UNICODE_SURROGATE_MAX)" not in three_byte_scalar_theorem:
    raise SystemExit("three-byte scalar theorem no longer proves bounds and surrogate exclusion for the exact decode")
if [line.strip() for line in three_byte_scalar_theorem.splitlines() if line.strip().startswith("requires ")] != list(three_byte_scalar_guard_premises) or \
        [line.strip() for line in three_byte_scalar_theorem.splitlines() if line.strip().startswith("return ")] != [f"return {three_byte_scalar_predicate}"]:
    raise SystemExit("three-byte scalar theorem must use exactly the production byte guards and return the claimed predicate")

three_byte_surrogate_rejected = proof_function_section(
    three_byte_surrogate_rejected_text, "an_unchecked_ed_a0_sequence_decodes_to_a_surrogate")
if "def an_unchecked_ed_a0_sequence_decodes_to_a_surrogate() -> bool:" not in three_byte_surrogate_rejected_text or \
        "lexer_decode_utf8_three(UTF8_SURROGATE_LEAD - UTF8_THREE_BYTE_LEAD_MIN, 32, 0)" not in three_byte_surrogate_rejected or \
        "ensure result == true" not in three_byte_surrogate_rejected or \
        "return decoded >= UNICODE_SURROGATE_MIN and decoded <= UNICODE_SURROGATE_MAX" not in three_byte_surrogate_rejected or \
        any(line.strip().startswith("requires ") for line in three_byte_surrogate_rejected.splitlines()):
    raise SystemExit("ED A0 surrogate control no longer demonstrates the excluded decode boundary")

four_byte_source = function_body(core_text, "four_byte_codepoint_at_cursor", "is_utf8_continuation")
if any(four_byte_source.count(fragment) != 1 for fragment in four_byte_source_guards):
    raise SystemExit("four-byte scalar proof's byte ranges or F0/F4 boundaries no longer match the production decoder")
if four_byte_source.count(four_byte_source_decode) != 1 or any(
        four_byte_source.index(left) >= four_byte_source.index(right)
        for left, right in zip(four_byte_source_guards, (*four_byte_source_guards[1:], four_byte_source_decode))):
    raise SystemExit("four-byte scalar proof no longer follows the production byte guards into its single decode call")

four_byte_scalar_theorem = proof_function_section(
    four_byte_scalar_bounds_text, "valid_four_byte_sequence_decodes_to_unicode_scalar")
if "def valid_four_byte_sequence_decodes_to_unicode_scalar(first: i64, second: i64, third: i64, fourth: i64) -> bool:" not in four_byte_scalar_bounds_text:
    raise SystemExit("four-byte scalar theorem no longer quantifies over the four raw UTF-8 bytes")
if any(fragment not in four_byte_scalar_theorem for fragment in four_byte_scalar_guard_premises) or \
        four_byte_scalar_theorem.count(four_byte_scalar_decode) != 1 or \
        "ensure result == (decoded >= UTF8_FOUR_BYTE_SCALAR_MIN and decoded <= UNICODE_SCALAR_MAX)" not in four_byte_scalar_theorem or \
        "ensure result implies decoded >= UTF8_FOUR_BYTE_SCALAR_MIN" not in four_byte_scalar_theorem or \
        "ensure result implies decoded <= UNICODE_SCALAR_MAX" not in four_byte_scalar_theorem:
    raise SystemExit("four-byte scalar theorem no longer proves the exact production decode's Unicode bounds")
if [line.strip() for line in four_byte_scalar_theorem.splitlines() if line.strip().startswith("requires ")] != list(four_byte_scalar_guard_premises):
    raise SystemExit("four-byte scalar theorem must use exactly the production decoder's byte guards as premises")
if [line.strip() for line in four_byte_scalar_theorem.splitlines() if line.strip().startswith("return ")] != [
        "return decoded >= UTF8_FOUR_BYTE_SCALAR_MIN and decoded <= UNICODE_SCALAR_MAX"]:
    raise SystemExit("four-byte scalar theorem body no longer returns the claimed range predicate")

four_byte_scalar_rejected = proof_function_section(
    four_byte_scalar_rejected_text, "an_out_of_range_f4_sequence_is_not_a_unicode_scalar")
if "def an_out_of_range_f4_sequence_is_not_a_unicode_scalar() -> bool:" not in four_byte_scalar_rejected_text or \
        "lexer_decode_utf8_four(UTF8_FOUR_BYTE_LEAD_MAX - UTF8_FOUR_BYTE_LEAD_MIN, 16, 63, 63)" not in four_byte_scalar_rejected or \
        "ensure result == false" not in four_byte_scalar_rejected or \
        "return decoded <= UNICODE_SCALAR_MAX" not in four_byte_scalar_rejected or \
        any(line.strip().startswith("requires ") for line in four_byte_scalar_rejected.splitlines()) or \
        [line.strip() for line in four_byte_scalar_rejected.splitlines() if line.strip().startswith("return ")] != [
            "return decoded <= UNICODE_SCALAR_MAX"]:
    raise SystemExit("F4 90 rejection control no longer exhibits the excluded above-maximum payload")

for name, fragments in negative_scalar_claims.items():
    section = proof_function_section(negative_text, name)
    if any(fragment not in section for fragment in fragments):
        raise SystemExit(f"{name} no longer proves the canonical boundary's false out-of-range claim")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("UTF-8 codepoint proofs require a strict proof build")

compiler = manifest["compiler"]
compiler_head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], check=True,
                               capture_output=True, text=True).stdout.strip()
if compiler_head != compiler["source_revision"]:
    raise SystemExit("proof product compiler revision does not match the checked-out compiler HEAD")

stage1_product = Path(compiler["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN,
    MANIFEST,
    MANIFEST_CHECKSUM,
    PROVER / "ELISA_COMPILER_REV",
    stage1_product,
    stage1_provenance,
    Path(__file__),
    HERE / "proof_product_gate.py",
    HERE / "utf8_decoder_expectations.py", HERE / "utf8_scalar_proof_expectations.py", HERE / "utf8_proof_reports.py",
    POSITIVE,
    TWO_BYTE_RANGES,
    WIDE_POSITIVE,
    THREE_BYTE_SCALAR_BOUNDS,
    THREE_BYTE_SURROGATE_REJECTED,
    FOUR_BYTE_SCALAR_BOUNDS,
    FOUR_BYTE_SCALAR_REJECTED,
    PAYLOAD_BOUNDS,
    GUARDS_POSITIVE,
    SEQUENCE_GUARDS_POSITIVE,
    SEQUENCE_F4_GUARD_POSITIVE,
    SEQUENCE_REJECTED,
    SEQUENCE_TRUNCATED,
    NEGATIVE,
    HELPER,
    CONSTANTS,
    TWO_BYTE_HELPER,
    WIDE_HELPER,
    FACADE,
    CORE,
    *source_include_closure([POSITIVE, TWO_BYTE_RANGES, WIDE_POSITIVE, THREE_BYTE_SCALAR_BOUNDS, THREE_BYTE_SURROGATE_REJECTED, FOUR_BYTE_SCALAR_BOUNDS, FOUR_BYTE_SCALAR_REJECTED, GUARDS_POSITIVE, SEQUENCE_GUARDS_POSITIVE, SEQUENCE_F4_GUARD_POSITIVE, SEQUENCE_REJECTED, SEQUENCE_TRUNCATED, NEGATIVE, FACADE, PAYLOAD_BOUNDS]),
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path, *, allow_constant_comparison_warnings: bool = False,
        warning_fingerprint=None) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=60)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    if allow_constant_comparison_warnings:
        # The rejection controls intentionally substitute concrete malformed bytes into the
        # complete acceptance predicate. Pin the resulting constant-folding warnings so no
        # unrelated semantic diagnostic is silently admitted with these proofs.
        observed_warnings = Counter(
            (item.get("kind_code"), item.get("severity"), item.get("message"))
            for item in report["semantic_diagnostics"]
        )
        expected_warnings = warning_fingerprint or Counter({
            (82, 2, "constant comparison is always true"): 32,
            (82, 2, "constant comparison is always false"): 31,
        })
        assert observed_warnings == expected_warnings, report["semantic_diagnostics"]
    else:
        assert not report["semantic_diagnostics"], report["semantic_diagnostics"]
    assert not report["trust"]["trusted_assumptions"]
    return process.returncode, report


validate_utf8_reports(
    FOUR_BYTE_SCALAR_BOUNDS=FOUR_BYTE_SCALAR_BOUNDS,
    FOUR_BYTE_SCALAR_REJECTED=FOUR_BYTE_SCALAR_REJECTED,
    GUARDS_POSITIVE=GUARDS_POSITIVE,
    NEGATIVE=NEGATIVE,
    PAYLOAD_BOUNDS=PAYLOAD_BOUNDS,
    POSITIVE=POSITIVE,
    SEQUENCE_F4_GUARD_POSITIVE=SEQUENCE_F4_GUARD_POSITIVE,
    SEQUENCE_GUARDS_POSITIVE=SEQUENCE_GUARDS_POSITIVE,
    SEQUENCE_REJECTED=SEQUENCE_REJECTED,
    SEQUENCE_TRUNCATED=SEQUENCE_TRUNCATED,
    THREE_BYTE_SCALAR_BOUNDS=THREE_BYTE_SCALAR_BOUNDS,
    THREE_BYTE_SURROGATE_REJECTED=THREE_BYTE_SURROGATE_REJECTED,
    TWO_BYTE_RANGES=TWO_BYTE_RANGES,
    WIDE_POSITIVE=WIDE_POSITIVE,
    hashes_before=hashes_before,
    helper_constants=helper_constants,
    inputs=inputs,
    payload_bound_models=payload_bound_models,
    run=run,
    sequence_guard_models=sequence_guard_models,
    sequence_rejected_cases=sequence_rejected_cases,
    sequence_truncated_cases=sequence_truncated_cases,
    two_byte_range_models=two_byte_range_models,
)
