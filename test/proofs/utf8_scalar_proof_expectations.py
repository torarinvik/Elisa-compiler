"""Expected UTF-8 proof model and rejection claims."""


expected_start_returns = (
    "return false if lexer.position >= lexer.source_length",
    "return remaining > 1 and is_utf8_continuation(lexer.source[lexer.position + 1]) if first.i64() >= UTF8_TWO_BYTE_LEAD_MIN and first.i64() <= UTF8_TWO_BYTE_LEAD_MAX",
    "return remaining > 2 and lexer.source[lexer.position + 1].i64() >= UTF8_E0_SECOND_MIN and lexer.source[lexer.position + 1].i64() <= UTF8_CONTINUATION_MAX and is_utf8_continuation(lexer.source[lexer.position + 2]) if first.i64() == UTF8_THREE_BYTE_LEAD_MIN",
    "return remaining > 2 and is_utf8_continuation(lexer.source[lexer.position + 1]) and is_utf8_continuation(lexer.source[lexer.position + 2]) if (first.i64() > UTF8_THREE_BYTE_LEAD_MIN and first.i64() < UTF8_SURROGATE_LEAD) or (first.i64() > UTF8_SURROGATE_LEAD and first.i64() <= UTF8_THREE_BYTE_LEAD_MAX)",
    "return remaining > 2 and lexer.source[lexer.position + 1].i64() >= UTF8_CONTINUATION_MIN and lexer.source[lexer.position + 1].i64() <= UTF8_ED_SECOND_MAX and is_utf8_continuation(lexer.source[lexer.position + 2]) if first.i64() == UTF8_SURROGATE_LEAD",
    "return remaining > 3 and lexer.source[lexer.position + 1].i64() >= UTF8_F0_SECOND_MIN and lexer.source[lexer.position + 1].i64() <= UTF8_CONTINUATION_MAX and is_utf8_continuation(lexer.source[lexer.position + 2]) and is_utf8_continuation(lexer.source[lexer.position + 3]) if first.i64() == UTF8_FOUR_BYTE_LEAD_MIN",
    "return remaining > 3 and is_utf8_continuation(lexer.source[lexer.position + 1]) and is_utf8_continuation(lexer.source[lexer.position + 2]) and is_utf8_continuation(lexer.source[lexer.position + 3]) if first.i64() > UTF8_FOUR_BYTE_LEAD_MIN and first.i64() < UTF8_FOUR_BYTE_LEAD_MAX",
    "return remaining > 3 and lexer.source[lexer.position + 1].i64() >= UTF8_CONTINUATION_MIN and lexer.source[lexer.position + 1].i64() <= UTF8_F4_SECOND_MAX and is_utf8_continuation(lexer.source[lexer.position + 2]) and is_utf8_continuation(lexer.source[lexer.position + 3]) if first.i64() == UTF8_FOUR_BYTE_LEAD_MAX",
    "return false",
)

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

two_byte_formula = (
    "(first - UTF8_TWO_BYTE_LEAD_PAYLOAD_OFFSET) * "
    "UTF8_TWO_BYTE_LEAD_PLACE_VALUE + second - UTF8_CONTINUATION_MIN"
)

latin1_return = (
    "return value == 0xAA or value == 0xB5 or value == 0xBA or "
    "value in 0xC0..0xD6 or value in 0xD8..0xF6 or value in 0xF8..0xFF"
)

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

three_byte_scalar_guard_premises = (
    "requires first >= UTF8_THREE_BYTE_LEAD_MIN and first <= UTF8_THREE_BYTE_LEAD_MAX",
    "requires second >= UTF8_CONTINUATION_MIN and second <= UTF8_CONTINUATION_MAX",
    "requires third >= UTF8_CONTINUATION_MIN and third <= UTF8_CONTINUATION_MAX",
    "requires first > UTF8_THREE_BYTE_LEAD_MIN or second >= UTF8_E0_SECOND_MIN",
    "requires first != UTF8_SURROGATE_LEAD or second <= UTF8_ED_SECOND_MAX",
)

three_byte_scalar_decode = (
    "decoded: i64 = lexer_decode_utf8_three(first - UTF8_THREE_BYTE_LEAD_MIN, "
    "second - UTF8_CONTINUATION_MIN, third - UTF8_CONTINUATION_MIN)"
)

three_byte_scalar_predicate = (
    "decoded >= UTF8_THREE_BYTE_SCALAR_MIN and decoded <= UTF8_THREE_BYTE_SCALAR_MAX and "
    "(decoded < UNICODE_SURROGATE_MIN or decoded > UNICODE_SURROGATE_MAX)"
)

four_byte_source_guards = (
    "return -1 if first.i64() < UTF8_FOUR_BYTE_LEAD_MIN or first.i64() > UTF8_FOUR_BYTE_LEAD_MAX",
    "return -1 if:",
    "second.i64() < UTF8_CONTINUATION_MIN or second.i64() > UTF8_CONTINUATION_MAX or third.i64() < UTF8_CONTINUATION_MIN or third.i64() > UTF8_CONTINUATION_MAX or fourth.i64() < UTF8_CONTINUATION_MIN or fourth.i64() > UTF8_CONTINUATION_MAX",
    "first.i64() == UTF8_FOUR_BYTE_LEAD_MIN and second.i64() < UTF8_F0_SECOND_MIN",
    "first.i64() == UTF8_FOUR_BYTE_LEAD_MAX and second.i64() > UTF8_F4_SECOND_MAX",
)

four_byte_source_decode = (
    "return lexer_decode_utf8_four(first.i64() - UTF8_FOUR_BYTE_LEAD_MIN, "
    "second.i64() - UTF8_CONTINUATION_MIN, third.i64() - UTF8_CONTINUATION_MIN, "
    "fourth.i64() - UTF8_CONTINUATION_MIN).int()"
)

four_byte_scalar_guard_premises = (
    "requires first >= UTF8_FOUR_BYTE_LEAD_MIN and first <= UTF8_FOUR_BYTE_LEAD_MAX",
    "requires second >= UTF8_CONTINUATION_MIN and second <= UTF8_CONTINUATION_MAX",
    "requires third >= UTF8_CONTINUATION_MIN and third <= UTF8_CONTINUATION_MAX",
    "requires fourth >= UTF8_CONTINUATION_MIN and fourth <= UTF8_CONTINUATION_MAX",
    "requires first > UTF8_FOUR_BYTE_LEAD_MIN or second >= UTF8_F0_SECOND_MIN",
    "requires first < UTF8_FOUR_BYTE_LEAD_MAX or second <= UTF8_F4_SECOND_MAX",
)

four_byte_scalar_decode = (
    "decoded: i64 = lexer_decode_utf8_four(first - UTF8_FOUR_BYTE_LEAD_MIN, "
    "second - UTF8_CONTINUATION_MIN, third - UTF8_CONTINUATION_MIN, "
    "fourth - UTF8_CONTINUATION_MIN)"
)

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
