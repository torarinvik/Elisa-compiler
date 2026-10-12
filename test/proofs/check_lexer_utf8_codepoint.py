"""Replay the source-linked proofs for the lexer's UTF-8 scalar decoders."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from collections import Counter

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

helper_constants = {
    "UTF8_CONTINUATION_MIN": "0x80",
    "UTF8_CONTINUATION_MAX": "0xBF",
    "UTF8_TWO_BYTE_LEAD_MIN": "0xC2",
    "UTF8_TWO_BYTE_LEAD_MAX": "0xDF",
    "UTF8_TWO_BYTE_LATIN1_LEAD_MAX": "0xC3",
    "UTF8_TWO_BYTE_UNICODE2_LEAD_MIN": "0xC4",
    "UTF8_TWO_BYTE_ARABIC_DIGIT_LEAD_MIN": "0xD9",
    "UTF8_TWO_BYTE_LEAD_PAYLOAD_OFFSET": "0xC0",
    "UTF8_THREE_BYTE_LEAD_MIN": "0xE0",
    "UTF8_THREE_BYTE_LEAD_MAX": "0xEF",
    "UTF8_FOUR_BYTE_LEAD_MIN": "0xF0",
    "UTF8_FOUR_BYTE_LEAD_MAX": "0xF4",
    "UTF8_E0_SECOND_MIN": "0xA0",
    "UTF8_SURROGATE_LEAD": "0xED",
    "UTF8_ED_SECOND_MAX": "0x9F",
    "UTF8_FIRST_NON_SURROGATE_LEAD": "0xEE",
    "UTF8_F0_SECOND_MIN": "0x90",
    "UTF8_F4_SECOND_MAX": "0x8F",
    "UTF8_THREE_BYTE_SCALAR_MIN": "0x800",
    "UTF8_THREE_BYTE_SCALAR_MAX": "0xFFFF",
    "UTF8_TWO_BYTE_SCALAR_MIN": "0x80",
    "UTF8_TWO_BYTE_SCALAR_MAX": "0x7FF",
    "UNICODE_SURROGATE_MIN": "0xD800",
    "UNICODE_SURROGATE_MAX": "0xDFFF",
    "UTF8_FOUR_BYTE_SCALAR_MIN": "0x10000",
    "UNICODE_SCALAR_MAX": "0x10FFFF",
    "UTF8_TWO_BYTE_LEAD_PLACE_VALUE": "0x40",
    "UTF8_THREE_BYTE_LEAD_PLACE_VALUE": "0x1000",
    "UTF8_THREE_BYTE_SECOND_PLACE_VALUE": "0x40",
    "UTF8_FOUR_BYTE_LEAD_PLACE_VALUE": "0x40000",
    "UTF8_FOUR_BYTE_SECOND_PLACE_VALUE": "0x1000",
    "UTF8_FOUR_BYTE_THIRD_PLACE_VALUE": "0x40",
}
for name, value in helper_constants.items():
    if f"const {name}: i64 = {value}" not in constant_text:
        raise SystemExit(f"{name} no longer names the proof-checked UTF-8 bound or place value")

helper_contracts = {
    "lexer_decode_utf8_two": (
        "requires first >= UTF8_TWO_BYTE_LEAD_MIN and first <= UTF8_TWO_BYTE_LEAD_MAX",
        "requires second >= UTF8_CONTINUATION_MIN and second <= UTF8_CONTINUATION_MAX",
        "ensure result == (first - UTF8_TWO_BYTE_LEAD_PAYLOAD_OFFSET) * UTF8_TWO_BYTE_LEAD_PLACE_VALUE + second - UTF8_CONTINUATION_MIN",
        "ensure result >= UTF8_TWO_BYTE_SCALAR_MIN",
        "ensure result <= UTF8_TWO_BYTE_SCALAR_MAX",
        "ensure first == UTF8_TWO_BYTE_LEAD_MIN and second == UTF8_CONTINUATION_MIN implies result == UTF8_TWO_BYTE_SCALAR_MIN",
        "ensure first == UTF8_TWO_BYTE_LEAD_MAX and second == UTF8_CONTINUATION_MAX implies result == UTF8_TWO_BYTE_SCALAR_MAX",
    ),
    "lexer_decode_utf8_three": (
        "requires lead_payload >= 0 and lead_payload <= 15",
        "requires second_payload >= 0 and second_payload <= 63",
        "requires third_payload >= 0 and third_payload <= 63",
        "ensure result == lead_payload * UTF8_THREE_BYTE_LEAD_PLACE_VALUE + second_payload * UTF8_THREE_BYTE_SECOND_PLACE_VALUE + third_payload",
        "ensure result >= 0",
        "ensure result <= UTF8_THREE_BYTE_SCALAR_MAX",
    ),
    "lexer_decode_utf8_four": (
        "requires lead_payload >= 0 and lead_payload <= 4",
        "requires second_payload >= 0 and second_payload <= 63",
        "requires third_payload >= 0 and third_payload <= 63",
        "requires fourth_payload >= 0 and fourth_payload <= 63",
        "ensure result == lead_payload * UTF8_FOUR_BYTE_LEAD_PLACE_VALUE + second_payload * UTF8_FOUR_BYTE_SECOND_PLACE_VALUE + third_payload * UTF8_FOUR_BYTE_THIRD_PLACE_VALUE + fourth_payload",
        "ensure result >= 0",
        "ensure result <= 0x13FFFF",
    ),
}
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
aggregator_includes = (
    'include "./lexer_utf8_codepoint_constants.elisa"',
    'include "./lexer_utf8_codepoint_two.elisa"',
    'include "./lexer_utf8_codepoint_wide.elisa"',
)
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
two_byte_latin1 = "lexer_decode_utf8_two(first.i64(), second.i64()).int().is_latin1_letter_codepoint()"
two_byte_letter = "lexer_decode_utf8_two(first.i64(), second.i64()).int().is_unicode2_letter_codepoint()"
if two_byte_latin1 not in identifier_start or two_byte_letter not in identifier_start:
    raise SystemExit("two-byte identifier paths no longer use the proved scalar decoder")
two_byte_guard = (
    "if has_second and first.i64() >= UTF8_TWO_BYTE_LEAD_MIN and "
    "first.i64() <= UTF8_TWO_BYTE_LEAD_MAX and second.is_utf8_continuation():"
)
two_byte_decode = "two_byte_codepoint: int = lexer_decode_utf8_two(first.i64(), second.i64()).int()"
if (two_byte_guard not in identifier_char or identifier_char.count(two_byte_decode) != 1 or
        "two_byte_codepoint.is_unicode2_digit_codepoint()" not in identifier_char):
    raise SystemExit("two-byte digit path no longer uses the proved scalar decoder")
if not all(fragment in identifier_start for fragment in (
    "first.i64() >= UTF8_TWO_BYTE_LEAD_MIN",
    "first.i64() <= UTF8_TWO_BYTE_LATIN1_LEAD_MAX",
    "second.is_utf8_continuation()",
    "first.i64() >= UTF8_TWO_BYTE_UNICODE2_LEAD_MIN",
    "first.i64() <= UTF8_TWO_BYTE_LEAD_MAX",
)):
    raise SystemExit("two-byte identifier paths no longer enforce lead and continuation bounds")
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
expected_identifier_start_returns = (
    "0 return if lexer.position >= lexer.source_length",
    "2 return if has_second and first.i64() >= UTF8_TWO_BYTE_LEAD_MIN and first.i64() <= UTF8_TWO_BYTE_LATIN1_LEAD_MAX and second.is_utf8_continuation() and lexer_decode_utf8_two(first.i64(), second.i64()).int().is_latin1_letter_codepoint()",
    "2 return if has_second and first.i64() >= UTF8_TWO_BYTE_UNICODE2_LEAD_MIN and first.i64() <= UTF8_TWO_BYTE_LEAD_MAX and second.is_utf8_continuation() and lexer_decode_utf8_two(first.i64(), second.i64()).int().is_unicode2_letter_codepoint()",
    "3 return if first.i64() >= UTF8_THREE_BYTE_LEAD_MIN and first.i64() <= UTF8_THREE_BYTE_LEAD_MAX and lexer.three_byte_codepoint_at_cursor().is_unicode_letter_codepoint()",
    "4 return if first.i64() >= UTF8_FOUR_BYTE_LEAD_MIN and first.i64() <= UTF8_FOUR_BYTE_LEAD_MAX and lexer.four_byte_codepoint_at_cursor().is_unicode_letter_codepoint()",
    "1 return if first.int().is_latin1_letter_codepoint() and not lexer.starts_valid_utf8_sequence()",
    "return 0",
)
if identifier_start_returns != expected_identifier_start_returns:
    raise SystemExit("Unicode identifier-start width has an unexpected or unguarded return")
if identifier_start.count("lexer.source[") != 2:
    raise SystemExit("Unicode identifier-start width gained or lost a byte load")
if not (identifier_start.index("0 return if lexer.position >= lexer.source_length") <
        identifier_start.index("remaining: usize = lexer.source_length - lexer.position") <
        identifier_start.index("first: u8 = lexer.source[lexer.position]") <
        identifier_start.index("has_second: bool = remaining > 1") <
        identifier_start.index("second: u8 = lexer.source[lexer.position + 1] if has_second else 0")):
    raise SystemExit("Unicode identifier-start width must guard its cursor before byte loads")

identifier_char_returns = tuple(
    line.strip() for line in identifier_char.splitlines()
    if "return" in line and not line.lstrip().startswith("#")
)
expected_identifier_char_returns = (
    "0 return if lexer.position >= lexer.source_length",
    "2 return if two_byte_codepoint.is_latin1_letter_codepoint()",
    "2 return if two_byte_codepoint.is_unicode2_letter_codepoint()",
    "2 return if first.i64() >= UTF8_TWO_BYTE_ARABIC_DIGIT_LEAD_MIN and two_byte_codepoint.is_unicode2_digit_codepoint()",
    "3 return if three_byte_codepoint.is_unicode_letter_codepoint() or three_byte_codepoint.is_unicode_digit_codepoint()",
    "4 return if four_byte_codepoint.is_unicode_letter_codepoint() or four_byte_codepoint.is_unicode_digit_codepoint()",
    "1 return if first.int().is_latin1_letter_codepoint() and not lexer.starts_valid_utf8_sequence()",
    "return 0",
)
if identifier_char_returns != expected_identifier_char_returns:
    raise SystemExit("Unicode identifier-character width has an unexpected or unguarded return")
if identifier_char.count("lexer.source[") != 2:
    raise SystemExit("Unicode identifier-character width gained or lost a byte load")
if not (identifier_char.index("0 return if lexer.position >= lexer.source_length") <
        identifier_char.index("remaining: usize = lexer.source_length - lexer.position") <
        identifier_char.index("first: u8 = lexer.source[lexer.position]") <
        identifier_char.index("has_second: bool = remaining > 1") <
        identifier_char.index("second: u8 = lexer.source[lexer.position + 1] if has_second else 0")):
    raise SystemExit("Unicode identifier-character width must guard its cursor before byte loads")

three = function_body(core_text, "three_byte_codepoint_at_cursor", "four_byte_codepoint_at_cursor")
four = function_body(core_text, "four_byte_codepoint_at_cursor", "is_utf8_continuation")
continuation = function_body(core_text, "is_utf8_continuation", "starts_valid_utf8_sequence")
starts_valid = function_body(core_text, "starts_valid_utf8_sequence", "unicode_identifier_start_width")


def check_decoder(body: str, *, indices: tuple[str, ...], lead_guard: str,
                  continuations: tuple[str, ...], special_guards: tuple[str, ...],
                  helper_call: str) -> None:
    expected_returns = (
        "-1 return if lexer.position >= lexer.source_length",
        f"-1 return if remaining <= {indices[-1]}",
        lead_guard,
        *continuations,
        *special_guards,
        helper_call,
    )
    observed_returns = tuple(
        line.strip() for line in body.splitlines()
        if "return" in line and not line.lstrip().startswith("#")
    )
    if observed_returns != expected_returns:
        raise SystemExit("UTF-8 decoder has an unexpected or unguarded return")
    if observed_returns[-1] != helper_call:
        raise SystemExit("UTF-8 helper call must be the decoder's final return")

    ordered = (
        "-1 return if lexer.position >= lexer.source_length",
        "remaining: usize = lexer.source_length - lexer.position",
        f"-1 return if remaining <= {indices[-1]}",
        "first: u8 = lexer.source[lexer.position]",
        lead_guard,
        *[f"lexer.source[lexer.position + {index}]" for index in indices],
        *continuations,
        *special_guards,
        helper_call,
    )
    positions = [body.find(fragment) for fragment in ordered]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        raise SystemExit("UTF-8 decoder no longer checks bounds and canonical bytes before decoding")
    if body.count("lexer.source[") != len(indices) + 1:
        raise SystemExit("UTF-8 decoder gained or lost a raw source-byte load")
    if "starts_valid_utf8_sequence()" in body:
        raise SystemExit("UTF-8 decoder no longer makes its proof-checked byte conditions explicit")


check_decoder(
    three,
    indices=("second_byte_index", "third_byte_index"),
    lead_guard="-1 return if first.i64() < UTF8_THREE_BYTE_LEAD_MIN or first.i64() > UTF8_THREE_BYTE_LEAD_MAX",
    continuations=("-1 return if second.i64() < UTF8_CONTINUATION_MIN or second.i64() > UTF8_CONTINUATION_MAX or third.i64() < UTF8_CONTINUATION_MIN or third.i64() > UTF8_CONTINUATION_MAX",),
    special_guards=(
        "-1 return if first.i64() == UTF8_THREE_BYTE_LEAD_MIN and second.i64() < UTF8_E0_SECOND_MIN",
        "-1 return if first.i64() == UTF8_SURROGATE_LEAD and second.i64() > UTF8_ED_SECOND_MAX",
    ),
    helper_call="return lexer_decode_utf8_three(first.i64() - UTF8_THREE_BYTE_LEAD_MIN, second.i64() - UTF8_CONTINUATION_MIN, third.i64() - UTF8_CONTINUATION_MIN).int()",
)
check_decoder(
    four,
    indices=("second_byte_index", "third_byte_index", "fourth_byte_index"),
    lead_guard="-1 return if first.i64() < UTF8_FOUR_BYTE_LEAD_MIN or first.i64() > UTF8_FOUR_BYTE_LEAD_MAX",
    continuations=(
        "-1 return if second.i64() < UTF8_CONTINUATION_MIN or second.i64() > UTF8_CONTINUATION_MAX or third.i64() < UTF8_CONTINUATION_MIN or third.i64() > UTF8_CONTINUATION_MAX or fourth.i64() < UTF8_CONTINUATION_MIN or fourth.i64() > UTF8_CONTINUATION_MAX",
    ),
    special_guards=(
        "-1 return if first.i64() == UTF8_FOUR_BYTE_LEAD_MIN and second.i64() < UTF8_F0_SECOND_MIN",
        "-1 return if first.i64() == UTF8_FOUR_BYTE_LEAD_MAX and second.i64() > UTF8_F4_SECOND_MAX",
    ),
    helper_call="return lexer_decode_utf8_four(first.i64() - UTF8_FOUR_BYTE_LEAD_MIN, second.i64() - UTF8_CONTINUATION_MIN, third.i64() - UTF8_CONTINUATION_MIN, fourth.i64() - UTF8_CONTINUATION_MIN).int()",
)

if "return byte.i64() >= UTF8_CONTINUATION_MIN and byte.i64() <= UTF8_CONTINUATION_MAX" not in continuation:
    raise SystemExit("UTF-8 continuation predicate no longer uses the shared byte bounds")
expected_start_returns = (
    "false return if lexer.position >= lexer.source_length",
    "remaining > 1 and is_utf8_continuation(lexer.source[lexer.position + 1]) return if first.i64() >= UTF8_TWO_BYTE_LEAD_MIN and first.i64() <= UTF8_TWO_BYTE_LEAD_MAX",
    "remaining > 2 and lexer.source[lexer.position + 1].i64() >= UTF8_E0_SECOND_MIN and lexer.source[lexer.position + 1].i64() <= UTF8_CONTINUATION_MAX and is_utf8_continuation(lexer.source[lexer.position + 2]) return if first.i64() == UTF8_THREE_BYTE_LEAD_MIN",
    "remaining > 2 and is_utf8_continuation(lexer.source[lexer.position + 1]) and is_utf8_continuation(lexer.source[lexer.position + 2]) return if (first.i64() > UTF8_THREE_BYTE_LEAD_MIN and first.i64() < UTF8_SURROGATE_LEAD) or (first.i64() > UTF8_SURROGATE_LEAD and first.i64() <= UTF8_THREE_BYTE_LEAD_MAX)",
    "remaining > 2 and lexer.source[lexer.position + 1].i64() >= UTF8_CONTINUATION_MIN and lexer.source[lexer.position + 1].i64() <= UTF8_ED_SECOND_MAX and is_utf8_continuation(lexer.source[lexer.position + 2]) return if first.i64() == UTF8_SURROGATE_LEAD",
    "remaining > 3 and lexer.source[lexer.position + 1].i64() >= UTF8_F0_SECOND_MIN and lexer.source[lexer.position + 1].i64() <= UTF8_CONTINUATION_MAX and is_utf8_continuation(lexer.source[lexer.position + 2]) and is_utf8_continuation(lexer.source[lexer.position + 3]) return if first.i64() == UTF8_FOUR_BYTE_LEAD_MIN",
    "remaining > 3 and is_utf8_continuation(lexer.source[lexer.position + 1]) and is_utf8_continuation(lexer.source[lexer.position + 2]) and is_utf8_continuation(lexer.source[lexer.position + 3]) return if first.i64() > UTF8_FOUR_BYTE_LEAD_MIN and first.i64() < UTF8_FOUR_BYTE_LEAD_MAX",
    "remaining > 3 and lexer.source[lexer.position + 1].i64() >= UTF8_CONTINUATION_MIN and lexer.source[lexer.position + 1].i64() <= UTF8_F4_SECOND_MAX and is_utf8_continuation(lexer.source[lexer.position + 2]) and is_utf8_continuation(lexer.source[lexer.position + 3]) return if first.i64() == UTF8_FOUR_BYTE_LEAD_MAX",
    "return false",
)
observed_start_returns = tuple(
    line.strip() for line in starts_valid.splitlines()
    if "return" in line and not line.lstrip().startswith("#")
)
if observed_start_returns != expected_start_returns:
    raise SystemExit("UTF-8 sequence validator has an unexpected or unguarded return")
if starts_valid.count("lexer.source[") != 21:
    raise SystemExit("UTF-8 sequence validator gained or lost a byte load")
start_bound = "false return if lexer.position >= lexer.source_length"
remaining_assignment = "remaining: usize = lexer.source_length - lexer.position"
first_load = "first: u8 = lexer.source[lexer.position]"
if not (starts_valid.index(start_bound) < starts_valid.index(remaining_assignment) < starts_valid.index(first_load)):
    raise SystemExit("UTF-8 sequence validator must establish a nonempty bounded cursor before reading")

sequence_guard_models = (
    ("proof_valid_two_byte_start", 1, "remaining: i64, first: i64, second: i64", (
        "remaining > 1", "first >= UTF8_TWO_BYTE_LEAD_MIN and first <= UTF8_TWO_BYTE_LEAD_MAX",
        "second >= UTF8_CONTINUATION_MIN", "second <= UTF8_CONTINUATION_MAX")),
    ("proof_valid_three_byte_e0_start", 2, "remaining: i64, first: i64, second: i64, third: i64", (
        "remaining > 2", "first == UTF8_THREE_BYTE_LEAD_MIN", "second >= UTF8_E0_SECOND_MIN",
        "second <= UTF8_CONTINUATION_MAX", "third >= UTF8_CONTINUATION_MIN", "third <= UTF8_CONTINUATION_MAX")),
    ("proof_valid_three_byte_middle_start", 3, "remaining: i64, first: i64, second: i64, third: i64", (
        "remaining > 2", "(first > UTF8_THREE_BYTE_LEAD_MIN and first < UTF8_SURROGATE_LEAD) or (first > UTF8_SURROGATE_LEAD and first <= UTF8_THREE_BYTE_LEAD_MAX)",
        "second >= UTF8_CONTINUATION_MIN and second <= UTF8_CONTINUATION_MAX",
        "third >= UTF8_CONTINUATION_MIN and third <= UTF8_CONTINUATION_MAX")),
    ("proof_valid_three_byte_ed_start", 4, "remaining: i64, first: i64, second: i64, third: i64", (
        "remaining > 2", "first == UTF8_SURROGATE_LEAD", "second >= UTF8_CONTINUATION_MIN",
        "second <= UTF8_ED_SECOND_MAX", "third >= UTF8_CONTINUATION_MIN", "third <= UTF8_CONTINUATION_MAX")),
    ("proof_valid_four_byte_f0_start", 5, "remaining: i64, first: i64, second: i64, third: i64, fourth: i64", (
        "remaining > 3", "first == UTF8_FOUR_BYTE_LEAD_MIN", "second >= UTF8_F0_SECOND_MIN",
        "second <= UTF8_CONTINUATION_MAX", "third >= UTF8_CONTINUATION_MIN and third <= UTF8_CONTINUATION_MAX",
        "fourth >= UTF8_CONTINUATION_MIN and fourth <= UTF8_CONTINUATION_MAX")),
    ("proof_valid_four_byte_middle_start", 6, "remaining: i64, first: i64, second: i64, third: i64, fourth: i64", (
        "remaining > 3", "first > UTF8_FOUR_BYTE_LEAD_MIN and first < UTF8_FOUR_BYTE_LEAD_MAX",
        "second >= UTF8_CONTINUATION_MIN and second <= UTF8_CONTINUATION_MAX",
        "third >= UTF8_CONTINUATION_MIN and third <= UTF8_CONTINUATION_MAX",
        "fourth >= UTF8_CONTINUATION_MIN and fourth <= UTF8_CONTINUATION_MAX")),
    ("proof_valid_four_byte_f4_start", 7, "remaining: i64, first: i64, second: i64, third: i64, fourth: i64", (
        "remaining > 3", "first == UTF8_FOUR_BYTE_LEAD_MAX", "second >= UTF8_CONTINUATION_MIN",
        "second <= UTF8_F4_SECOND_MAX", "third >= UTF8_CONTINUATION_MIN and third <= UTF8_CONTINUATION_MAX",
        "fourth >= UTF8_CONTINUATION_MIN and fourth <= UTF8_CONTINUATION_MAX")),
)


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


two_byte_formula = (
    "(first - UTF8_TWO_BYTE_LEAD_PAYLOAD_OFFSET) * "
    "UTF8_TWO_BYTE_LEAD_PLACE_VALUE + second - UTF8_CONTINUATION_MIN"
)
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
latin1_return = (
    "return value == 0xAA or value == 0xB5 or value == 0xBA or "
    "value in 0xC0..0xD6 or value in 0xD8..0xF6 or value in 0xF8..0xFF"
)
digit_return = "return value in 0x0660..0x0669 or value in 0x06F0..0x06F9 or value in 0x07C0..0x07C9"
if latin1_return not in latin1_classifier or digit_return not in digit_classifier:
    raise SystemExit("two-byte scalar classes no longer match their proof-checked Unicode intervals")


payload_bound_models = {
    "three_byte_e0_boundary_range": (
        "three_byte_e0_boundary_range(second_payload: i64, third_payload: i64) -> i64:",
        "requires second_payload >= 32 and second_payload <= 63",
        "requires third_payload >= 0 and third_payload <= 63",
        "ensure result >= 2048",
        "ensure result <= 65535",
        "return second_payload * 64 + third_payload",
    ),
    "three_byte_below_surrogate_range": (
        "three_byte_below_surrogate_range(lead_payload: i64, second_payload: i64, third_payload: i64) -> i64:",
        "requires lead_payload >= 1 and lead_payload <= 12",
        "requires second_payload >= 0 and second_payload <= 63",
        "requires third_payload >= 0 and third_payload <= 63",
        "ensure result >= 2048",
        "ensure result < 55296",
        "return lead_payload * 4096 + second_payload * 64 + third_payload",
    ),
    "three_byte_ed_boundary_range": (
        "three_byte_ed_boundary_range(second_payload: i64, third_payload: i64) -> i64:",
        "requires second_payload >= 0 and second_payload <= 31",
        "requires third_payload >= 0 and third_payload <= 63",
        "ensure result < 55296",
        "return 13 * 4096 + second_payload * 64 + third_payload",
    ),
    "three_byte_above_surrogate_range": (
        "three_byte_above_surrogate_range(lead_payload: i64, second_payload: i64, third_payload: i64) -> i64:",
        "requires lead_payload >= 14 and lead_payload <= 15",
        "requires second_payload >= 0 and second_payload <= 63",
        "requires third_payload >= 0 and third_payload <= 63",
        "ensure result > 57343",
        "ensure result <= 65535",
        "return lead_payload * 4096 + second_payload * 64 + third_payload",
    ),
    "four_byte_f0_prefix_range": (
        "four_byte_f0_prefix_range(second_payload: i64) -> i64:",
        "requires second_payload >= 16 and second_payload <= 63",
        "ensure result >= 65536",
        "ensure result <= 258048",
        "return second_payload * 4096",
    ),
    "four_byte_middle_prefix_range": (
        "four_byte_middle_prefix_range(lead_payload: i64, second_payload: i64) -> i64:",
        "requires lead_payload >= 1 and lead_payload <= 3",
        "requires second_payload >= 0 and second_payload <= 63",
        "ensure result >= 262144",
        "ensure result <= 1044480",
        "return lead_payload * 262144 + second_payload * 4096",
    ),
    "four_byte_f4_prefix_range": (
        "four_byte_f4_prefix_range(second_payload: i64) -> i64:",
        "requires second_payload >= 0 and second_payload <= 15",
        "ensure result >= 1048576",
        "ensure result <= 1110016",
        "return 4 * 262144 + second_payload * 4096",
    ),
    "four_byte_suffix_range": (
        "four_byte_suffix_range(third_payload: i64, fourth_payload: i64) -> i64:",
        "requires third_payload >= 0 and third_payload <= 63",
        "requires fourth_payload >= 0 and fourth_payload <= 63",
        "ensure result >= 0",
        "ensure result <= 4095",
        "return third_payload * 64 + fourth_payload",
    ),
    "four_byte_f0_combined_scalar_range": (
        "four_byte_f0_combined_scalar_range(prefix: i64, suffix: i64) -> i64:",
        "requires prefix >= 65536 and prefix <= 258048",
        "requires suffix >= 0 and suffix <= 4095",
        "ensure result >= 65536",
        "ensure result <= 262143",
        "return prefix + suffix",
    ),
    "four_byte_middle_combined_scalar_range": (
        "four_byte_middle_combined_scalar_range(prefix: i64, suffix: i64) -> i64:",
        "requires prefix >= 262144 and prefix <= 1044480",
        "requires suffix >= 0 and suffix <= 4095",
        "ensure result >= 65536",
        "ensure result <= 1048575",
        "return prefix + suffix",
    ),
    "four_byte_f4_combined_scalar_range": (
        "four_byte_f4_combined_scalar_range(prefix: i64, suffix: i64) -> i64:",
        "requires prefix >= 1048576 and prefix <= 1110016",
        "requires suffix >= 0 and suffix <= 4095",
        "ensure result >= 1048576",
        "ensure result <= 1114111",
        "return prefix + suffix",
    ),
}
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
sequence_rejected_cases = (
    ("reject_overlong_two_byte_lead", (2, 192, 128, 0, 0)),
    ("reject_c1_overlong_two_byte_lead", (2, 193, 128, 0, 0)),
    ("reject_overlong_e0_sequence", (3, 224, 159, 128, 0)),
    ("reject_surrogate_ed_sequence", (3, 237, 160, 128, 0)),
    ("reject_overlong_f0_sequence", (4, 240, 143, 128, 128)),
    ("reject_above_maximum_f4_sequence", (4, 244, 144, 128, 128)),
    ("reject_truncated_f0_sequence", (3, 240, 144, 128, 0)),
    ("reject_malformed_three_byte_continuation", (3, 226, 40, 161, 0)),
    ("reject_lone_continuation_byte", (1, 128, 0, 0, 0)),
)
sequence_truncated_cases = (
    ("reject_truncated_two_byte_sequence", (1, 194, 0, 0, 0)),
    ("reject_truncated_three_byte_sequence", (2, 224, 160, 0, 0)),
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
three_guard_return = (
    "return first >= UTF8_THREE_BYTE_LEAD_MIN and first <= UTF8_THREE_BYTE_LEAD_MAX and "
    "second >= UTF8_CONTINUATION_MIN and second <= UTF8_CONTINUATION_MAX and "
    "third >= UTF8_CONTINUATION_MIN and third <= UTF8_CONTINUATION_MAX and "
    "(first > UTF8_THREE_BYTE_LEAD_MIN or second >= UTF8_E0_SECOND_MIN) and "
    "(first != UTF8_SURROGATE_LEAD or second <= UTF8_ED_SECOND_MAX)"
)
four_guard_return = (
    "return first >= UTF8_FOUR_BYTE_LEAD_MIN and first <= UTF8_FOUR_BYTE_LEAD_MAX and "
    "second >= UTF8_CONTINUATION_MIN and second <= UTF8_CONTINUATION_MAX and "
    "third >= UTF8_CONTINUATION_MIN and third <= UTF8_CONTINUATION_MAX and "
    "fourth >= UTF8_CONTINUATION_MIN and fourth <= UTF8_CONTINUATION_MAX and "
    "(first > UTF8_FOUR_BYTE_LEAD_MIN or second >= UTF8_F0_SECOND_MIN) and "
    "(first < UTF8_FOUR_BYTE_LEAD_MAX or second <= UTF8_F4_SECOND_MAX)"
)
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
negative_scalar_claims = {
    "a_valid_three_byte_sequence_cannot_decode_below_minimum": (
        "ensure result == false",
        "return 32 * 64 < 2048",
    ),
    "a_valid_four_byte_sequence_cannot_decode_above_maximum": (
        "ensure result == false",
        "return 4 * 262144 + 15 * 4096 + 63 * 64 + 63 > 1114111",
    ),
}
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
    POSITIVE,
    TWO_BYTE_RANGES,
    WIDE_POSITIVE,
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
    *source_include_closure([POSITIVE, TWO_BYTE_RANGES, WIDE_POSITIVE, GUARDS_POSITIVE, SEQUENCE_GUARDS_POSITIVE, SEQUENCE_F4_GUARD_POSITIVE, SEQUENCE_REJECTED, SEQUENCE_TRUNCATED, NEGATIVE, FACADE, PAYLOAD_BOUNDS]),
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


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["declarations"] == len(helper_constants) + 1
assert positive["summary"]["obligations"] == positive["summary"]["proven"] == 6
assert positive["replay"] == {"certificates": 6, "replayed": 6, "gaps": 0}
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "positive UTF-8 proof report changed across identical runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert verified == {"lexer_decode_utf8_two"}

code, two_byte_ranges = run(TWO_BYTE_RANGES)
assert code == 0 and two_byte_ranges["status"] == two_byte_ranges["verification_state"] == "proved"
assert two_byte_ranges["summary"]["declarations"] == len(helper_constants) + len(two_byte_range_models)
assert two_byte_ranges["summary"]["obligations"] == two_byte_ranges["summary"]["proven"] == 10
assert two_byte_ranges["replay"] == {"certificates": 10, "replayed": 10, "gaps": 0}
assert not two_byte_ranges["findings"]
assert two_byte_ranges == run(TWO_BYTE_RANGES)[1], "two-byte scalar-range report changed across identical runs"
two_byte_ranges_verified = {row["name"] for row in two_byte_ranges["declaration_details"] if row.get("verified")}
assert two_byte_ranges_verified == set(two_byte_range_models)

code, guards_positive = run(GUARDS_POSITIVE)
assert code == 0 and guards_positive["status"] == guards_positive["verification_state"] == "proved"
assert guards_positive["summary"]["declarations"] == len(helper_constants) + 2
assert guards_positive["summary"]["obligations"] == guards_positive["summary"]["proven"] == 22
assert guards_positive["replay"] == {"certificates": 22, "replayed": 22, "gaps": 0}
assert not guards_positive["findings"]
assert guards_positive == run(GUARDS_POSITIVE)[1], "decoder guard proof report changed across identical runs"
guard_verified = {row["name"] for row in guards_positive["declaration_details"] if row.get("verified")}
assert guard_verified == {"proof_three_byte_guard_contract", "proof_four_byte_guard_contract"}

code, sequence_guards = run(SEQUENCE_GUARDS_POSITIVE)
assert code == 0 and sequence_guards["status"] == sequence_guards["verification_state"] == "proved"
assert sequence_guards["summary"]["declarations"] == len(helper_constants) + 6
assert sequence_guards["summary"]["obligations"] == sequence_guards["summary"]["proven"] == 43
assert sequence_guards["replay"] == {"certificates": 43, "replayed": 43, "gaps": 0}
assert not sequence_guards["findings"]
assert sequence_guards == run(SEQUENCE_GUARDS_POSITIVE)[1], "UTF-8 sequence guard proof changed across identical runs"
sequence_verified = {row["name"] for row in sequence_guards["declaration_details"] if row.get("verified")}
assert sequence_verified == {name for name, index, _, _ in sequence_guard_models if index != 7}

code, sequence_f4_guard = run(SEQUENCE_F4_GUARD_POSITIVE)
assert code == 0 and sequence_f4_guard["status"] == sequence_f4_guard["verification_state"] == "proved"
assert sequence_f4_guard["summary"]["declarations"] == len(helper_constants) + 1
assert sequence_f4_guard["summary"]["obligations"] == sequence_f4_guard["summary"]["proven"] == 8
assert sequence_f4_guard["replay"] == {"certificates": 8, "replayed": 8, "gaps": 0}
assert not sequence_f4_guard["findings"]
assert sequence_f4_guard == run(SEQUENCE_F4_GUARD_POSITIVE)[1], "UTF-8 F4 guard proof changed across identical runs"
sequence_f4_verified = {row["name"] for row in sequence_f4_guard["declaration_details"] if row.get("verified")}
assert sequence_f4_verified == {"proof_valid_four_byte_f4_start"}

code, sequence_rejected = run(SEQUENCE_REJECTED, allow_constant_comparison_warnings=True)
assert code == 0 and sequence_rejected["status"] == sequence_rejected["verification_state"] == "proved"
assert sequence_rejected["summary"]["declarations"] == len(helper_constants) + 9
assert sequence_rejected["summary"]["obligations"] == sequence_rejected["summary"]["proven"] == 18
assert sequence_rejected["replay"] == {"certificates": 18, "replayed": 18, "gaps": 0}
assert not sequence_rejected["findings"]
assert sequence_rejected == run(SEQUENCE_REJECTED, allow_constant_comparison_warnings=True)[1], "malformed UTF-8 rejection proofs changed across identical runs"
sequence_rejected_verified = {row["name"] for row in sequence_rejected["declaration_details"] if row.get("verified")}
assert sequence_rejected_verified == {name for name, _ in sequence_rejected_cases}

code, sequence_truncated = run(
    SEQUENCE_TRUNCATED,
    allow_constant_comparison_warnings=True,
    warning_fingerprint=Counter({
        (82, 2, "constant comparison is always true"): 1,
        (82, 2, "constant comparison is always false"): 13,
    }),
)
assert code == 0 and sequence_truncated["status"] == sequence_truncated["verification_state"] == "proved"
assert sequence_truncated["summary"]["declarations"] == len(helper_constants) + 2
assert sequence_truncated["summary"]["obligations"] == sequence_truncated["summary"]["proven"] == 4
assert sequence_truncated["replay"] == {"certificates": 4, "replayed": 4, "gaps": 0}
assert not sequence_truncated["findings"]
assert sequence_truncated == run(
    SEQUENCE_TRUNCATED,
    allow_constant_comparison_warnings=True,
    warning_fingerprint=Counter({
        (82, 2, "constant comparison is always true"): 1,
        (82, 2, "constant comparison is always false"): 13,
    }),
)[1], "UTF-8 truncation proofs changed across identical runs"
sequence_truncated_verified = {row["name"] for row in sequence_truncated["declaration_details"] if row.get("verified")}
assert sequence_truncated_verified == {name for name, _ in sequence_truncated_cases}

code, wide_positive = run(WIDE_POSITIVE)
assert code == 0 and wide_positive["status"] == wide_positive["verification_state"] == "proved"
assert wide_positive["summary"]["declarations"] == len(helper_constants) + 2
assert wide_positive["summary"]["obligations"] == wide_positive["summary"]["proven"] == 8
assert wide_positive["replay"] == {"certificates": 8, "replayed": 8, "gaps": 0}
assert not wide_positive["findings"]
assert wide_positive == run(WIDE_POSITIVE)[1], "wide UTF-8 proof report changed across identical runs"
wide_verified = {row["name"] for row in wide_positive["declaration_details"] if row.get("verified")}
assert wide_verified == {"lexer_decode_utf8_three", "lexer_decode_utf8_four"}

code, payload_bounds = run(PAYLOAD_BOUNDS)
assert code == 0 and payload_bounds["status"] == payload_bounds["verification_state"] == "proved"
assert payload_bounds["summary"]["declarations"] == len(payload_bound_models)
assert payload_bounds["summary"]["obligations"] == payload_bounds["summary"]["proven"] == 32
assert payload_bounds["replay"] == {"certificates": 32, "replayed": 32, "gaps": 0}
assert not payload_bounds["findings"]
assert payload_bounds == run(PAYLOAD_BOUNDS)[1], "UTF-8 payload-range report changed across identical runs"
payload_bounds_verified = {row["name"] for row in payload_bounds["declaration_details"] if row.get("verified")}
assert payload_bounds_verified == set(payload_bound_models)

code, negative = run(NEGATIVE)
assert code == 0 and negative["status"] == negative["verification_state"] == "proved"
assert negative["summary"]["declarations"] == len(helper_constants) + 4
assert negative["summary"]["obligations"] == negative["summary"]["proven"] == 12
assert negative["replay"] == {
    "certificates": negative["summary"]["proven"],
    "replayed": negative["summary"]["proven"],
    "gaps": 0,
}
assert not negative["findings"]
negative_verified = {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert negative_verified == {
    "lexer_decode_utf8_three", "lexer_decode_utf8_four",
    "a_valid_three_byte_sequence_cannot_decode_below_minimum",
    "a_valid_four_byte_sequence_cannot_decode_above_maximum",
}
assert negative == run(NEGATIVE)[1], "negative UTF-8 proof report changed across identical runs"

hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "a proof input changed while proof reports were being replayed"
print("lexer UTF-8 proofs replayed: 6/6 two-byte decoder, 10/10 two-byte scalar ranges, 8/8 wide-helper, 32/32 payload-range, 22/22 decoder-guard, 43/43 sequence-guard, 8/8 F4-guard, 16/16 malformed-input controls, and 12/12 boundary-claim certificates")
