"""Admit source-linked proofs for checked decimal bit-int width accumulation."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve(strict=True)
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
HELPER = ROOT / "src/semantic/bit_int_width.elisa"
ENDPOINTS = ROOT / "src/semantic/bit_int_endpoints.elisa"
PARSER = ROOT / "src/semantic/check_const_enum_value_fits.elisa"
LITERAL_CHECK = ROOT / "src/semantic/check_literal_type_overflow.elisa"
CAST_CHECK = ROOT / "src/semantic/check_cast_constant_truncated.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
POSITIVE = HERE / "bit_int_width_step.elisa"
NEGATIVE = HERE / "bit_int_width_step_rejected.elisa"
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")


def uncomment(text: str) -> str:
    """Remove Elisa line comments without changing comment markers in string literals."""
    lines = []
    for line in text.splitlines():
        quoted = False
        escaped = False
        for index, char in enumerate(line):
            if escaped:
                escaped = False
            elif char == "\\" and quoted:
                escaped = True
            elif char == '"':
                quoted = not quoted
            elif char == "#" and not quoted:
                line = line[:index]
                break
        lines.append(line)
    return "\n".join(lines)


def compact(text: str) -> str:
    return re.sub(r"\s+", "", uncomment(text))


def function_source(text: str, name: str) -> str:
    match = re.search(rf"(?m)^\s*def\s+{re.escape(name)}(?=\[|\()", text)
    if not match:
        raise SystemExit(f"missing production or proof function: {name}")
    tail = text[match.end():]
    following = re.search(r"(?m)^\s*(?:def\s+|public:|private:|module\s+|extend\s+)", tail)
    end = match.end() + following.start() if following else len(text)
    return text[match.start():end]


def require_source_contract(helper_text: str, parser_text: str, endpoints_text: str) -> list[str]:
    errors: list[str] = []
    helper = compact(function_source(helper_text, "append_digit"))
    expected_contracts = (
        "ensure(width>=BIT_INT_PREFIX_MINandwidth<=BIT_INT_MAX_WIDTHanddigit>=DECIMAL_DIGIT_MINanddigit<=DECIMAL_DIGIT_MAX)impliesresult.valid==(width*DECIMAL_RADIX+digit<=BIT_INT_MAX_WIDTH)",
        "ensureresult.validimplies(result.value>=BIT_INT_PREFIX_MINandresult.value<=BIT_INT_MAX_WIDTH)",
        "ensureresult.validimpliesresult.value==width*DECIMAL_RADIX+digit",
        "ensurenotresult.validimpliesresult.value==0",
    )
    for clause in expected_contracts:
        if helper.count(clause) != 1:
            errors.append(f"append_digit must state contract exactly once: {clause}")

    final_width = compact(function_source(helper_text, "supported_final_width"))
    final_width_contract = compact(
        "ensure result == (width >= BIT_INT_MIN_WIDTH and width <= BIT_INT_MAX_WIDTH)"
    )
    final_width_body = compact(
        "return width >= BIT_INT_MIN_WIDTH and width <= BIT_INT_MAX_WIDTH"
    )
    if final_width.count(final_width_contract) != 1 or final_width.count(final_width_body) != 1:
        errors.append("supported_final_width must exactly characterize the inclusive range 1..63")

    input_guard = compact(
        "return (false, 0) if width < BIT_INT_PREFIX_MIN or width > BIT_INT_MAX_WIDTH "
        "or digit < DECIMAL_DIGIT_MIN or digit > DECIMAL_DIGIT_MAX"
    )
    candidate = compact("candidate: i64 = width * DECIMAL_RADIX + digit")
    over_limit = compact("return (false, 0) if candidate > BIT_INT_MAX_WIDTH")
    success = compact("return (true, candidate)")
    ordered = [helper.find(part) for part in (input_guard, candidate, over_limit, success)]
    if any(position < 0 for position in ordered) or ordered != sorted(ordered):
        errors.append("append_digit must validate inputs before bounded arithmetic and reject before success")
    if any(literal in helper for literal in ("width>63", "width*10", "digit>9", "candidate>63")):
        errors.append("append_digit reintroduced a magic width/radix/digit limit")

    for name, type_name, value in (
        ("BIT_INT_PREFIX_MIN", "i64", "0"),
        ("BIT_INT_MIN_WIDTH", "i64", "1"),
        ("BIT_INT_MAX_WIDTH", "i64", "63"),
        ("BIT_INT_WIDTH_LIMIT", "i64", "BIT_INT_MAX_WIDTH + 1"),
        ("DECIMAL_RADIX", "i64", "10"),
        ("DECIMAL_DIGIT_MIN", "i64", "0"),
        ("DECIMAL_DIGIT_MAX", "i64", "DECIMAL_RADIX - 1"),
        ("ASCII_DIGIT_ZERO", "u8", "48"),
        ("ASCII_DIGIT_NINE", "u8", "57"),
    ):
        declaration = compact(f"const {name}: {type_name} = {value}")
        if compact(helper_text).count(declaration) != 1:
            errors.append(f"missing or changed named constant: {declaration}")
    for name, type_name, value in (
        ("MAX_WIDTH_CANDIDATE", "i64", "BIT_INT_MAX_WIDTH * DECIMAL_RADIX + DECIMAL_DIGIT_MAX"),
        ("I64_MAX", "i64", "9223372036854775807"),
    ):
        declaration = compact(f"const {name}: {type_name} = {value}")
        if compact(helper_text).count(declaration) != 1:
            errors.append(f"missing or changed named bound: {declaration}")

    unsigned_high = compact(function_source(helper_text, "unsigned_63_high_endpoint"))
    high_steps = ("ensureresult==I64_MAX", "returnI64_MAX")
    high_positions = [unsigned_high.find(part) for part in high_steps]
    if any(position < 0 for position in high_positions) or high_positions != sorted(high_positions):
        errors.append("unsigned_63_high_endpoint must return the representable i64 maximum under an exact postcondition")

    if helper_text.count("module SemanticBitIntWidth:") != 1:
        errors.append("checked width helper module is missing or duplicated")

    if 'include "./bit_int_endpoints.elisa"' not in parser_text:
        errors.append("bit-int window parser must import the proved endpoint arithmetic")
    endpoint_functions = {
        "unsigned_high_from_span": (
            "requires span >= 1 and span <= I64_MAX",
            "ensure result == span - 1",
            "ensure result >= 0",
            "ensure result <= I64_MAX",
            "return span - 1",
        ),
        "signed_low_from_span": (
            "requires span >= 1 and span <= SIGNED_SPAN_MAX",
            "ensure result == 0 - span",
            "ensure result >= SIGNED_LOW_MIN",
            "ensure result < 0",
            "return 0 - span",
        ),
        "signed_high_from_span": (
            "requires span >= 1 and span <= SIGNED_SPAN_MAX",
            "ensure result == span - 1",
            "ensure result >= 0",
            "ensure result <= I64_MAX",
            "return span - 1",
        ),
    }
    for name, clauses in endpoint_functions.items():
        body = compact(function_source(endpoints_text, name))
        for clause in clauses:
            if compact(clause) not in body:
                errors.append(f"{name} no longer states or implements endpoint arithmetic clause: {clause}")
    for name, value in (
        ("I64_MAX", "9223372036854775807"),
        ("SIGNED_SPAN_MAX", "4611686018427387904"),
        ("SIGNED_LOW_MIN", "0 - SIGNED_SPAN_MAX"),
    ):
        if compact(f"const {name}: i64 = {value}") not in compact(endpoints_text):
            errors.append(f"bit-int endpoint bound changed: {name}")

    parser = compact(function_source(parser_text, "bit_int_window"))
    parser_guard = compact(
        "if digit < SemanticBitIntWidth::ASCII_DIGIT_ZERO "
        "or digit > SemanticBitIntWidth::ASCII_DIGIT_NINE:"
    )
    digit_value = compact(
        "digit_value: i64 = "
        "(digit - SemanticBitIntWidth::ASCII_DIGIT_ZERO).i64()"
    )
    parser_call = compact(
        "step: (valid: bool, value: i64) = "
        "SemanticBitIntWidth::append_digit(bits, digit_value)"
    )
    parser_initial_state = compact(
        "bits: mutable i64 = SemanticBitIntWidth::BIT_INT_PREFIX_MIN "
        "index: mutable usize = 1 ok: mutable bool = true "
        "while index < length and ok |bits, index, ok|:"
    )
    invalid_step = compact("if not step.valid: ok <- false")
    valid_update = compact("bits <- step.value index <- index + 1")
    final_rejection = compact(
        "(false, 0, 0) return if not ok or not SemanticBitIntWidth::supported_final_width(bits)"
    )
    positions = [parser.find(part) for part in (parser_initial_state, parser_guard, digit_value, parser_call, invalid_step, valid_update, final_rejection)]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        errors.append("bit_int_window must reject non-digits, use the checked helper, and advance only on valid steps")
    if "bits<-bits*10" in parser or 'include"./bit_int_width.elisa"' not in compact(parser_text):
        errors.append("bit_int_window bypasses or no longer includes the checked decimal helper")
    unsigned_branch_steps = (
        compact(
            "(true, SemanticBitIntWidth::BIT_INT_PREFIX_MIN, "
            "SemanticBitIntWidth::unsigned_63_high_endpoint()) return if "
            "bits == SemanticBitIntWidth::BIT_INT_MAX_WIDTH"
        ),
        compact("span: i64 = 1 << bits.usize()"),
        compact(
            "(false, 0, 0) return if span < SemanticBitIntWidth::BIT_INT_MIN_WIDTH "
            "or span > SemanticBitIntEndpoints::I64_MAX"
        ),
        compact("high: i64 = SemanticBitIntEndpoints::unsigned_high_from_span(span)"),
        compact("return (true, SemanticBitIntWidth::BIT_INT_PREFIX_MIN, high)"),
    )
    unsigned_positions = [parser.find(part) for part in unsigned_branch_steps]
    signed_branch = compact(
        "span: i64 = 1 << (bits - SemanticBitIntWidth::BIT_INT_MIN_WIDTH).usize() "
        "(false, 0, 0) return if span < SemanticBitIntWidth::BIT_INT_MIN_WIDTH "
        "or span > SemanticBitIntEndpoints::SIGNED_SPAN_MAX "
        "low: i64 = SemanticBitIntEndpoints::signed_low_from_span(span) "
        "high: i64 = SemanticBitIntEndpoints::signed_high_from_span(span) "
        "return (true, low, high)"
    )
    if any(position < 0 for position in unsigned_positions) or unsigned_positions != sorted(unsigned_positions) or signed_branch not in parser:
        errors.append("bit_int_window must use the checked u63 endpoint and retain the signed-width calculation")

    return errors


helper_text = HELPER.read_text()
endpoints_text = ENDPOINTS.read_text()
parser_text = PARSER.read_text()
source_errors = require_source_contract(helper_text, parser_text, endpoints_text)
if source_errors:
    raise SystemExit("\n".join(source_errors))
if 'include "./check_const_enum_value_fits.elisa"' not in SEMANTIC.read_text():
    raise SystemExit("semantic pass no longer includes the shared bit-int window parser")
if "bit_int_window(type_name)" not in compact(LITERAL_CHECK.read_text()):
    raise SystemExit("typed integer-literal overflow check no longer uses the shared width parser")
if "bit_int_window(method_name)" not in compact(CAST_CHECK.read_text()) or \
        "bit_int_window(callee_name)" not in compact(CAST_CHECK.read_text()):
    raise SystemExit("constant-cast range checks no longer use the shared width parser")

# Ensure the admission guard itself notices weakening either safety gate.
weakened_prefix = helper_text.replace(
    "width > BIT_INT_MAX_WIDTH", "width >= BIT_INT_MAX_WIDTH", 1
)
if weakened_prefix == helper_text or not require_source_contract(weakened_prefix, parser_text, endpoints_text):
    raise SystemExit("source checker failed to catch a weakened prefix bound")
weakened_helper = helper_text.replace(
    "candidate > BIT_INT_MAX_WIDTH", "candidate >= BIT_INT_MAX_WIDTH", 1
)
if weakened_helper == helper_text or not require_source_contract(weakened_helper, parser_text, endpoints_text):
    raise SystemExit("source checker failed to catch an off-by-one width acceptance mutation")
weakened_parser = parser_text.replace("if not step.valid:", "if step.valid:", 1)
if weakened_parser == parser_text or not require_source_contract(helper_text, weakened_parser, endpoints_text):
    raise SystemExit("source checker failed to catch inverted checked-step handling")
weakened_final_width = helper_text.replace(
    "width >= BIT_INT_MIN_WIDTH", "width > BIT_INT_MIN_WIDTH", 1
)
if weakened_final_width == helper_text or not require_source_contract(weakened_final_width, parser_text, endpoints_text):
    raise SystemExit("source checker failed to catch rejection of the minimum valid width")
parser_bypass = parser_text.replace(
    "SemanticBitIntWidth::append_digit(bits, digit_value)",
    "(false, bits * SemanticBitIntWidth::DECIMAL_RADIX + digit_value)", 1,
)
if parser_bypass == parser_text or not require_source_contract(helper_text, parser_bypass, endpoints_text):
    raise SystemExit("source checker failed to catch a parser bypass of the checked helper")
u63_endpoint_bypass = parser_text.replace(
    "SemanticBitIntWidth::unsigned_63_high_endpoint()",
    "SemanticBitIntWidth::I64_MAX", 1,
)
if u63_endpoint_bypass == parser_text or not require_source_contract(helper_text, u63_endpoint_bypass, endpoints_text):
    raise SystemExit("source checker failed to catch removal of the representable u63 endpoint")
unsigned_endpoint_bypass = parser_text.replace(
    "SemanticBitIntEndpoints::unsigned_high_from_span(span)", "span - 1", 1
)
if unsigned_endpoint_bypass == parser_text or not require_source_contract(helper_text, unsigned_endpoint_bypass, endpoints_text):
    raise SystemExit("source checker failed to catch bypass of the proved unsigned endpoint")
signed_endpoint_bypass = parser_text.replace(
    "SemanticBitIntEndpoints::signed_low_from_span(span)", "0 - span", 1
)
if signed_endpoint_bypass == parser_text or not require_source_contract(helper_text, signed_endpoint_bypass, endpoints_text):
    raise SystemExit("source checker failed to catch bypass of the proved signed endpoint")
weakened_unsigned_span_guard = parser_text.replace(
    "span > SemanticBitIntEndpoints::I64_MAX", "span >= SemanticBitIntEndpoints::I64_MAX", 1
)
if weakened_unsigned_span_guard == parser_text or not require_source_contract(helper_text, weakened_unsigned_span_guard, endpoints_text):
    raise SystemExit("source checker failed to catch an off-by-one unsigned span guard")

positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()
if 'include "../../src/semantic/bit_int_width.elisa"' not in positive_text:
    raise SystemExit("positive proof no longer imports the production width helper")
if 'include "./bit_int_width_step.elisa"' not in negative_text:
    raise SystemExit("negative controls no longer share the positive proof source")

expected_positive = {
    "bounded_width_step_matches_the_decimal_transition",
    "accepted_width_step_stays_below_sixty_four",
    "every_guarded_decimal_candidate_fits_i64",
    "every_two_digit_decimal_suffix_matches_the_width_bound",
    "width_sixty_three_is_accepted",
    "width_sixty_four_is_rejected",
    "a_prefix_already_outside_the_window_is_rejected",
    "negative_prefix_is_rejected",
    "non_decimal_digit_is_rejected",
    "ascii_digit_byte_maps_to_a_decimal_digit",
    "unsigned_63_high_endpoint_is_i64_max",
    "unsigned_62_high_endpoint_is_i64_max_over_two",
    "final_width_predicate_matches_the_supported_interval",
    "minimum_final_width_is_supported",
    "maximum_final_width_is_supported",
    "zero_final_width_is_rejected",
    "width_above_the_limit_is_rejected",
    "every_out_of_range_final_width_is_rejected",
}
expected_negative = {
    "false_width_sixty_four_is_accepted",
    "false_overwide_prefix_is_accepted",
    "false_invalid_digit_is_accepted",
    "false_maximum_candidate_is_below_its_bound",
    "false_every_two_digit_decimal_suffix_is_accepted",
    "false_unsigned_63_high_is_the_i63_maximum",
    "false_zero_final_width_is_supported",
    "false_width_above_limit_is_supported",
    "false_minimum_final_width_is_rejected",
    "false_maximum_final_width_is_rejected",
}
positive_names = set(re.findall(r"(?m)^def\s+(\w+)\s*\(", positive_text))
negative_names = set(re.findall(r"(?m)^def\s+(\w+)\s*\(", negative_text))
if positive_names != expected_positive:
    raise SystemExit(f"positive proof inventory changed: {sorted(positive_names)}")
if negative_names != expected_negative:
    raise SystemExit(f"negative proof inventory changed: {sorted(negative_names)}")
for name in expected_positive:
    body = compact(function_source(positive_text, name))
    expected_call = (
        "SemanticBitIntWidth::unsigned_63_high_endpoint("
        if name == "unsigned_63_high_endpoint_is_i64_max"
        else "SemanticBitIntWidth::supported_final_width("
        if name in {
            "final_width_predicate_matches_the_supported_interval",
            "minimum_final_width_is_supported",
            "maximum_final_width_is_supported",
            "zero_final_width_is_rejected",
            "width_above_the_limit_is_rejected",
            "every_out_of_range_final_width_is_rejected",
        }
        else "SemanticBitIntWidth::append_digit("
        if name != "unsigned_62_high_endpoint_is_i64_max_over_two"
        else ""
    )
    if expected_call not in body:
        raise SystemExit(f"positive theorem {name} no longer exercises the production helper")
for name in expected_negative:
    body = compact(function_source(negative_text, name))
    expected_call = "SemanticBitIntWidth::unsigned_63_high_endpoint(" if name.startswith("false_unsigned_") else "SemanticBitIntWidth::append_digit("
    if name in {
        "false_zero_final_width_is_supported",
        "false_width_above_limit_is_supported",
        "false_minimum_final_width_is_rejected",
        "false_maximum_final_width_is_rejected",
    }:
        expected_call = "SemanticBitIntWidth::supported_final_width("
    if expected_call not in body:
        raise SystemExit(f"false control {name} no longer exercises the production helper")

positive_shapes = {
    "bounded_width_step_matches_the_decimal_transition": (
        "requires width >= SemanticBitIntWidth::BIT_INT_PREFIX_MIN and width <= SemanticBitIntWidth::BIT_INT_MAX_WIDTH",
        "requires digit >= SemanticBitIntWidth::DECIMAL_DIGIT_MIN and digit <= SemanticBitIntWidth::DECIMAL_DIGIT_MAX",
        "candidate: i64 = width * SemanticBitIntWidth::DECIMAL_RADIX + digit",
        "return step.valid == (candidate <= SemanticBitIntWidth::BIT_INT_MAX_WIDTH)",
    ),
    "accepted_width_step_stays_below_sixty_four": (
        "return not step.valid or (step.value >= SemanticBitIntWidth::BIT_INT_PREFIX_MIN and step.value <= SemanticBitIntWidth::BIT_INT_MAX_WIDTH)",
    ),
    "every_guarded_decimal_candidate_fits_i64": (
        "candidate: i64 = width * SemanticBitIntWidth::DECIMAL_RADIX + digit",
        "candidate <= SemanticBitIntWidth::MAX_WIDTH_CANDIDATE",
        "SemanticBitIntWidth::MAX_WIDTH_CANDIDATE <= SemanticBitIntWidth::I64_MAX",
    ),
    "every_two_digit_decimal_suffix_matches_the_width_bound": (
        "requires first_digit >= SemanticBitIntWidth::DECIMAL_DIGIT_MIN and first_digit <= SemanticBitIntWidth::DECIMAL_DIGIT_MAX",
        "requires second_digit >= SemanticBitIntWidth::DECIMAL_DIGIT_MIN and second_digit <= SemanticBitIntWidth::DECIMAL_DIGIT_MAX",
        "first: (valid: bool, value: i64) = SemanticBitIntWidth::append_digit(SemanticBitIntWidth::BIT_INT_PREFIX_MIN, first_digit)",
        "candidate: i64 = first_digit * SemanticBitIntWidth::DECIMAL_RADIX + second_digit",
        "step: (valid: bool, value: i64) = SemanticBitIntWidth::append_digit(first.value, second_digit)",
        "return first.valid and step.valid == (candidate <= SemanticBitIntWidth::BIT_INT_MAX_WIDTH)",
    ),
    "width_sixty_three_is_accepted": (
        "SemanticBitIntWidth::BIT_INT_MAX_WIDTH / SemanticBitIntWidth::DECIMAL_RADIX",
        "SemanticBitIntWidth::BIT_INT_MAX_WIDTH % SemanticBitIntWidth::DECIMAL_RADIX",
        "return step.valid and step.value == SemanticBitIntWidth::BIT_INT_MAX_WIDTH",
    ),
    "width_sixty_four_is_rejected": (
        "SemanticBitIntWidth::BIT_INT_WIDTH_LIMIT / SemanticBitIntWidth::DECIMAL_RADIX",
        "SemanticBitIntWidth::BIT_INT_WIDTH_LIMIT % SemanticBitIntWidth::DECIMAL_RADIX",
        "return not step.valid and step.value == SemanticBitIntWidth::BIT_INT_PREFIX_MIN",
    ),
    "a_prefix_already_outside_the_window_is_rejected": (
        "requires width >= SemanticBitIntWidth::BIT_INT_WIDTH_LIMIT",
        "return not step.valid and step.value == SemanticBitIntWidth::BIT_INT_PREFIX_MIN",
    ),
    "negative_prefix_is_rejected": (
        "requires width < SemanticBitIntWidth::BIT_INT_PREFIX_MIN",
        "return not step.valid and step.value == SemanticBitIntWidth::BIT_INT_PREFIX_MIN",
    ),
    "non_decimal_digit_is_rejected": (
        "requires digit < SemanticBitIntWidth::DECIMAL_DIGIT_MIN or digit > SemanticBitIntWidth::DECIMAL_DIGIT_MAX",
        "return not step.valid and step.value == SemanticBitIntWidth::BIT_INT_PREFIX_MIN",
    ),
    "ascii_digit_byte_maps_to_a_decimal_digit": (
        "requires byte >= SemanticBitIntWidth::ASCII_DIGIT_ZERO and byte <= SemanticBitIntWidth::ASCII_DIGIT_NINE",
        "digit: i64 = (byte - SemanticBitIntWidth::ASCII_DIGIT_ZERO).i64()",
        "digit >= SemanticBitIntWidth::DECIMAL_DIGIT_MIN and digit <= SemanticBitIntWidth::DECIMAL_DIGIT_MAX",
        "step.valid and step.value == digit",
    ),
    "unsigned_63_high_endpoint_is_i64_max": (
        "SemanticBitIntWidth::unsigned_63_high_endpoint()",
        "return high == SemanticBitIntWidth::I64_MAX",
    ),
    "unsigned_62_high_endpoint_is_i64_max_over_two": (
        "1 << (SemanticBitIntWidth::BIT_INT_MAX_WIDTH - SemanticBitIntWidth::BIT_INT_MIN_WIDTH).usize()",
        "return high == SemanticBitIntWidth::I64_MAX / 2",
    ),
    "final_width_predicate_matches_the_supported_interval": (
        "SemanticBitIntWidth::supported_final_width(width)",
        "width >= SemanticBitIntWidth::BIT_INT_MIN_WIDTH and width <= SemanticBitIntWidth::BIT_INT_MAX_WIDTH",
    ),
    "minimum_final_width_is_supported": (
        "SemanticBitIntWidth::supported_final_width(SemanticBitIntWidth::BIT_INT_MIN_WIDTH)",
    ),
    "maximum_final_width_is_supported": (
        "SemanticBitIntWidth::supported_final_width(SemanticBitIntWidth::BIT_INT_MAX_WIDTH)",
    ),
    "zero_final_width_is_rejected": (
        "not SemanticBitIntWidth::supported_final_width(SemanticBitIntWidth::BIT_INT_PREFIX_MIN)",
    ),
    "width_above_the_limit_is_rejected": (
        "not SemanticBitIntWidth::supported_final_width(SemanticBitIntWidth::BIT_INT_WIDTH_LIMIT)",
    ),
    "every_out_of_range_final_width_is_rejected": (
        "requires width < SemanticBitIntWidth::BIT_INT_MIN_WIDTH or width > SemanticBitIntWidth::BIT_INT_MAX_WIDTH",
        "not SemanticBitIntWidth::supported_final_width(width)",
    ),
}
negative_shapes = {
    "false_width_sixty_four_is_accepted": (
        "SemanticBitIntWidth::BIT_INT_WIDTH_LIMIT % SemanticBitIntWidth::DECIMAL_RADIX",
        "return step.valid",
    ),
    "false_overwide_prefix_is_accepted": (
        "requires width >= SemanticBitIntWidth::BIT_INT_WIDTH_LIMIT",
        "return step.valid",
    ),
    "false_invalid_digit_is_accepted": (
        "requires digit < SemanticBitIntWidth::DECIMAL_DIGIT_MIN or digit > SemanticBitIntWidth::DECIMAL_DIGIT_MAX",
        "return step.valid",
    ),
    "false_maximum_candidate_is_below_its_bound": (
        "SemanticBitIntWidth::BIT_INT_MAX_WIDTH / SemanticBitIntWidth::DECIMAL_RADIX",
        "return step.valid or SemanticBitIntWidth::MAX_WIDTH_CANDIDATE <",
    ),
    "false_every_two_digit_decimal_suffix_is_accepted": (
        "requires first_digit >= SemanticBitIntWidth::DECIMAL_DIGIT_MIN and first_digit <= SemanticBitIntWidth::DECIMAL_DIGIT_MAX",
        "requires second_digit >= SemanticBitIntWidth::DECIMAL_DIGIT_MIN and second_digit <= SemanticBitIntWidth::DECIMAL_DIGIT_MAX",
        "return first.valid and step.valid",
    ),
    "false_unsigned_63_high_is_the_i63_maximum": (
        "SemanticBitIntWidth::unsigned_63_high_endpoint()",
        "return high == SemanticBitIntWidth::I64_MAX / 2",
    ),
    "false_zero_final_width_is_supported": (
        "SemanticBitIntWidth::supported_final_width(SemanticBitIntWidth::BIT_INT_PREFIX_MIN)",
    ),
    "false_width_above_limit_is_supported": (
        "SemanticBitIntWidth::supported_final_width(SemanticBitIntWidth::BIT_INT_WIDTH_LIMIT)",
    ),
    "false_minimum_final_width_is_rejected": (
        "SemanticBitIntWidth::supported_final_width(SemanticBitIntWidth::BIT_INT_MIN_WIDTH)",
    ),
    "false_maximum_final_width_is_rejected": (
        "SemanticBitIntWidth::supported_final_width(SemanticBitIntWidth::BIT_INT_MAX_WIDTH)",
    ),
}
for theorem, fragments in positive_shapes.items():
    body = compact(function_source(positive_text, theorem))
    if any(compact(fragment) not in body for fragment in fragments):
        raise SystemExit(f"positive theorem {theorem} no longer proves its checked bound")
for theorem, fragments in negative_shapes.items():
    body = compact(function_source(negative_text, theorem))
    if any(compact(fragment) not in body for fragment in fragments):
        raise SystemExit(f"false control {theorem} no longer challenges the stated boundary")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("bit-int width proof requires a strict proof build")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
source_closure = source_include_closure([POSITIVE, NEGATIVE])
inputs = [
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV",
    stage1_product, stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
    HELPER, ENDPOINTS, PARSER, LITERAL_CHECK, CAST_CHECK, SEMANTIC, *source_closure,
]
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=60)
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
assert positive == run(POSITIVE)[1], "width-step proof report changed across repeated runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert expected_positive <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert {row["name"] for row in negative["findings"]} == expected_negative
assert all(row["kind"] == "ensure-unproven" and row["status"] in {"unknown", "disproved"}
           for row in negative["findings"])
assert all(not row.get("counterexample_found") or row["status"] == "disproved"
           for row in negative["findings"])
assert require_current_product(BIN, PROVER) == manifest, "proof product changed during replay"
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "source-bound bit-int width parsing: checked decimal steps keep i64 intermediates at most 639, accept widths 1 through 63, reject malformed or over-width suffixes, and handle u63 with the representable i64 maximum without forming 2^63",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(expected_negative),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
