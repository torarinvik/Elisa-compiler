"""Validate deterministic UTF-8 proof reports and false controls."""
from collections import Counter
import hashlib


def validate_utf8_reports(
    FOUR_BYTE_SCALAR_BOUNDS,
    FOUR_BYTE_SCALAR_REJECTED,
    GUARDS_POSITIVE,
    NEGATIVE,
    PAYLOAD_BOUNDS,
    POSITIVE,
    SEQUENCE_F4_GUARD_POSITIVE,
    SEQUENCE_GUARDS_POSITIVE,
    SEQUENCE_REJECTED,
    SEQUENCE_TRUNCATED,
    THREE_BYTE_SCALAR_BOUNDS,
    THREE_BYTE_SURROGATE_REJECTED,
    TWO_BYTE_RANGES,
    WIDE_POSITIVE,
    hashes_before,
    helper_constants,
    inputs,
    payload_bound_models,
    run,
    sequence_guard_models,
    sequence_rejected_cases,
    sequence_truncated_cases,
    two_byte_range_models,
):
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

    code, three_byte_scalar_bounds = run(THREE_BYTE_SCALAR_BOUNDS)
    assert code == 0 and three_byte_scalar_bounds["status"] == three_byte_scalar_bounds["verification_state"] == "proved"
    assert three_byte_scalar_bounds["summary"]["declarations"] == len(helper_constants) + 3
    assert three_byte_scalar_bounds["summary"]["obligations"] == three_byte_scalar_bounds["summary"]["proven"] == 10
    assert three_byte_scalar_bounds["replay"] == {"certificates": 10, "replayed": 10, "gaps": 0}
    assert not three_byte_scalar_bounds["findings"]
    assert three_byte_scalar_bounds == run(THREE_BYTE_SCALAR_BOUNDS)[1], "three-byte scalar-bound report changed across identical runs"
    three_byte_scalar_verified = {row["name"] for row in three_byte_scalar_bounds["declaration_details"] if row.get("verified")}
    assert three_byte_scalar_verified == {"lexer_decode_utf8_three", "lexer_decode_utf8_four", "valid_three_byte_sequence_decodes_to_non_surrogate_scalar"}

    code, three_byte_surrogate_rejected = run(THREE_BYTE_SURROGATE_REJECTED)
    assert code == 0 and three_byte_surrogate_rejected["status"] == three_byte_surrogate_rejected["verification_state"] == "proved"
    assert three_byte_surrogate_rejected["summary"]["declarations"] == len(helper_constants) + 3
    assert three_byte_surrogate_rejected["summary"]["obligations"] == three_byte_surrogate_rejected["summary"]["proven"] == 7
    assert three_byte_surrogate_rejected["replay"] == {"certificates": 7, "replayed": 7, "gaps": 0}
    assert not three_byte_surrogate_rejected["findings"]
    assert three_byte_surrogate_rejected == run(THREE_BYTE_SURROGATE_REJECTED)[1], "surrogate boundary report changed across identical runs"
    three_byte_surrogate_verified = {row["name"] for row in three_byte_surrogate_rejected["declaration_details"] if row.get("verified")}
    assert three_byte_surrogate_verified == {"lexer_decode_utf8_three", "lexer_decode_utf8_four", "an_unchecked_ed_a0_sequence_decodes_to_a_surrogate"}

    code, four_byte_scalar_bounds = run(FOUR_BYTE_SCALAR_BOUNDS)
    assert code == 0 and four_byte_scalar_bounds["status"] == four_byte_scalar_bounds["verification_state"] == "proved"
    assert four_byte_scalar_bounds["summary"]["declarations"] == len(helper_constants) + 3
    assert four_byte_scalar_bounds["summary"]["obligations"] == four_byte_scalar_bounds["summary"]["proven"] == 9
    assert four_byte_scalar_bounds["replay"] == {"certificates": 9, "replayed": 9, "gaps": 0}
    assert not four_byte_scalar_bounds["findings"]
    assert four_byte_scalar_bounds == run(FOUR_BYTE_SCALAR_BOUNDS)[1], "four-byte scalar-bound report changed across identical runs"
    four_byte_scalar_verified = {row["name"] for row in four_byte_scalar_bounds["declaration_details"] if row.get("verified")}
    assert four_byte_scalar_verified == {"lexer_decode_utf8_three", "lexer_decode_utf8_four", "valid_four_byte_sequence_decodes_to_unicode_scalar"}

    code, four_byte_scalar_rejected = run(FOUR_BYTE_SCALAR_REJECTED)
    assert code == 0 and four_byte_scalar_rejected["status"] == four_byte_scalar_rejected["verification_state"] == "proved"
    assert four_byte_scalar_rejected["summary"]["declarations"] == len(helper_constants) + 3
    assert four_byte_scalar_rejected["summary"]["obligations"] == four_byte_scalar_rejected["summary"]["proven"] == 7
    assert four_byte_scalar_rejected["replay"] == {"certificates": 7, "replayed": 7, "gaps": 0}
    assert not four_byte_scalar_rejected["findings"]
    assert four_byte_scalar_rejected == run(FOUR_BYTE_SCALAR_REJECTED)[1], "F4 rejection report changed across identical runs"
    four_byte_scalar_rejected_verified = {row["name"] for row in four_byte_scalar_rejected["declaration_details"] if row.get("verified")}
    assert four_byte_scalar_rejected_verified == {"lexer_decode_utf8_three", "lexer_decode_utf8_four", "an_out_of_range_f4_sequence_is_not_a_unicode_scalar"}

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
    print("lexer UTF-8 proofs replayed: 6/6 two-byte decoder, 10/10 two-byte scalar ranges, 8/8 wide-helper, 10/10 three-byte scalar and surrogate bounds, 7/7 ED surrogate boundary, 9/9 four-byte Unicode bounds, 7/7 F4 rejection boundary, 32/32 payload-range, 22/22 decoder-guard, 43/43 sequence-guard, 8/8 F4-guard, 16/16 malformed-input controls, and 12/12 boundary-claim certificates")
