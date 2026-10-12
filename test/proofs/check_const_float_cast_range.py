"""Admit constant float-cast range proofs against the strict proof product."""
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
POSITIVE = HERE / "const_float_cast_range.elisa"
NEGATIVE = HERE / "const_float_cast_range_rejected.elisa"
SIGN_POSITIVE = HERE / "const_float_cast_sign_parity.elisa"
SIGN_NEGATIVE = HERE / "const_float_cast_sign_parity_rejected.elisa"
RANGE = ROOT / "src/semantic/const_float_cast_range.elisa"
CHECKER = ROOT / "src/semantic/check_const_float_cast.elisa"
CODEGEN_TYPES = ROOT / "src/backend/codegen_value_type.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
PARITY = ROOT / "test/parity/const_float_cast_smoke.sh"

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in text.splitlines())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one production function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


semantic_text = SEMANTIC.read_text()
range_text = RANGE.read_text()
checker_text = CHECKER.read_text()
parity_text = PARITY.read_text()
if 'include "./const_float_cast_range.elisa"' not in semantic_text or \
        semantic_text.index('include "./const_float_cast_range.elisa"') > semantic_text.index('include "./check_const_float_cast.elisa"'):
    raise SystemExit("constant cast range helper must be included before its semantic consumer")

semantic_range_check = compact(function_section(checker_text, "const_float_cast_invalid"))
if "pointer_bits:u32=const_float_target_pointer_bits()" not in semantic_range_check or \
        "ConstFloatCastRange::cast_out_of_range(target,negative,text,pointer_bits)" not in semantic_range_check:
    raise SystemExit("constant float cast diagnostics no longer consume the verified shared range decision")
if "false return if negative" in semantic_range_check or "decimal_integer_exceeds(text,limit)" in semantic_range_check:
    raise SystemExit("semantic cast check bypasses the sign-sensitive shared range helper")

limit_impl = compact(function_section(range_text, "integer_magnitude_limit"))
for target, negative, positive in (
    ("i8", "128", "127"),
    ("i16", "32768", "32767"),
    ("i32", "2147483648", "2147483647"),
):
    fragment = f'"{target}"->"{negative}"ifnegativeelse"{positive}"'
    if fragment not in limit_impl:
        raise SystemExit(f"signed {target} lower/upper magnitudes changed without updating the proof specification")
if '"i64"->"9223372036854775808"ifnegativeelse"9223372036854775807"' not in limit_impl or \
        '"int"|"isize"->"2147483648"ifpointer_bits==32andnegativeelse"2147483647"ifpointer_bits==32else"9223372036854775808"ifnegativeelse"9223372036854775807"' not in limit_impl:
    raise SystemExit("signed 64-bit or target-sized bound table changed without proof updates")
contract_fragments = (
    '(result=="128")== (target=="i8"andnegative)',
    '(result=="127")== (target=="i8"andnotnegative)',
    '(result=="32768")== (target=="i16"andnegative)',
    '(result=="32767")== (target=="i16"andnotnegative)',
    '(result=="9223372036854775808")== ((target=="i64"or((target=="int"ortarget=="isize")andpointer_bits==64))andnegative)',
    '(result=="2147483648")== ((target=="i32"or((target=="int"ortarget=="isize")andpointer_bits==32))andnegative)',
    '(result=="2147483647")== ((target=="i32"or((target=="int"ortarget=="isize")andpointer_bits==32))andnotnegative)',
    '(result=="18446744073709551615")== ((target=="u64"or((target=="usize"ortarget=="uintptr")andpointer_bits==64))andnotnegative)',
    '(result=="4294967295")== ((target=="u32"or((target=="usize"ortarget=="uintptr")andpointer_bits==32))andnotnegative)',
)
if not all(fragment.replace(" ", "") in limit_impl for fragment in contract_fragments):
    raise SystemExit("integer bound helper lost a literal-linked Boolean postcondition")
for target in ("u8", "u16", "u32"):
    if f'"{target}"->""ifnegativeelse' not in limit_impl:
        raise SystemExit(f"negative unsigned {target} magnitude limit changed")
if '"u64"->""ifnegativeelse"18446744073709551615"' not in limit_impl or \
        '"usize"|"uintptr"->""ifnegativeelse"4294967295"ifpointer_bits==32else"18446744073709551615"' not in limit_impl:
    raise SystemExit("wide unsigned or target-sized magnitude limit changed")

range_decision = compact(function_section(range_text, "cast_out_of_range"))
decision_order = (
    'falsereturniftext==""',
    'boundary:sview=float_cast_rounding_boundary(target,negative,pointer_bits)',
    'returnfalseifboundary==""',
    'decimal_value_compare(text,boundary)',
    'ifnegativeand(target=="i64"or((target=="int"ortarget=="isize")andpointer_bits==64)):returnmagnitude.comparison>0',
    'returnmagnitude.comparison>=0',
)
positions = [range_decision.find(fragment) for fragment in decision_order]
if any(position < 0 for position in positions) or positions != sorted(positions):
    raise SystemExit("cast range decision no longer composes sign-zero handling, exact decimal comparison, and rounding guards")

for name, expected in (
    ("decimal_is_exponent_marker", "returnwhenbyte:101|69->true_->false"),
    ("decimal_is_digit", "returnwhenbyte:48|49|50|51|52|53|54|55|56|57->true_->false"),
    ("decimal_exponent_sign", "returnwhenbyte:45->0-143->1_->0"),
):
    if expected not in compact(function_section(range_text, name)):
        raise SystemExit(f"{name} no longer classifies its closed byte set by patterns")

decimal_compare = compact(function_section(range_text, "decimal_value_compare"))
if "exponent_position<-scan" not in decimal_compare or "decimal_position<-whole_digits_i64+exponent_magnitude" not in decimal_compare or \
        "input_order:i64=decimal_position-first_nonzero_i64" not in decimal_compare or \
        "limit_order:i64=limit_decimal_position.i64()-limit_first_nonzero.i64()" not in decimal_compare or \
        "whilesource_cursor<exponent_positionorlimit_cursor<limit_length" not in decimal_compare or "magnitude_zero" not in decimal_compare:
    raise SystemExit("decimal comparator no longer normalizes significands and exponent scales")

boundary_impl = compact(function_section(range_text, "float_cast_rounding_boundary"))
for threshold in (
    "127.99999999999999289457264239899814128875732421875",
    "128.9999999999999857891452847979962825775146484375",
    "0.999999999999999944488848768742172978818416595458984375",
    "9223372036854775296",
    "9223372036854776832",
    "18446744073709550592",
):
    if threshold not in boundary_impl:
        raise SystemExit(f"binary64 rounding boundary {threshold} changed without proof updates")
boundary_contracts = (
    '(result=="127.99999999999999289457264239899814128875732421875")== (target=="i8"andnotnegative)',
    '(result=="128.9999999999999857891452847979962825775146484375")== (target=="i8"andnegative)',
    '(result=="2147483647.99999988079071044921875")==((target=="i32"or((target=="int"ortarget=="isize")andpointer_bits==32))andnotnegative)',
    '(result=="2147483648.9999997615814208984375")==((target=="i32"or((target=="int"ortarget=="isize")andpointer_bits==32))andnegative)',
    '(result=="9223372036854775296")==((target=="i64"or((target=="int"ortarget=="isize")andpointer_bits==64))andnotnegative)',
    '(result=="9223372036854776832")==((target=="i64"or((target=="int"ortarget=="isize")andpointer_bits==64))andnegative)',
    '(result=="4294967295.9999997615814208984375")==((target=="u32"or((target=="usize"ortarget=="uintptr")andpointer_bits==32))andnotnegative)',
    '(result=="18446744073709550592")==((target=="u64"or((target=="usize"ortarget=="uintptr")andpointer_bits==64))andnotnegative)',
    '(result=="0.999999999999999944488848768742172978818416595458984375")==((target=="u8"ortarget=="u16"ortarget=="u32"ortarget=="u64"ortarget=="usize"ortarget=="uintptr")andnegative)',
)
if not all(contract.replace(" ", "") in boundary_impl for contract in boundary_contracts):
    raise SystemExit("rounding-boundary postconditions no longer link target widths to exact thresholds")
if "elifbyte!='_'" not in decimal_compare or "exponent_digit_byte!='_'" not in decimal_compare or \
        "text[source_cursor]=='.'ortext[source_cursor]=='_'" not in decimal_compare:
    raise SystemExit("decimal comparator no longer handles legal digit separators in mantissas and exponents")

semantic_target_bits = compact(function_section(checker_text, "const_float_target_pointer_bits"))
backend_target_bits = compact(function_section(CODEGEN_TYPES.read_text(), "target_pointer_bits"))
if '32returnifgetenv("ELISA_STAGE1_WASM")iswasm_targetreturn64' not in semantic_target_bits or \
        '32returnifgetenv("ELISA_STAGE1_WASM")iswasm_targetreturn64' not in backend_target_bits:
    raise SystemExit("semantic cast checking no longer matches backend pointer-width selection")

sign_step = compact(function_section(range_text, "negative_after_unary"))
parity_contract = "((is_minusandnotoperand_is_negative)or(notis_minusandoperand_is_negative))"
parity_return = "(is_minusandnotoperand_is_negative)or(notis_minusandoperand_is_negative)"
sign_spec = compact(function_section(SIGN_POSITIVE.read_text(), "negative_after_unary_boolean_spec"))
if f"ensureresult=={parity_contract}" not in sign_step or \
        f"return{parity_return}" not in sign_step or \
        f"ensureresult=={parity_contract}" not in sign_spec or \
        f"return{parity_return}" not in sign_spec:
    raise SystemExit("unary sign parity step lost its Boolean specification")
negative_sign = compact(function_section(checker_text, "const_float_negative"))
if "ConstFloatCastRange::negative_after_unary(true,const_float_negative(operand))" not in negative_sign or \
        "ConstFloatCastRange::negative_after_unary(false,const_float_negative(operand))" not in negative_sign or \
        "truereturnifoperator==TokenKind.Minus" in negative_sign:
    raise SystemExit("AST unary sign handling no longer composes minus parity and plus identity")

parity_controls = (
    "NEG_BIG_TO_I8",
    "NEG_BIG_TO_I64",
    "NEG_ROUNDS_TO_MIN_I64",
    "NEG_MIN_I8",
    "NEG_MIN_I64",
    "EXPONENT_TO_I8",
    "EXPONENT_OVER_I8",
    "DOUBLE_NEG_POSITIVE_OVERFLOW",
    "DOUBLE_NEG_SMALL_I8",
    "ROUNDING_NEAR_I8_MAX",
    "ROUNDING_NEAR_I8_MIN",
    "NEG_U8_NEAR_ONE",
    "I64_POS_ROUNDING_MIDPOINT",
    "NEG_FRACTION_U32",
    "BIG_TO_U64",
    "NEG_ZERO_U32",
    "WASM32_INT_BOUNDARY",
    "WASM32_USIZE_BOUNDARY",
    "WASM32_INT_NEG_MIDPOINT",
    "WASM32_ISIZE_NEG_MIDPOINT",
    "WASM64_INT_CONTROL",
    "WASM64_USIZE_CONTROL",
    "WASM64_INT_NEG_MIDPOINT",
    "EXP_SMALL_I8",
    "EXP_TINY_I8",
    "EXP_AT_LIMIT_I8",
)
if not all(control in parity_text for control in parity_controls):
    raise SystemExit("constant float-cast parity fixture lost a negative signed boundary case")

positive_names = {
    "signed_negative_limit_table_refines_its_spec",
    "signed_positive_limit_table_refines_its_spec",
    "target_signed_32_limit_table_refines_its_spec",
    "target_unsigned_32_limit_table_refines_its_spec",
    "one_unary_minus_flips_sign",
    "double_unary_minus_restores_positive_sign",
    "unary_plus_preserves_negative_sign",
    "negative_i8_minimum_is_in_range",
    "negative_i8_one_past_minimum_is_out_of_range",
    "negative_i16_minimum_is_in_range",
    "negative_i16_one_past_minimum_is_out_of_range",
    "negative_i32_minimum_is_in_range",
    "negative_i32_one_past_minimum_is_out_of_range",
    "negative_i64_minimum_is_in_range",
    "negative_i64_one_past_minimum_rounds_to_minimum",
    "negative_unsigned_cast_is_out_of_range",
    "negative_unsigned_zero_is_in_range",
    "negative_unsigned_fraction_truncates_to_zero",
    "negative_unsigned_rounding_neighbor_is_safe",
    "negative_unsigned_rounding_midpoint_is_out_of_range",
    "target_int_32_boundary_is_out_of_range",
    "target_int_64_boundary_is_in_range",
    "target_isize_32_minimum_is_in_range",
    "target_int_32_negative_rounding_midpoint_is_out_of_range",
    "target_isize_32_negative_rounding_midpoint_is_out_of_range",
    "target_int_64_negative_rounding_midpoint_is_safe",
    "target_usize_32_boundary_is_out_of_range",
    "target_usize_64_same_value_is_in_range",
    "ordinary_decimal_keeps_the_positive_i8_limit",
    "positive_i8_fraction_truncates_within_range",
    "negative_i8_fraction_truncates_within_range",
    "positive_u8_fraction_truncates_within_range",
    "positive_exponent_within_i8_range_is_accepted",
    "negative_exponent_below_one_is_accepted",
    "exponent_fraction_at_positive_limit_is_accepted",
    "exponent_fraction_one_above_positive_limit_is_rejected",
    "positive_rounding_adjacent_decimal_is_rejected_conservatively",
    "negative_rounding_adjacent_decimal_is_rejected_conservatively",
    "safe_i8_positive_rounding_neighbor_is_accepted",
    "i64_positive_rounding_midpoint_is_rejected",
    "safe_previous_i64_f64_is_accepted",
    "i64_negative_rounding_midpoint_is_safe",
    "i64_negative_rounding_after_midpoint_is_rejected",
}
negative_names = {
    "false_claim_negative_i8_overflow_is_in_range",
    "false_claim_negative_i64_overflow_is_in_range",
    "false_claim_negative_unsigned_cast_is_in_range",
    "false_claim_negative_unsigned_fraction_is_out_of_range",
    "false_claim_wasm32_usize_overflow_is_in_range",
    "false_claim_double_minus_is_negative",
    "false_claim_exponent_overflow_is_in_range",
    "false_claim_positive_rounding_adjacent_cast_is_safe",
    "false_claim_negative_rounding_adjacent_cast_is_safe",
}


def declaration_names(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


if declaration_names(POSITIVE) != positive_names:
    raise SystemExit("constant float-cast positive proof inventory changed")
if declaration_names(NEGATIVE) != negative_names or \
        'include "./const_float_cast_range.elisa"' not in NEGATIVE.read_text():
    raise SystemExit("constant float-cast false-claim inventory changed")

sign_positive_names = {
    "negative_after_unary_boolean_spec",
    "one_unary_minus_flips_sign",
    "double_unary_minus_restores_sign",
    "unary_plus_preserves_sign",
}
sign_negative_names = {"false_claim_double_minus_flips_sign"}
if declaration_names(SIGN_POSITIVE) != sign_positive_names or \
        declaration_names(SIGN_NEGATIVE) != sign_negative_names or \
        'include "./const_float_cast_sign_parity.elisa"' not in SIGN_NEGATIVE.read_text():
    raise SystemExit("constant float-cast sign-parity proof inventory changed")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("constant float-cast proofs require a strict proof build")

stage1_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", POSITIVE, NEGATIVE, SIGN_POSITIVE, SIGN_NEGATIVE,
    RANGE, CHECKER, CODEGEN_TYPES, SEMANTIC, PARITY,
    *source_include_closure([POSITIVE, NEGATIVE, SIGN_POSITIVE, SIGN_NEGATIVE]),
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
assert positive == run(POSITIVE)[1], "constant float-cast proof report changed across identical runs"
assert {row["name"] for row in positive["declaration_details"] if row.get("verified")} == positive_names

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == negative["verification_state"] == "failed"
assert negative["summary"]["declarations"] == len(positive_names) + len(negative_names)
assert negative["summary"]["proven"] + len(negative_names) == negative["summary"]["obligations"]
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" for row in negative["findings"])
assert not negative_names & {row["name"] for row in negative["declaration_details"] if row.get("verified")}

code, sign_positive = run(SIGN_POSITIVE)
assert code == 0 and sign_positive["status"] == sign_positive["verification_state"] == "proved"
assert sign_positive["summary"]["declarations"] == len(sign_positive_names)
assert sign_positive["summary"]["obligations"] == sign_positive["summary"]["proven"]
assert not sign_positive["findings"]
assert sign_positive == run(SIGN_POSITIVE)[1], "sign-parity proof report changed across identical runs"
assert {row["name"] for row in sign_positive["declaration_details"] if row.get("verified")} == sign_positive_names

code, sign_negative = run(SIGN_NEGATIVE)
assert code == 1 and sign_negative["status"] == "failed"
assert sign_negative["summary"]["declarations"] == len(sign_positive_names) + len(sign_negative_names)
assert sign_negative["summary"]["proven"] + len(sign_negative_names) == sign_negative["summary"]["obligations"]
assert {row["name"] for row in sign_negative["findings"]} == sign_negative_names
assert all(row["kind"] == "ensure-unproven" for row in sign_negative["findings"])
assert not sign_negative_names & {row["name"] for row in sign_negative["declaration_details"] if row.get("verified")}

assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product
print(json.dumps({
    "admitted": True,
    "scope": "binary64 rounding, truncation, signedness, exponents, and target-sized integer bounds",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": sorted(negative_names),
    "sign_parity_obligations": sign_positive["summary"]["proven"],
    "sign_parity_false_claims_rejected": sorted(sign_negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
}, sort_keys=True))
