"""Expected UTF-8 decoder source contracts."""


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

aggregator_includes = (
    'include "./lexer_utf8_codepoint_constants.elisa"',
    'include "./lexer_utf8_codepoint_two.elisa"',
    'include "./lexer_utf8_codepoint_wide.elisa"',
)

two_byte_guard = (
    "if has_second and first.i64() >= UTF8_TWO_BYTE_LEAD_MIN and "
    "first.i64() <= UTF8_TWO_BYTE_LEAD_MAX and second.is_utf8_continuation():"
)

expected_identifier_start_returns = (
    "return 0 if lexer.position >= lexer.source_length",
    "return 2 if two_byte_codepoint.is_latin1_letter_codepoint()",
    "return 2 if two_byte_codepoint.is_unicode2_letter_codepoint()",
    "return 3 if first.i64() >= UTF8_THREE_BYTE_LEAD_MIN and first.i64() <= UTF8_THREE_BYTE_LEAD_MAX and lexer.three_byte_codepoint_at_cursor().is_unicode_letter_codepoint()",
    "return 4 if first.i64() >= UTF8_FOUR_BYTE_LEAD_MIN and first.i64() <= UTF8_FOUR_BYTE_LEAD_MAX and lexer.four_byte_codepoint_at_cursor().is_unicode_letter_codepoint()",
    "return 1 if first.int().is_latin1_letter_codepoint() and not lexer.starts_valid_utf8_sequence()",
    "return 0",
)

expected_identifier_char_returns = (
    "return 0 if lexer.position >= lexer.source_length",
    "return 2 if two_byte_codepoint.is_latin1_letter_codepoint()",
    "return 2 if two_byte_codepoint.is_unicode2_letter_codepoint()",
    "return 2 if first.i64() >= UTF8_TWO_BYTE_ARABIC_DIGIT_LEAD_MIN and two_byte_codepoint.is_unicode2_digit_codepoint()",
    "return 3 if three_byte_codepoint.is_unicode_letter_codepoint() or three_byte_codepoint.is_unicode_digit_codepoint()",
    "return 4 if four_byte_codepoint.is_unicode_letter_codepoint() or four_byte_codepoint.is_unicode_digit_codepoint()",
    "return 1 if first.int().is_latin1_letter_codepoint() and not lexer.starts_valid_utf8_sequence()",
    "return 0",
)


def check_decoder(body: str, *, indices: tuple[str, ...], lead_guard: str,
                  continuations: tuple[str, ...], special_guards: tuple[str, ...],
                  helper_call: str) -> None:
    expected_returns = (
        "return -1 if lexer.position >= lexer.source_length",
        f"-1 return if remaining <= {indices[-1]}",
        lead_guard,
        "return -1 if:",
        helper_call,
    )
    observed_returns = tuple(
        line.strip() for line in body.splitlines()
        if "return" in line and not line.lstrip().startswith("#")
    )
    if observed_returns != expected_returns:
        raise SystemExit("UTF-8 decoder has an unexpected or unguarded return")
    lines = body.splitlines()
    guard_index = next((index for index, line in enumerate(lines) if line.strip() == "return -1 if:"), -1)
    if guard_index < 0:
        raise SystemExit("UTF-8 decoder is missing its invalid-byte guard block")
    guard_indent = len(lines[guard_index]) - len(lines[guard_index].lstrip(" \t"))
    guard_conditions = []
    for line in lines[guard_index + 1:]:
        if line.strip() and len(line) - len(line.lstrip(" \t")) <= guard_indent:
            break
        if line.strip():
            guard_conditions.append(line.strip())
    if tuple(guard_conditions) != (*continuations, *special_guards):
        raise SystemExit("UTF-8 decoder invalid-byte guard expressions changed")
    if observed_returns[-1] != helper_call:
        raise SystemExit("UTF-8 helper call must be the decoder's final return")

    ordered = (
        "return -1 if lexer.position >= lexer.source_length",
        "remaining: usize = lexer.source_length - lexer.position",
        f"-1 return if remaining <= {indices[-1]}",
        "first: u8 = lexer.source[lexer.position]",
        lead_guard,
        *[f"lexer.source[lexer.position + {index}]" for index in indices],
        "return -1 if:",
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
