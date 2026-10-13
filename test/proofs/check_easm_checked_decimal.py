"""Admit overflow-safe EASM decimal parsing against a strict proof product."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product


argument_parser = argparse.ArgumentParser()
argument_parser.add_argument("--source-only", action="store_true",
                             help="check production and proof bindings without running Elisa-Proof")
ARGS = argument_parser.parse_args()
ROOT = Path(__file__).resolve().parents[2]
PROVER = ROOT.parent / "elisa-proof"
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=not ARGS.source_only)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
POSITIVE = HERE / "easm_checked_decimal.elisa"
NEGATIVE = HERE / "easm_checked_decimal_rejected.elisa"
ARITH_POSITIVE = HERE / "easm_checked_decimal_arithmetic.elisa"
ARITH_NEGATIVE = HERE / "easm_checked_decimal_arithmetic_rejected.elisa"
HELPER = ROOT / "src/backend/easm_checked_decimal.elisa"
ENV = ROOT / "src/backend/codegen_env.elisa"
PARSER = ROOT / "src/backend/easm_verify_function.elisa"
MEMORY = ROOT / "src/backend/easm_verify_memory.elisa"
MEMSTATE = ROOT / "src/backend/easm_memstate_domain.elisa"
LAYOUT_PARSER = ROOT / "src/backend/easm_parse.elisa"
INTEGRATION = ROOT / "test/breadth/easm_checked_decimal_parse_smoke.elisa"
STDIN_DRIVER = ROOT / "test/breadth/easm_verify_stdin.elisa"
ENFORCEMENT_TEST = ROOT / "scripts/easm_enforcement_fuzz.py"

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(source: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in source.splitlines())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)(?:ghost[ \t]+)?def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one production function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}(?:ghost[ \t]+)?def [A-Za-z_][A-Za-z0-9_]*\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def declaration_names(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))

helper_text = HELPER.read_text()
arithmetic_text = ARITH_POSITIVE.read_text()
arithmetic_compact = compact(arithmetic_text)
env_text = ENV.read_text()
parser_text = PARSER.read_text()
memory_text = MEMORY.read_text()
if 'include "../../src/backend/easm_checked_decimal.elisa"' not in POSITIVE.read_text():
    raise SystemExit("positive proof no longer includes the production checked-digit helpers")
if 'include "../../src/backend/easm_memstate_domain.elisa"' not in POSITIVE.read_text():
    raise SystemExit("invalid-size-fact proof no longer includes the production memory-bound domain")
if 'include "./easm_checked_decimal.elisa"' not in NEGATIVE.read_text():
    raise SystemExit("negative controls no longer include the production checked-digit helpers")
if 'include "./easm_checked_decimal_arithmetic.elisa"' not in ARITH_NEGATIVE.read_text():
    raise SystemExit("arithmetic false claims no longer include the positive arithmetic proofs")
if 'include "easm_checked_decimal.elisa"' not in env_text:
    raise SystemExit("backend environment no longer imports the checked-digit helpers")
if env_text.index('include "easm_checked_decimal.elisa"') > env_text.index('include "easm_verify_function.elisa"'):
    raise SystemExit("checked-digit helpers are imported after the parser that uses them")

for contract in (
    "ensure result.valid == (value < I64_MAX / DECIMAL_RADIX",
    "ensure result.valid implies result.value == value * DECIMAL_RADIX + digit",
    "ensure not result.valid implies result.value == 0",
    "ensure result.valid == (value > I64_MIN / DECIMAL_RADIX",
    "ensure result.valid implies result.value == value * DECIMAL_RADIX - digit",
):
    if contract not in helper_text:
        raise SystemExit(f"checked decimal helper contract is missing: {contract}")

parse_source = compact(function_section(helper_text, "parse_signed"))
required_parse_contracts = (
    "ensureresult.valid==decimal_parse_reference(text).valid",
    "ensureresult.value==decimal_parse_reference(text).value",
    "ensurenotresult.validimpliesresult.value==0",
    "ensure(result.validandtext.length>0andtext[0]==ASCII_MINUS)impliesresult.value<=0",
    "ensure(result.validandtext.length>0andtext[0]!=ASCII_MINUS)impliesresult.value>=0",
    "text.length>0",
    "text[0]!=ASCII_MINUSortext.length>1",
    "foralldigit_indexin0..<text.length",
    "text[digit_index]>=ASCII_DIGIT_ZERO",
    "text[digit_index]<=ASCII_DIGIT_NINE",
)
required_parse_steps = (
    "return(false,0)iftext.length<0",
    "iftext.length>0andtext[0]==EasmCheckedDecimal::ASCII_MINUS:",
    "return(false,0)ifposition==text.length",
    "whileposition<text.length|position,text,value|",
    "decreasestext.length-position",
    "invariantposition<=text.length",
    "invariantnegativeimpliesposition>=1",
    "invariantnegativeimpliesvalue<=0",
    "invariantnotnegativeimpliesvalue>=0",
    "start:usize=position",
    "invariantdecimal_parse_reference_from(text,position,negative,value,position>start).valid==decimal_parse_reference(text).valid",
    "invariantdecimal_parse_reference_from(text,position,negative,value,position>start).value==decimal_parse_reference(text).value",
    "invariantforalldigit_indexin0..<position:(negativeanddigit_index==0andtext[digit_index]==ASCII_MINUS)or(text[digit_index]>=ASCII_DIGIT_ZEROandtext[digit_index]<=ASCII_DIGIT_NINE)",
    "return(false,0)ifbyte<ASCII_DIGIT_ZEROorbyte>ASCII_DIGIT_NINE",
    "append_negative_digit(value,digit)",
    "append_positive_digit(value,digit)",
    "position<-position+1",
    "return(true,value)",
)
if not all(fragment in parse_source for fragment in required_parse_contracts + required_parse_steps):
    raise SystemExit("signed parser lost its syntax, sign, failure, or loop-safety proof contract")

reference_from = compact(function_section(helper_text, "decimal_parse_reference_from"))
reference_wrapper = compact(function_section(helper_text, "decimal_parse_reference"))
required_reference_fragments = (
    "ghostdefdecimal_parse_reference_from(",
    "requiresposition<=text.lengthand(negativeimpliesvalue<=0)and(notnegativeimpliesvalue>=0)",
    "decreasestext.length-position",
    "ensureresult.validimplies(negativeimpliesresult.value<=0)",
    "ensureresult.validimplies(notnegativeimpliesresult.value>=0)",
    "byte:u8=text[position]",
    "return(false,0)ifbyte<ASCII_DIGIT_ZEROorbyte>ASCII_DIGIT_NINE",
    "value*DECIMAL_RADIX-digit",
    "value*DECIMAL_RADIX+digit",
    "returndecimal_parse_reference_from(text,position+1,negative,next_value,true)",
)
if not all(fragment in reference_from for fragment in required_reference_fragments) or \
        "append_positive_digit" in reference_from or "append_negative_digit" in reference_from:
    raise SystemExit("recursive decimal reference no longer defines an independent checked digit fold")
if "ghostdefdecimal_parse_reference(text:sview)" not in reference_wrapper or \
        "returndecimal_parse_reference_from(text,position,negative,0,false)" not in reference_wrapper or \
        "ensure(result.validandtext.length>0andtext[0]==ASCII_MINUS)impliesresult.value<=0" not in reference_wrapper or \
        "ensure(result.validandtext.length>0andtext[0]!=ASCII_MINUS)impliesresult.value>=0" not in reference_wrapper:
    raise SystemExit("decimal reference wrapper no longer specifies the optional sign and digit fold")

# Reduce the production i64 constants to the exact thresholds used by the
# scalar proofs, then bind the source guard and its executable rejection
# branches to those formulas.
radix = 10
i64_max = 9223372036854775807
i64_min = -i64_max - 1
positive_limit, positive_final_digit = divmod(i64_max, radix)
negative_limit = -(abs(i64_min) // radix)
negative_remainder = i64_min - negative_limit * radix
negative_final_digit = -negative_remainder
positive_guard = (
    f"value<{positive_limit}or(value=={positive_limit}anddigit<={positive_final_digit})"
)
negative_guard = (
    f"value>0-{abs(negative_limit)}or"
    f"(value==0-{abs(negative_limit)}anddigit<={negative_final_digit})"
)
positive_source = compact(function_section(helper_text, "append_positive_digit"))
negative_source = compact(function_section(helper_text, "append_negative_digit"))
if "constDECIMAL_RADIX:i64=10" not in compact(helper_text) or \
        f"constI64_MAX:i64={i64_max}" not in compact(helper_text) or \
        "constI64_MIN:i64=0-I64_MAX-1" not in compact(helper_text):
    raise SystemExit("production decimal constants no longer match the i64 proof domain")
if "ensureresult.valid==(value<I64_MAX/DECIMAL_RADIXor(value==I64_MAX/DECIMAL_RADIXanddigit<=I64_MAX%DECIMAL_RADIX))" not in positive_source or \
        "limit:i64=I64_MAX/DECIMAL_RADIX" not in positive_source or \
        "final_digit_limit:i64=I64_MAX%DECIMAL_RADIX" not in positive_source or \
        "return(false,0)ifvalue>limit" not in positive_source or \
        "return(false,0)ifvalue==limitanddigit>final_digit_limit" not in positive_source or \
        "return(true,value*DECIMAL_RADIX+digit)" not in positive_source:
    raise SystemExit("positive digit guard or checked accumulation no longer matches its scalar proof")
if "ensureresult.valid==(value>I64_MIN/DECIMAL_RADIXor(value==I64_MIN/DECIMAL_RADIXanddigit<=0-(I64_MIN%DECIMAL_RADIX)))" not in negative_source or \
        "limit:i64=I64_MIN/DECIMAL_RADIX" not in negative_source or \
        "final_digit_limit:i64=0-(I64_MIN%DECIMAL_RADIX)" not in negative_source or \
        "return(false,0)ifvalue<limit" not in negative_source or \
        "return(false,0)ifvalue==limitanddigit>final_digit_limit" not in negative_source or \
        "return(true,value*DECIMAL_RADIX-digit)" not in negative_source:
    raise SystemExit("negative digit guard or checked accumulation no longer matches its scalar proof")
if f"ensureresult==({positive_guard})" not in arithmetic_compact or \
        f"return{positive_guard}" not in arithmetic_compact or \
        f"ensureresult==({negative_guard})" not in arithmetic_compact or \
        f"return{negative_guard}" not in arithmetic_compact:
    raise SystemExit("scalar proof guard formulas no longer match the reduced production thresholds")
positive_range_proof = compact(function_section(arithmetic_text, "positive_digit_accumulation_stays_below_max"))
negative_range_proof = compact(function_section(arithmetic_text, "negative_digit_accumulation_stays_above_min"))
if f"returnvalue*{radix}+digit>=0andvalue*{radix}+digit<={i64_max}" not in positive_range_proof or \
        f"returnvalue*{radix}-digit>=0-{i64_max}-1andvalue*{radix}-digit<=0" not in negative_range_proof:
    raise SystemExit("scalar arithmetic proofs no longer establish both signed i64 bounds")
ascii_offset_proof = compact(function_section(arithmetic_text, "ascii_digit_byte_offset_is_in_range"))
if "requiresbyte>=48andbyte<=57" not in ascii_offset_proof or \
        "returnbyte-48>=0andbyte-48<=9" not in ascii_offset_proof:
    raise SystemExit("ASCII digit proof no longer covers the exact accepted byte interval")
positive_first_digit = compact(function_section(arithmetic_text, "positive_accumulator_accepts_first_digit"))
negative_first_digit = compact(function_section(arithmetic_text, "negative_accumulator_accepts_first_digit"))
if "requiresdigit>=0anddigit<=9" not in positive_first_digit or \
        "return0<922337203685477580or(0==922337203685477580anddigit<=7)" not in positive_first_digit or \
        "requiresdigit>=0anddigit<=9" not in negative_first_digit or \
        "return0>-922337203685477580or(0==-922337203685477580anddigit<=8)" not in negative_first_digit:
    raise SystemExit("first-digit proofs no longer establish acceptance from the zero accumulator")
arithmetic_names = {
    "positive_digit_guard",
    "positive_digit_accumulation_stays_below_max",
    "negative_digit_guard",
    "negative_digit_accumulation_stays_above_min",
    "positive_final_digit_reaches_i64_max",
    "negative_final_digit_reaches_i64_min",
    "ascii_digit_byte_offset_is_in_range",
    "positive_accumulator_accepts_first_digit",
    "negative_accumulator_accepts_first_digit",
}
arithmetic_false_names = {
    "false_claim_positive_overflow_digit_is_guarded",
    "false_claim_negative_underflow_digit_is_guarded",
}
if declaration_names(ARITH_POSITIVE) != arithmetic_names or \
        declaration_names(ARITH_NEGATIVE) != arithmetic_false_names:
    raise SystemExit("checked-decimal arithmetic proof inventory changed")

parser_body = parser_text.split("def easm_parse_i64_checked(text: sview)", 1)[1].split(
    "def easm_parse_i64(text: sview)", 1
)[0]
required_parser_fragments = (
    "ensure result.valid == EasmCheckedDecimal::decimal_parse_reference(text).valid",
    "ensure result.value == EasmCheckedDecimal::decimal_parse_reference(text).value",
    "ensure not result.valid implies result.value == 0",
    "return EasmCheckedDecimal::parse_signed(text)",
)
if not all(fragment in parser_body for fragment in required_parser_fragments):
    raise SystemExit("EASM parser no longer delegates to the source-verified signed-decimal parser")
if "break if byte <" in parser_body or "value <- value *" in parser_body:
    raise SystemExit("EASM parser bypasses strict digit validation or checked accumulation")
if "value: i64 = easm_parse_i64(easm_trim(fact[marker + 7.usize():sview_len(fact)]))" not in memory_text:
    raise SystemExit("size-guard facts no longer use the hardened signed-decimal parser")
size_bound_source = compact(function_section(memory_text, "easm_size_guard_lower_bound"))
if "greatest<-EasmMemStateDomain::greatest_bound(greatest,value)" not in size_bound_source:
    raise SystemExit("size-guard facts no longer combine parsed values in the proved lower-bound domain")
unchecked_parse_source = compact(function_section(parser_text, "easm_parse_i64"))
if "parsed:(valid:bool,value:i64)=easm_parse_i64_checked(text)" not in unchecked_parse_source or \
        "returnparsed.valueifparsed.validelse0" not in unchecked_parse_source:
    raise SystemExit("legacy size-fact parser no longer maps rejected decimals to the proved zero sentinel")

layout_parser_text = LAYOUT_PARSER.read_text()
layout_parse_body = layout_parser_text.split(
    "def parse_layout_module(source: darray[u8]&", 1
)[1].split("def parse_module(", 1)[0]
required_layout_fragments = (
    "easm_parse_i64_checked(easm_trim(attributes[5:sview_len(attributes)]))",
    '"invalid-layout-size"',
    "if not parsed_size.valid",
    "easm_parse_i64_checked(easm_trim(attributes[7:sview_len(attributes)]))",
    '"invalid-layout-stride"',
    "if not parsed_stride.valid",
    "easm_parse_i64_checked(easm_trim(rest[guard_start:sview_len(rest)]))",
    '"invalid-layout-required-size"',
    "if not parsed_requirement.valid",
    "easm_parse_i64_checked(offset_text)",
    '"invalid-layout-field-offset"',
    "numeric_offset_prefix and parsed_offset.valid and requires_size_valid",
)
if not all(fragment in layout_parse_body for fragment in required_layout_fragments):
    raise SystemExit("EASM layout parser no longer rejects malformed or overflowing decimal fields")

required_memory_fragments = (
    "def easm_memory_displacement_checked(operand: sview)",
    "ensure not result.valid implies result.value == 0",
    "return easm_parse_i64_checked(prefix)",
    '"invalid-memory-displacement"',
    "easm_memory_displacement_checked(operand)",
    "def easm_immediate_operand_after_dollar_checked(operand: sview)",
    'dollar: usize = easm_find(operand, "$")',
    "parsed: (valid: bool, value: i64) = easm_parse_i64_checked(easm_trim(operand[dollar + 1.usize():sview_len(operand)]))",
    "parsed.value < -2147483648 or parsed.value > 2147483647",
    "def easm_immediate_after_dollar_checked(text: sview)",
    "return easm_immediate_operand_after_dollar_checked(easm_first_operand(text))",
)
if not all(fragment in memory_text for fragment in required_memory_fragments):
    raise SystemExit("EASM memory and immediate decimal consumers no longer fail closed")
if '"invalid-stack-adjustment"' not in parser_text or "easm_immediate_operand_after_dollar_checked(source_operand)" not in parser_text:
    raise SystemExit("stack adjustment verification no longer reports malformed immediates")

required_integration_fragments = (
    '"invalid-layout-required-size"',
    "8junk",
    "9223372036854775808",
    "-9223372036854775809",
    '"invalid-layout-field-offset"',
    '"invalid-layout-size"',
    "overflowing_size",
    '"invalid-layout-stride"',
    '"invalid-stack-adjustment"',
    '"invalid-memory-displacement"',
    '"9223372036854775807"',
    '"-9223372036854775808"',
)
integration_text = INTEGRATION.read_text()
if not all(fragment in integration_text for fragment in required_integration_fragments):
    raise SystemExit("EASM decimal integration smoke lost a malformed-input or i64-boundary control")

stdin_driver_text = STDIN_DRIVER.read_text()
if "issues: darray[Easm::Issue] = parsed.issues" not in stdin_driver_text:
    raise SystemExit("EASM stdin verifier no longer preserves parser diagnostics")
enforcement_text = ENFORCEMENT_TEST.read_text()
required_driver_controls = (
    "def required_size_source(value: str) -> str:",
    '("malformed", "8junk")',
    '("overflow", "9223372036854775808")',
    '"invalid-layout-required-size" not in codes',
)
if not all(fragment in enforcement_text for fragment in required_driver_controls):
    raise SystemExit("EASM stdin integration controls lost malformed/overflow required-size rejection")

positive_names = {
    "positive_digit_step_obeys_its_exact_i64_boundary",
    "negative_digit_step_obeys_its_exact_i64_boundary",
    "positive_digit_step_preserves_the_i64_range",
    "negative_digit_step_preserves_the_i64_range",
    "positive_ascii_digit_byte_step_preserves_the_i64_range",
    "negative_ascii_digit_byte_step_preserves_the_i64_range",
    "positive_i64_max_is_reached_without_overflow",
    "negative_i64_min_is_reached_without_overflow",
    "signed_parser_accepts_only_well_formed_decimal_bytes",
    "signed_parser_returns_zero_on_every_rejection",
    "signed_parser_matches_independent_recursive_reference",
    "nonpositive_decimal_size_fact_does_not_strengthen_an_existing_bound",
    "rejected_decimal_does_not_strengthen_an_existing_bound",
    "signed_parser_preserves_the_sign_of_every_valid_result",
    "signed_parser_rejects_empty_or_incomplete_signs",
    "signed_parser_computes_both_i64_extremes",
    "signed_parser_rejects_both_i64_overflows",
}
parser_false_names = (
    "positive_i64_overflow_is_accepted",
    "negative_i64_underflow_is_accepted",
    "signed_parser_accepts_a_nondigit",
    "signed_parser_always_disagrees_with_independent_recursive_reference",
    "signed_parser_accepts_positive_overflow",
    "signed_parser_accepts_negative_underflow",
    "signed_parser_returns_positive_for_negative_input",
    "signed_parser_returns_negative_for_positive_input",
    "rejected_decimal_can_strengthen_a_nonnegative_size_bound",
)
if declaration_names(POSITIVE) != positive_names or declaration_names(NEGATIVE) != set(parser_false_names):
    raise SystemExit("checked-decimal parser proof declaration inventory changed")
negative_text = NEGATIVE.read_text()
negative_proof_shapes = {
    "positive_i64_overflow_is_accepted": (
        "EasmCheckedDecimal::append_positive_digit(",
        "returnstep.valid",
    ),
    "negative_i64_underflow_is_accepted": (
        "EasmCheckedDecimal::append_negative_digit(",
        "returnstep.valid",
    ),
    "signed_parser_accepts_a_nondigit": (
        'EasmCheckedDecimal::parse_signed("7x")',
        "returnparsed.valid",
    ),
    "signed_parser_always_disagrees_with_independent_recursive_reference": (
        "EasmCheckedDecimal::parse_signed(text)",
        "EasmCheckedDecimal::decimal_parse_reference(text)",
        "returnparsed.valid!=reference.validorparsed.value!=reference.value",
    ),
    "signed_parser_accepts_positive_overflow": (
        'EasmCheckedDecimal::parse_signed("9223372036854775808")',
        "returnparsed.valid",
    ),
    "signed_parser_accepts_negative_underflow": (
        'EasmCheckedDecimal::parse_signed("-9223372036854775809")',
        "returnparsed.valid",
    ),
    "signed_parser_returns_positive_for_negative_input": (
        'EasmCheckedDecimal::parse_signed("-1")',
        "returnparsed.validandparsed.value>0",
    ),
    "signed_parser_returns_negative_for_positive_input": (
        'EasmCheckedDecimal::parse_signed("1")',
        "returnparsed.validandparsed.value<0",
    ),
    "rejected_decimal_can_strengthen_a_nonnegative_size_bound": (
        "EasmCheckedDecimal::parse_signed(text)",
        "returnnotparsed.validandEasmMemStateDomain::greatest_bound(current,parsed.value)>current",
    ),
}
for name, fragments in negative_proof_shapes.items():
    body = compact(function_section(negative_text, name))
    if not all(fragment in body for fragment in fragments):
        raise SystemExit(f"negative proof {name} no longer exercises its intended production case")
for name in positive_names:
    if f"def {name}(" not in POSITIVE.read_text():
        raise SystemExit(f"positive theorem missing: {name}")
positive_text = POSITIVE.read_text()
parse_equivalence_shape = (
    "ensure result == true "
    "parsed: (valid: bool, value: i64) = EasmCheckedDecimal::parse_signed(text) "
    "reference: (valid: bool, value: i64) = EasmCheckedDecimal::decimal_parse_reference(text) "
    "return parsed.valid == reference.valid and parsed.value == reference.value"
)
if compact(parse_equivalence_shape) not in compact(function_section(
        positive_text, "signed_parser_matches_independent_recursive_reference")):
    raise SystemExit("decimal refinement theorem no longer compares parser and independent reference results")
sign_proof = compact(function_section(
    positive_text, "signed_parser_preserves_the_sign_of_every_valid_result"
))
if "parsed:(valid:bool,value:i64)=EasmCheckedDecimal::parse_signed(text)" not in sign_proof or \
        "text[0]==EasmCheckedDecimal::ASCII_MINUSandparsed.value<=0" not in sign_proof or \
        "text[0]!=EasmCheckedDecimal::ASCII_MINUSandparsed.value>=0" not in sign_proof:
    raise SystemExit("signed parser sign theorem no longer checks the production parser result")
edge_proof = compact(function_section(
    positive_text, "signed_parser_rejects_empty_or_incomplete_signs"
))
if not all(fragment in edge_proof for fragment in (
    'EasmCheckedDecimal::parse_signed("")',
    'EasmCheckedDecimal::parse_signed("-")',
    'EasmCheckedDecimal::parse_signed("+1")',
    "notempty.validandempty.value==0",
    "notsign_only.validandsign_only.value==0",
    "notplus_sign.validandplus_sign.value==0",
)):
    raise SystemExit("signed parser edge proof no longer checks empty, sign-only, and plus-prefixed inputs")
invalid_bound_proof = compact(function_section(
    positive_text, "nonpositive_decimal_size_fact_does_not_strengthen_an_existing_bound"
))
if "requirescurrent>=0" not in invalid_bound_proof or \
        "EasmCheckedDecimal::parse_signed(text)" not in invalid_bound_proof or \
        "parsed.value>0orEasmMemStateDomain::greatest_bound(current,parsed.value)==current" not in invalid_bound_proof:
    raise SystemExit("nonpositive decimal size-fact theorem no longer connects parser output to the production bound join")
rejected_bound_proof = compact(function_section(
    positive_text, "rejected_decimal_does_not_strengthen_an_existing_bound"
))
if "requirescurrent>=0" not in rejected_bound_proof or \
        "parsed:(valid:bool,value:i64)=EasmCheckedDecimal::parse_signed(text)" not in rejected_bound_proof or \
        "ifnotparsed.valid:returnEasmMemStateDomain::greatest_bound(current,parsed.value)==current" not in rejected_bound_proof:
    raise SystemExit("rejected-decimal theorem no longer proves that the zero sentinel leaves a nonnegative bound unchanged")
for sign in ("positive", "negative"):
    name = f"{sign}_ascii_digit_byte_step_preserves_the_i64_range"
    body = positive_text.split(f"def {name}(", 1)[1].split("\ndef ", 1)[0]
    if "byte - EasmCheckedDecimal::ASCII_DIGIT_ZERO" not in body:
        raise SystemExit(f"{name} no longer proves the production ASCII-byte-to-digit mapping")
    if f"EasmCheckedDecimal::append_{sign}_digit(value, digit)" not in body:
        raise SystemExit(f"{name} no longer applies the production checked-digit helper")

if ARGS.source_only:
    print(json.dumps({
        "source_bound": True,
        "parser_positive_declarations": len(positive_names),
        "parser_false_controls": len(parser_false_names),
        "arithmetic_positive_declarations": len(arithmetic_names),
        "arithmetic_false_controls": len(arithmetic_false_names),
    }, sort_keys=True))
    raise SystemExit(0)

try:
    product_manifest = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if product_manifest.get("compile_mode") != "strict":
    raise SystemExit("checked-decimal proof requires a strict proof build")

stage1_product = Path(product_manifest["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = [
    BIN,
    MANIFEST,
    MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV",
    stage1_product,
    stage1_provenance,
    Path(__file__),
    HERE / "proof_product_gate.py",
    POSITIVE,
    NEGATIVE,
    ARITH_POSITIVE,
    ARITH_NEGATIVE,
    HELPER,
    ENV,
    PARSER,
    MEMORY,
    MEMSTATE,
    LAYOUT_PARSER,
    INTEGRATION,
    STDIN_DRIVER,
    ENFORCEMENT_TEST,
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
assert positive == run(POSITIVE)[1], "proof report changed across repeated runs"
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert positive_names <= verified

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert negative["summary"]["proven"] + len(parser_false_names) == negative["summary"]["obligations"]
assert [(finding["kind"], finding["name"]) for finding in negative["findings"]] == [
    ("ensure-unproven", name) for name in parser_false_names
]
negative_verified = {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert not set(parser_false_names) & negative_verified

code, arithmetic_positive = run(ARITH_POSITIVE)
assert code == 0 and arithmetic_positive["status"] == arithmetic_positive["verification_state"] == "proved"
assert arithmetic_positive["summary"]["declarations"] == len(arithmetic_names)
assert arithmetic_positive["summary"]["proven"] == arithmetic_positive["summary"]["obligations"]
assert not arithmetic_positive["findings"]
assert arithmetic_positive == run(ARITH_POSITIVE)[1], "arithmetic proof report changed across repeated runs"
assert {row["name"] for row in arithmetic_positive["declaration_details"] if row.get("verified")} == arithmetic_names

code, arithmetic_negative = run(ARITH_NEGATIVE)
assert code == 1 and arithmetic_negative["status"] == "failed"
assert arithmetic_negative["summary"]["declarations"] == len(arithmetic_names) + len(arithmetic_false_names)
assert arithmetic_negative["summary"]["proven"] + len(arithmetic_false_names) == arithmetic_negative["summary"]["obligations"]
assert {finding["name"] for finding in arithmetic_negative["findings"]} == arithmetic_false_names
assert all(finding["kind"] == "ensure-unproven" for finding in arithmetic_negative["findings"])
assert not arithmetic_false_names & {row["name"] for row in arithmetic_negative["declaration_details"] if row.get("verified")}

assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product_manifest, "proof-product provenance changed during replay"
print(json.dumps({
    "admitted": True,
    "scope": "signed decimal parser refines an independent recursive byte-fold specification, preserves input sign, rejects empty/sign-only/plus-prefixed inputs, accepts only signed ASCII decimal input, zeroes rejection without strengthening nonnegative memory-size bounds, and covers both i64 boundaries",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": [finding["name"] for finding in negative["findings"]],
    "arithmetic_obligations": arithmetic_positive["summary"]["proven"],
    "arithmetic_false_claims_rejected": sorted(arithmetic_false_names),
    "proof_binary_sha256": hashlib.sha256(BIN.read_bytes()).hexdigest(),
    "proof_revision": product_manifest["proof"].get("head"),
    "compiler_revision": product_manifest["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
