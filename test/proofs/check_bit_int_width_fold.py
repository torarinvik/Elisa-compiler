"""Admit a sequence-level refinement proof for the production bit-int width parser."""
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
PARSER = ROOT / "src/semantic/check_const_enum_value_fits.elisa"
POSITIVE = HERE / "bit_int_width_fold.elisa"
NEGATIVE = HERE / "bit_int_width_fold_rejected.elisa"
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")


def compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def function_source(text: str, name: str) -> str:
    match = re.search(rf"(?m)^\s*def\s+{re.escape(name)}(?=\[|\()", text)
    if not match:
        raise SystemExit(f"missing production or proof function: {name}")
    tail = text[match.end():]
    following = re.search(r"(?m)^\s*(?:def\s+|public:|private:|module\s+|extend\s+)", tail)
    end = match.end() + following.start() if following else len(text)
    return text[match.start():end]


def ordered(text: str, fragments: tuple[str, ...]) -> bool:
    normalized = compact(text)
    positions = [normalized.find(compact(fragment)) for fragment in fragments]
    return all(position >= 0 for position in positions) and positions == sorted(positions)


def require_parser_fold(source: str) -> list[str]:
    errors = []
    if 'include "./bit_int_width.elisa"' not in source:
        errors.append("production bit-int parser no longer imports the checked width helper")
    parser = function_source(source, "bit_int_window")
    required_steps = (
        "length: usize = sview_len(type_name)",
        "(false, 0, 0) return if length < 2",
        "lead: u8 = type_name[0]",
        "is_unsigned: bool = lead == 117",
        "is_signed: bool = lead == 105",
        "(false, 0, 0) return if not (is_unsigned or is_signed)",
        "bits: mutable i64 = SemanticBitIntWidth::BIT_INT_PREFIX_MIN",
        "index: mutable usize = 1",
        "ok: mutable bool = true",
        "while index < length and ok |bits, index, ok|:",
        "digit: u8 = type_name[index]",
        "digit < SemanticBitIntWidth::ASCII_DIGIT_ZERO or digit > SemanticBitIntWidth::ASCII_DIGIT_NINE",
        "digit_value: i64 = (digit - SemanticBitIntWidth::ASCII_DIGIT_ZERO).i64()",
        "step: (valid: bool, value: i64) = SemanticBitIntWidth::append_digit(bits, digit_value)",
        "if not step.valid: ok <- false",
        "bits <- step.value index <- index + 1",
        "(false, 0, 0) return if not ok or not SemanticBitIntWidth::supported_final_width(bits)",
    )
    if not ordered(parser, required_steps):
        errors.append("bit-int digit scan no longer follows the bounded recursive-fold model")
    return errors


HELPER_TEXT = HELPER.read_text()
PARSER_TEXT = PARSER.read_text()
if 'include "../../src/semantic/bit_int_width.elisa"' not in POSITIVE.read_text():
    raise SystemExit("positive sequence proof no longer imports the production width helper")
if 'include "./bit_int_width_fold.elisa"' not in NEGATIVE.read_text():
    raise SystemExit("sequence false controls no longer share the positive proof")
source_errors = require_parser_fold(PARSER_TEXT)
if source_errors:
    raise SystemExit("\n".join(source_errors))

helper = compact(function_source(HELPER_TEXT, "append_digit"))
helper_steps = (
    "return (false, 0) if width < BIT_INT_PREFIX_MIN or width > BIT_INT_MAX_WIDTH or digit < DECIMAL_DIGIT_MIN or digit > DECIMAL_DIGIT_MAX",
    "candidate: i64 = width * DECIMAL_RADIX + digit",
    "return (false, 0) if candidate > BIT_INT_MAX_WIDTH",
    "return (true, candidate)",
)
if not ordered(helper, helper_steps):
    raise SystemExit("production append_digit no longer checks its prefix/digit and candidate before success")
validity_contract = compact(
    "ensure (width >= BIT_INT_PREFIX_MIN and width <= BIT_INT_MAX_WIDTH and "
    "digit >= DECIMAL_DIGIT_MIN and digit <= DECIMAL_DIGIT_MAX) implies "
    "result.valid == (width * DECIMAL_RADIX + digit <= BIT_INT_MAX_WIDTH)"
)
if helper.count(validity_contract) != 1:
    raise SystemExit("production append_digit no longer states its exact validity condition for guarded inputs")

proof_text = POSITIVE.read_text()
spec = compact(function_source(proof_text, "width_ascii_fold_spec"))
fold = compact(function_source(proof_text, "fold_width_ascii_bytes"))
parse = compact(function_source(proof_text, "parse_width_ascii_bytes"))
name_spec = compact(function_source(proof_text, "bit_int_name_width_spec"))
name_parse = compact(function_source(proof_text, "parse_bit_int_name_width"))
if "SemanticBitIntWidth::append_digit" in spec:
    raise SystemExit("independent width-fold specification delegates to the production helper")
if "decreasesremaining" not in spec or "decreasesremaining" not in fold:
    raise SystemExit("recursive digit folds no longer prove termination from the remaining suffix")
required_range = compact(
    "requires remaining <= bytes.count and width >= SemanticBitIntWidth::BIT_INT_PREFIX_MIN "
    "and width <= SemanticBitIntWidth::BIT_INT_MAX_WIDTH"
)
for name, function in (("width_ascii_fold_spec", spec), ("fold_width_ascii_bytes", fold)):
    if function.count(required_range) != 1:
        raise SystemExit(f"{name} must constrain its index and accumulator before arithmetic or indexing")
    for postcondition in (
        "ensure result.valid implies result.value >= SemanticBitIntWidth::BIT_INT_PREFIX_MIN",
        "ensure result.valid implies result.value <= SemanticBitIntWidth::BIT_INT_MAX_WIDTH",
        "ensure not result.valid implies result.value == SemanticBitIntWidth::BIT_INT_PREFIX_MIN",
    ):
        if function.count(compact(postcondition)) != 1:
            raise SystemExit(f"{name} must specify the valid range and rejected sentinel exactly once")
spec_steps = (
    "return (true, width) if remaining == 0",
    "position: usize = bytes.count - remaining",
    "byte: u8 = bytes[position]",
    "return (false, SemanticBitIntWidth::BIT_INT_PREFIX_MIN) if byte < SemanticBitIntWidth::ASCII_DIGIT_ZERO or byte > SemanticBitIntWidth::ASCII_DIGIT_NINE",
    "digit_value: i64 = (byte - SemanticBitIntWidth::ASCII_DIGIT_ZERO).i64()",
    "candidate: i64 = width * SemanticBitIntWidth::DECIMAL_RADIX + digit_value",
    "return (false, SemanticBitIntWidth::BIT_INT_PREFIX_MIN) if candidate > SemanticBitIntWidth::BIT_INT_MAX_WIDTH",
    "return width_ascii_fold_spec(bytes, remaining - 1, candidate)",
)
fold_steps = (
    "return (true, width) if remaining == 0",
    "position: usize = bytes.count - remaining",
    "byte: u8 = bytes[position]",
    "return (false, SemanticBitIntWidth::BIT_INT_PREFIX_MIN) if byte < SemanticBitIntWidth::ASCII_DIGIT_ZERO or byte > SemanticBitIntWidth::ASCII_DIGIT_NINE",
    "digit_value: i64 = (byte - SemanticBitIntWidth::ASCII_DIGIT_ZERO).i64()",
    "step: (valid: bool, value: i64) = SemanticBitIntWidth::append_digit(width, digit_value)",
    "return (false, SemanticBitIntWidth::BIT_INT_PREFIX_MIN) if not step.valid",
    "return fold_width_ascii_bytes(bytes, remaining - 1, step.value)",
)
if not ordered(function_source(proof_text, "width_ascii_fold_spec"), spec_steps):
    raise SystemExit("independent byte-fold specification changed its ASCII/bounded decimal transition")
if not ordered(function_source(proof_text, "fold_width_ascii_bytes"), fold_steps):
    raise SystemExit("production fold no longer rejects before recursing and resets on every rejected path")
for clause in (
    "ensure result.valid==width_ascii_fold_spec(bytes,remaining,width).valid",
    "ensure result.value==width_ascii_fold_spec(bytes,remaining,width).value",
    "step:(valid:bool,value:i64)=SemanticBitIntWidth::append_digit(width,digit_value)",
    "returnfold_width_ascii_bytes(bytes,remaining-1,step.value)",
):
    if compact(clause) not in fold:
        raise SystemExit("production fold no longer refines the independent specification one digit at a time")
for clause in (
    "ensure result.valid==width_ascii_fold_spec(bytes,bytes.count,SemanticBitIntWidth::BIT_INT_PREFIX_MIN).valid",
    "ensure result.value==width_ascii_fold_spec(bytes,bytes.count,SemanticBitIntWidth::BIT_INT_PREFIX_MIN).value",
    "returnfold_width_ascii_bytes(bytes,bytes.count,SemanticBitIntWidth::BIT_INT_PREFIX_MIN)",
):
    if compact(clause) not in parse:
        raise SystemExit("whole-suffix parser wrapper no longer starts from the production empty prefix")

name_spec_steps = (
    "return (false, false, SemanticBitIntWidth::BIT_INT_PREFIX_MIN) if bytes.count < 2",
    "lead: u8 = bytes[0]",
    "is_unsigned: bool = lead == 117",
    "is_signed: bool = lead == 105",
    "return (false, false, SemanticBitIntWidth::BIT_INT_PREFIX_MIN) if not (is_unsigned or is_signed)",
    "folded: (valid: bool, value: i64) = width_ascii_fold_spec(bytes, bytes.count - 1, SemanticBitIntWidth::BIT_INT_PREFIX_MIN)",
    "return (false, false, SemanticBitIntWidth::BIT_INT_PREFIX_MIN) if not folded.valid or not SemanticBitIntWidth::supported_final_width(folded.value)",
    "return (true, is_unsigned, folded.value)",
)
name_parse_steps = (
    "return (false, false, SemanticBitIntWidth::BIT_INT_PREFIX_MIN) if bytes.count < 2",
    "lead: u8 = bytes[0]",
    "is_unsigned: bool = lead == 117",
    "is_signed: bool = lead == 105",
    "return (false, false, SemanticBitIntWidth::BIT_INT_PREFIX_MIN) if not (is_unsigned or is_signed)",
    "folded: (valid: bool, value: i64) = fold_width_ascii_bytes(bytes, bytes.count - 1, SemanticBitIntWidth::BIT_INT_PREFIX_MIN)",
    "return (false, false, SemanticBitIntWidth::BIT_INT_PREFIX_MIN) if not folded.valid or not SemanticBitIntWidth::supported_final_width(folded.value)",
    "return (true, is_unsigned, folded.value)",
)
if "fold_width_ascii_bytes" in name_spec or not ordered(function_source(proof_text, "bit_int_name_width_spec"), name_spec_steps):
    raise SystemExit("independent bit-int name specification must classify u/i and fold exactly the suffix after byte zero")
if not ordered(function_source(proof_text, "parse_bit_int_name_width"), name_parse_steps):
    raise SystemExit("production-linked bit-int name model no longer classifies the prefix and folds the byte-one suffix")
for clause in ("ensure result.found implies bytes.count >= 2",):
    if name_spec.count(compact(clause)) != 1 or name_parse.count(compact(clause)) != 1:
        raise SystemExit("successful name parses must expose a bounds-safe prefix/signedness contract")
for clause in (
    "ensure result.found == bit_int_name_width_spec(bytes).found",
    "ensure result.unsigned == bit_int_name_width_spec(bytes).unsigned",
    "ensure result.width == bit_int_name_width_spec(bytes).width",
):
    if compact(clause) not in name_parse:
        raise SystemExit("bit-int name model no longer refines every result field of its independent specification")

expected_positive = {
    "width_ascii_fold_spec",
    "fold_width_ascii_bytes",
    "parse_width_ascii_bytes",
    "every_width_ascii_fold_matches_the_independent_specification",
    "every_accepted_width_ascii_fold_stays_in_the_supported_prefix_range",
    "width_ascii_fold_accepts_exactly_sixty_three",
    "width_ascii_fold_rejects_sixty_four_and_clears_the_value",
    "width_ascii_fold_rejects_a_non_digit_and_clears_the_value",
    "width_ascii_fold_accepts_leading_zeroes_before_one",
    "all_zero_width_bytes_leave_an_empty_prefix_that_is_not_a_final_width",
    "width_ascii_fold_rejects_an_overwide_prefix_before_the_remaining_bytes",
    "bit_int_name_width_spec",
    "parse_bit_int_name_width",
    "unsigned_name_parser_accepts_u_sixty_three",
    "signed_name_parser_accepts_i_one",
    "name_parser_rejects_an_unknown_lead_byte",
    "name_parser_rejects_a_missing_width",
    "name_parser_rejects_an_empty_name",
    "name_parser_rejects_zero_width",
    "name_parser_rejects_a_nondigit_suffix",
    "name_parser_rejects_width_sixty_four",
}
expected_negative = {
    "false_width_ascii_fold_accepts_sixty_four",
    "false_width_ascii_fold_accepts_a_non_digit",
    "false_width_ascii_fold_preserves_sixty_four_after_rejection",
    "false_width_ascii_fold_rejects_exactly_sixty_three",
    "false_all_zero_width_bytes_form_a_supported_final_width",
    "false_name_parser_accepts_an_unknown_lead_byte",
    "false_name_parser_accepts_a_missing_width",
    "false_name_parser_marks_i_as_unsigned",
    "false_name_parser_marks_u_as_signed",
    "false_name_parser_accepts_an_empty_name",
    "false_name_parser_accepts_zero_width",
    "false_name_parser_accepts_a_nondigit_suffix",
    "false_name_parser_accepts_width_sixty_four",
}
negative_text = NEGATIVE.read_text()
declared_positive = set(re.findall(r"(?m)^def\s+(\w+)\s*\(", proof_text))
declared_negative = set(re.findall(r"(?m)^def\s+(\w+)\s*\(", negative_text))
if declared_positive != expected_positive:
    raise SystemExit(f"positive sequence proof inventory changed: {sorted(declared_positive)}")
if declared_negative != expected_negative:
    raise SystemExit(f"sequence false-control inventory changed: {sorted(declared_negative)}")

positive_shapes = {
    "every_width_ascii_fold_matches_the_independent_specification": (
        "requires remaining <= bytes.count and width >= SemanticBitIntWidth::BIT_INT_PREFIX_MIN and width <= SemanticBitIntWidth::BIT_INT_MAX_WIDTH",
        "folded: (valid: bool, value: i64) = fold_width_ascii_bytes(bytes, remaining, width)",
        "specified: (valid: bool, value: i64) = width_ascii_fold_spec(bytes, remaining, width)",
        "return folded.valid == specified.valid and folded.value == specified.value",
    ),
    "every_accepted_width_ascii_fold_stays_in_the_supported_prefix_range": (
        "requires remaining <= bytes.count and width >= SemanticBitIntWidth::BIT_INT_PREFIX_MIN and width <= SemanticBitIntWidth::BIT_INT_MAX_WIDTH",
        "folded: (valid: bool, value: i64) = fold_width_ascii_bytes(bytes, remaining, width)",
        "return not folded.valid or (folded.value >= SemanticBitIntWidth::BIT_INT_PREFIX_MIN and folded.value <= SemanticBitIntWidth::BIT_INT_MAX_WIDTH)",
    ),
    "width_ascii_fold_accepts_exactly_sixty_three": (
        "bytes: darray[u8] = [54, 51]",
        "folded: (valid: bool, value: i64) = parse_width_ascii_bytes(bytes)",
        "return folded.valid and folded.value == SemanticBitIntWidth::BIT_INT_MAX_WIDTH",
    ),
    "width_ascii_fold_rejects_sixty_four_and_clears_the_value": (
        "bytes: darray[u8] = [54, 52]",
        "folded: (valid: bool, value: i64) = parse_width_ascii_bytes(bytes)",
        "return not folded.valid and folded.value == SemanticBitIntWidth::BIT_INT_PREFIX_MIN",
    ),
    "width_ascii_fold_rejects_a_non_digit_and_clears_the_value": (
        "bytes: darray[u8] = [49, 58, 50]",
        "folded: (valid: bool, value: i64) = parse_width_ascii_bytes(bytes)",
        "return not folded.valid and folded.value == SemanticBitIntWidth::BIT_INT_PREFIX_MIN",
    ),
    "width_ascii_fold_accepts_leading_zeroes_before_one": (
        "bytes: darray[u8] = [48, 48, 49]",
        "folded: (valid: bool, value: i64) = parse_width_ascii_bytes(bytes)",
        "return folded.valid and folded.value == SemanticBitIntWidth::BIT_INT_MIN_WIDTH",
    ),
    "all_zero_width_bytes_leave_an_empty_prefix_that_is_not_a_final_width": (
        "bytes: darray[u8] = [48, 48]",
        "folded: (valid: bool, value: i64) = parse_width_ascii_bytes(bytes)",
        "return folded.valid and folded.value == SemanticBitIntWidth::BIT_INT_PREFIX_MIN and not SemanticBitIntWidth::supported_final_width(folded.value)",
    ),
    "width_ascii_fold_rejects_an_overwide_prefix_before_the_remaining_bytes": (
        "bytes: darray[u8] = [54, 52, 49]",
        "folded: (valid: bool, value: i64) = parse_width_ascii_bytes(bytes)",
        "return not folded.valid and folded.value == SemanticBitIntWidth::BIT_INT_PREFIX_MIN",
    ),
    "unsigned_name_parser_accepts_u_sixty_three": (
        "bytes: darray[u8] = [117, 54, 51]",
        "parsed: (found: bool, unsigned: bool, width: i64) = parse_bit_int_name_width(bytes)",
        "return parsed.found and parsed.unsigned and parsed.width == SemanticBitIntWidth::BIT_INT_MAX_WIDTH",
    ),
    "signed_name_parser_accepts_i_one": (
        "bytes: darray[u8] = [105, 49]",
        "parsed: (found: bool, unsigned: bool, width: i64) = parse_bit_int_name_width(bytes)",
        "return parsed.found and not parsed.unsigned and parsed.width == SemanticBitIntWidth::BIT_INT_MIN_WIDTH",
    ),
    "name_parser_rejects_an_unknown_lead_byte": (
        "bytes: darray[u8] = [118, 56]",
        "parsed: (found: bool, unsigned: bool, width: i64) = parse_bit_int_name_width(bytes)",
        "return not parsed.found and not parsed.unsigned and parsed.width == SemanticBitIntWidth::BIT_INT_PREFIX_MIN",
    ),
    "name_parser_rejects_a_missing_width": (
        "bytes: darray[u8] = [117]",
        "parsed: (found: bool, unsigned: bool, width: i64) = parse_bit_int_name_width(bytes)",
        "return not parsed.found and not parsed.unsigned and parsed.width == SemanticBitIntWidth::BIT_INT_PREFIX_MIN",
    ),
    "name_parser_rejects_an_empty_name": (
        "bytes: darray[u8] = []",
        "parsed: (found: bool, unsigned: bool, width: i64) = parse_bit_int_name_width(bytes)",
        "return not parsed.found and not parsed.unsigned and parsed.width == SemanticBitIntWidth::BIT_INT_PREFIX_MIN",
    ),
    "name_parser_rejects_zero_width": (
        "bytes: darray[u8] = [117, 48]",
        "parsed: (found: bool, unsigned: bool, width: i64) = parse_bit_int_name_width(bytes)",
        "return not parsed.found and not parsed.unsigned and parsed.width == SemanticBitIntWidth::BIT_INT_PREFIX_MIN",
    ),
    "name_parser_rejects_a_nondigit_suffix": (
        "bytes: darray[u8] = [105, 58, 49]",
        "parsed: (found: bool, unsigned: bool, width: i64) = parse_bit_int_name_width(bytes)",
        "return not parsed.found and not parsed.unsigned and parsed.width == SemanticBitIntWidth::BIT_INT_PREFIX_MIN",
    ),
    "name_parser_rejects_width_sixty_four": (
        "bytes: darray[u8] = [117, 54, 52]",
        "parsed: (found: bool, unsigned: bool, width: i64) = parse_bit_int_name_width(bytes)",
        "return not parsed.found and not parsed.unsigned and parsed.width == SemanticBitIntWidth::BIT_INT_PREFIX_MIN",
    ),
}
for theorem, fragments in positive_shapes.items():
    body = compact(function_source(proof_text, theorem))
    if "ensureresult==true" not in body or any(compact(fragment) not in body for fragment in fragments):
        raise SystemExit(f"sequence theorem {theorem} no longer states its intended property")

negative_shapes = {
    "false_width_ascii_fold_accepts_sixty_four": "bytes:darray[u8]=[54,52]returnparse_width_ascii_bytes(bytes).valid",
    "false_width_ascii_fold_accepts_a_non_digit": "bytes:darray[u8]=[58]returnparse_width_ascii_bytes(bytes).valid",
    "false_width_ascii_fold_preserves_sixty_four_after_rejection": "returnnotfolded.validandfolded.value==SemanticBitIntWidth::BIT_INT_WIDTH_LIMIT",
    "false_width_ascii_fold_rejects_exactly_sixty_three": "bytes:darray[u8]=[54,51]returnnotparse_width_ascii_bytes(bytes).valid",
    "false_all_zero_width_bytes_form_a_supported_final_width": "bytes:darray[u8]=[48,48]folded:(valid:bool,value:i64)=parse_width_ascii_bytes(bytes)returnfolded.validandSemanticBitIntWidth::supported_final_width(folded.value)",
    "false_name_parser_accepts_an_unknown_lead_byte": "bytes:darray[u8]=[118,56]returnparse_bit_int_name_width(bytes).found",
    "false_name_parser_accepts_a_missing_width": "bytes:darray[u8]=[117]returnparse_bit_int_name_width(bytes).found",
    "false_name_parser_marks_i_as_unsigned": "bytes:darray[u8]=[105,49]parsed:(found:bool,unsigned:bool,width:i64)=parse_bit_int_name_width(bytes)returnparsed.foundandparsed.unsigned",
    "false_name_parser_marks_u_as_signed": "bytes:darray[u8]=[117,49]parsed:(found:bool,unsigned:bool,width:i64)=parse_bit_int_name_width(bytes)returnparsed.foundandnotparsed.unsigned",
    "false_name_parser_accepts_an_empty_name": "bytes:darray[u8]=[]returnparse_bit_int_name_width(bytes).found",
    "false_name_parser_accepts_zero_width": "bytes:darray[u8]=[117,48]returnparse_bit_int_name_width(bytes).found",
    "false_name_parser_accepts_a_nondigit_suffix": "bytes:darray[u8]=[105,58,49]returnparse_bit_int_name_width(bytes).found",
    "false_name_parser_accepts_width_sixty_four": "bytes:darray[u8]=[117,54,52]returnparse_bit_int_name_width(bytes).found",
}
for theorem, fragments in negative_shapes.items():
    if fragments not in compact(function_source(negative_text, theorem)):
        raise SystemExit(f"sequence false control {theorem} no longer challenges its intended boundary")

# Source-shape mutation controls protect the fold's production correspondence.
parser_mutations = (
    PARSER_TEXT.replace("SemanticBitIntWidth::append_digit(bits, digit_value)", "(true, bits * 10 + digit_value)", 1),
    PARSER_TEXT.replace("if not step.valid:", "if step.valid:", 1),
    PARSER_TEXT.replace("bits <- step.value", "bits <- digit_value", 1),
    PARSER_TEXT.replace("bits: mutable i64 = SemanticBitIntWidth::BIT_INT_PREFIX_MIN", "bits: mutable i64 = 1", 1),
    PARSER_TEXT.replace("is_unsigned: bool = lead == 117", "is_unsigned: bool = lead == 118", 1),
    PARSER_TEXT.replace("is_signed: bool = lead == 105", "is_signed: bool = lead == 106", 1),
)
for mutation in parser_mutations:
    if mutation == PARSER_TEXT or not require_parser_fold(mutation):
        raise SystemExit("source checker failed to catch a parser/fold correspondence mutation")
mutated_spec = proof_text.replace(
    "candidate > SemanticBitIntWidth::BIT_INT_MAX_WIDTH",
    "candidate >= SemanticBitIntWidth::BIT_INT_MAX_WIDTH",
    1,
)
if mutated_spec == proof_text or ordered(function_source(mutated_spec, "width_ascii_fold_spec"), spec_steps):
    raise SystemExit("source checker failed to catch a weakened independent width-fold specification")
mutated_name_spec = proof_text.replace(
    "width_ascii_fold_spec(bytes, bytes.count - 1,",
    "width_ascii_fold_spec(bytes, bytes.count,",
    1,
)
if mutated_name_spec == proof_text or ordered(function_source(mutated_name_spec, "bit_int_name_width_spec"), name_spec_steps):
    raise SystemExit("source checker failed to catch a specification scanner-offset mutation")
mutated_name_parse = proof_text.replace(
    "fold_width_ascii_bytes(bytes, bytes.count - 1,",
    "fold_width_ascii_bytes(bytes, bytes.count,",
    1,
)
if mutated_name_parse == proof_text or ordered(function_source(mutated_name_parse, "parse_bit_int_name_width"), name_parse_steps):
    raise SystemExit("source checker failed to catch a production-model scanner-offset mutation")
mutated_name_lead = proof_text.replace("is_unsigned: bool = lead == 117", "is_unsigned: bool = lead == 118", 1)
if mutated_name_lead == proof_text or ordered(function_source(mutated_name_lead, "bit_int_name_width_spec"), name_spec_steps):
    raise SystemExit("source checker failed to catch an independent name-prefix mutation")
mutated_name_signed_lead = proof_text.replace("is_signed: bool = lead == 105", "is_signed: bool = lead == 106", 1)
if mutated_name_signed_lead == proof_text or ordered(function_source(mutated_name_signed_lead, "bit_int_name_width_spec"), name_spec_steps):
    raise SystemExit("source checker failed to catch an independent signed-prefix mutation")

try:
    manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if manifest.get("compile_mode") != "strict":
    raise SystemExit("bit-int width-fold proof requires a strict proof build")

stage1_product = Path(manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV",
    stage1_product, stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
    HELPER, PARSER, POSITIVE, NEGATIVE,
    *source_include_closure([POSITIVE, NEGATIVE, PARSER]),
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=180)
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
assert positive == run(POSITIVE)[1], "width-fold proof report changed across repeated runs"
positive_verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert expected_positive <= positive_verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["verification_state"] in {"failed", "disproved"}
assert negative["summary"]["unproven"] == len(expected_negative)
assert {row["name"] for row in negative["findings"]} == expected_negative
assert all(row["kind"] == "ensure-unproven" and row["status"] in {"unknown", "disproved"}
           for row in negative["findings"])
negative_verified = {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert expected_positive <= negative_verified
assert not expected_negative & negative_verified
assert require_current_product(BIN, PROVER) == manifest
hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof inputs changed during sequence replay"
print(json.dumps({
    "admitted": True,
    "scope": "source-linked arbitrary-length bit-int ASCII byte folds refine an independent bounded specification; non-digits and prefixes over 63 fail closed",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(expected_negative),
    "proof_revision": manifest["proof"].get("head"),
    "compiler_revision": manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
