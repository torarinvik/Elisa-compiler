"""Admit source-linked contracts for Semantic's checked signed arithmetic."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure

argument_parser = argparse.ArgumentParser()
argument_parser.add_argument("--source-only", action="store_true",
                             help="check production and proof bindings without running Elisa-Proof")
ARGS = argument_parser.parse_args()
from source_guard_compat import expand_return_if_blocks
ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=not ARGS.source_only)
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
SOURCE = ROOT / "src/semantic/check_ensure_strict.elisa"
ARITHMETIC = ROOT / "src/semantic/linear_checked_arithmetic.elisa"
SEMANTIC_SOURCES = ROOT / "src/semantic"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
PARSER = ROOT / "src/parser/parser.elisa"
PARSER_TOKENS = ROOT / "src/parser/parser_tokens.elisa"
LEXER = ROOT / "src/lexer/lexer.elisa"
TOKEN_KIND = ROOT / "src/lexer/tokens.elisa"
TOKEN_KIND_PROJECTION = HERE / "parser_token_kind_projection.elisa"
POSITIVE = HERE / "linear_neg_overflow.elisa"
NEGATIVE = HERE / "linear_neg_overflow_rejected.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    return "".join("".join(line.split("#", 1)[0].split()) for line in expand_return_if_blocks(text).splitlines())


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"^[ \t]*def {re.escape(name)}\(", source, re.MULTILINE))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    start = matches[0].start()
    following = re.search(r"^[ \t]*def [A-Za-z_][A-Za-z0-9_]*\(", source[matches[0].end():], re.MULTILINE)
    end = matches[0].end() + following.start() if following else len(source)
    return source[start:end]


def token_kind_variants(source: str) -> list[str]:
    match = re.search(r"(?ms)^\s*const enum TokenKind of u8:\n(.*?)(?=^\s*(?:struct|const enum|def) |\Z)", source)
    if not match:
        raise SystemExit("could not find the TokenKind enum projection")
    return [line.strip() for line in match.group(1).splitlines()
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", line.strip())]


source_text = ARITHMETIC.read_text()
semantic_text = SEMANTIC.read_text()
legacy_text = SOURCE.read_text()
maximum = compact(function_section(source_text, "linear_i64_max"))
minimum = compact(function_section(source_text, "linear_i64_min"))
if "return9223372036854775807" not in maximum:
    raise SystemExit("linear_i64_max no longer returns the signed 64-bit upper bound")
if "return0-9223372036854775807-1" not in minimum:
    raise SystemExit("linear_i64_min no longer returns the signed 64-bit lower bound")

negate = compact(function_section(source_text, "linear_neg_safe"))
if "ensureresult.known==(operand!=linear_i64_min())" not in negate or \
        "ensureresult.knownimpliesresult.value==0-operand" not in negate or \
        "ensurenotresult.knownimpliesresult.value==0" not in negate or \
        "returnlinear_sub_safe(0,operand)" not in negate:
    raise SystemExit("linear_neg_safe no longer exports its exact checked-negation result")

sub = compact(function_section(source_text, "linear_sub_safe"))
if "ensureresult.known==(right==0or(right>0andleft>=linear_i64_min()+right)or(right<0andleft<=linear_i64_max()+right))" not in sub or \
        "ensureresult.knownimpliesresult.value==left-right" not in sub or \
        "ensurenotresult.knownimpliesresult.value==0" not in sub:
    raise SystemExit("linear_sub_safe no longer exports exact success and fail-closed value contracts")
addition = compact(function_section(source_text, "linear_add_safe"))
if "ensureresult.known==(right==0or(right>0andleft<=linear_i64_max()-right)or(right<0andleft>=linear_i64_min()-right))" not in addition or \
        "ensureresult.knownimpliesresult.value==left+right" not in addition or \
        "ensurenotresult.knownimpliesresult.value==0" not in addition:
    raise SystemExit("linear_add_safe no longer exports exact range and fail-closed value contracts")
multiply = compact(function_section(source_text, "linear_mul_safe"))
multiply_guard = compact(function_section(source_text, "linear_mul_guard"))
for fragment in (
        "ensure result == (",
        "left==0orright==0orleft==1orright==1",
        "(left==-1andright!=linear_i64_min())",
        "(right==-1andleft!=linear_i64_min())",
        "left<=linear_i64_max()/right",
        "right>=linear_i64_min()/left",
        "left>=linear_i64_min()/right",
        "left>=linear_i64_max()/right",
):
    if compact(fragment) not in multiply_guard:
        raise SystemExit(f"linear_mul_guard lost its exact signed-range contract fragment: {fragment}")
if not all(compact(fragment) in multiply for fragment in (
        "ensure result.known == linear_mul_guard(left, right)",
        "ensure result.known implies result.value == left * right",
        "ensure not result.known implies result.value == 0",
        "if not linear_mul_guard(left, right): return (false, 0)",
        "return (true, left * right)",
)):
    raise SystemExit("linear_mul_safe no longer checks the proved range guard before multiplying")
sub_guards = (
    "return(false,0)ifright>0andleft<linear_i64_min()+right",
    "return(false,0)ifright<0andleft>linear_i64_max()+right",
    "return(true,left-right)",
)
positions = [sub.find(fragment) for fragment in sub_guards]
if any(position < 0 for position in positions) or positions != sorted(positions):
    raise SystemExit("checked subtraction must reject both underflow and overflow before returning the difference")
dispatcher = compact(function_section(source_text, "linear_arith_safe"))
for fragment in (
        "ensure(operator==TokenKind.Plus)implies(result.known==linear_add_safe(left,right).knownandresult.value==linear_add_safe(left,right).value)",
        "ensure(operator==TokenKind.Minus)implies(result.known==linear_sub_safe(left,right).knownandresult.value==linear_sub_safe(left,right).value)",
        "ensure(operator==TokenKind.Star)implies(result.known==linear_mul_safe(left,right).knownandresult.value==linear_mul_safe(left,right).value)",
        "ensure(operator!=TokenKind.Plusandoperator!=TokenKind.Minusandoperator!=TokenKind.Star)implies(notresult.knownandresult.value==0)",
):
    if fragment not in dispatcher:
        raise SystemExit(f"linear_arith_safe lost its exact dispatch contract fragment: {fragment}")
dispatch_guards = (
    "returnlinear_add_safe(left,right)ifoperator==TokenKind.Plus",
    "returnlinear_sub_safe(left,right)ifoperator==TokenKind.Minus",
    "returnlinear_mul_safe(left,right)ifoperator==TokenKind.Star",
    "return(false,0)",
)
dispatch_positions = [dispatcher.find(fragment) for fragment in dispatch_guards]
if any(position < 0 for position in dispatch_positions) or dispatch_positions != sorted(dispatch_positions):
    raise SystemExit("linear_arith_safe must dispatch +, -, * to their helpers and reject all other operators")
if 'include "./linear_checked_arithmetic.elisa"' not in semantic_text or \
        semantic_text.index('include "./linear_checked_arithmetic.elisa"') > semantic_text.index('include "./check_ensure_strict.elisa"'):
    raise SystemExit("semantic compilation no longer imports the proved arithmetic helper before its consumers")
for operation in ("add", "sub", "mul"):
    if f"linear_{operation}_safe(" not in legacy_text:
        raise SystemExit(f"strict linearization no longer uses the proved linear_{operation}_safe helper")
for consumer in (
        "check_index_out_of_bounds.elisa", "check_contract_result_void.elisa",
        "check_static_eval.elisa", "check_ensure_strict_const.elisa",
        "check_ensure_strict_guarded_return.elisa",
):
    include = f'include "./{consumer}"'
    if include not in semantic_text or semantic_text.index(include) < semantic_text.index('include "./linear_checked_arithmetic.elisa"'):
        raise SystemExit(f"semantic compilation no longer imports checked arithmetic before {consumer}")
    consumer_text = (SEMANTIC_SOURCES / consumer).read_text()
    if consumer_text.count("linear_arith_safe(") != 1:
        raise SystemExit(f"{consumer} no longer routes its single arithmetic fold through the proved dispatcher")
if 'include "../parser/parser.elisa"' not in semantic_text or \
        'include "./parser_tokens.elisa"' not in PARSER.read_text() or \
        'include "../lexer/lexer.elisa"' not in PARSER_TOKENS.read_text():
    raise SystemExit("production semantic compilation no longer imports the parser's Lexer TokenKind source")
if "type TokenKind = Lexer::TokenKind" not in LEXER.read_text():
    raise SystemExit("production TokenKind alias no longer resolves to Lexer::TokenKind")
if token_kind_variants(TOKEN_KIND.read_text()) != token_kind_variants(TOKEN_KIND_PROJECTION.read_text()):
    raise SystemExit("proof TokenKind projection differs from the production enum order")
semantic_sources = "\n".join(path.read_text() for path in SEMANTIC_SOURCES.glob("*.elisa"))
for name in ("linear_i64_max", "linear_i64_min", "linear_add_safe", "linear_sub_safe", "linear_mul_safe", "linear_neg_safe", "linear_arith_safe"):
    if len(re.findall(rf"(?m)^\s*def {name}\(", semantic_sources)) != 1:
        raise SystemExit(f"{name} must have exactly one production definition in the semantic layer")
    if re.search(rf"(?m)^\s*def {name}\(", legacy_text):
        raise SystemExit(f"{name} was duplicated in the legacy ensure checker instead of using the isolated helper")
positive_text = POSITIVE.read_text()
if 'include "./parser_token_kind_projection.elisa"' not in positive_text:
    raise SystemExit("positive proof no longer includes the checked TokenKind projection")
if 'include "../../src/semantic/linear_checked_arithmetic.elisa"' not in positive_text:
    raise SystemExit("positive proof no longer includes the production checked-arithmetic helper")
for operation in ("add", "sub", "mul"):
    wrapper = compact(function_section(positive_text, f"proof_linear_{operation}_safe"))
    wrapper_fragments = (
        f"def proof_linear_{operation}_safe(left: i64, right: i64) -> (known: bool, value: i64):",
        f"ensureresult.known==linear_{operation}_safe(left,right).known",
        f"ensureresult.value==linear_{operation}_safe(left,right).value",
        f"returnlinear_{operation}_safe(left,right)",
    )
    if any(compact(fragment) not in wrapper for fragment in wrapper_fragments):
        raise SystemExit(f"proof projection no longer delegates to production linear_{operation}_safe")
negation_wrapper = compact(function_section(positive_text, "proof_linear_neg_safe"))
if any(fragment not in negation_wrapper for fragment in (
        "defproof_linear_neg_safe(operand:i64)->(known:bool,value:i64):",
        "ensureresult.known==linear_neg_safe(operand).known",
        "ensureresult.value==linear_neg_safe(operand).value",
        "returnlinear_neg_safe(operand)",
)):
    raise SystemExit("proof projection no longer delegates to production linear_neg_safe")
arithmetic_wrapper = compact(function_section(positive_text, "proof_linear_arith_safe"))
if any(fragment not in arithmetic_wrapper for fragment in (
        "defproof_linear_arith_safe(left:i64,operator:TokenKind,right:i64)->(known:bool,value:i64):",
        "ensureresult.known==linear_arith_safe(left,operator,right).known",
        "ensureresult.value==linear_arith_safe(left,operator,right).value",
        "returnlinear_arith_safe(left,operator,right)",
)):
    raise SystemExit("proof projection no longer delegates to production linear_arith_safe")
for operation, expected in (
        ("add", "result.known implies result.value == left + right"),
        ("sub", "result.known implies result.value == left - right"),
        ("mul", "result.known implies result.value == left * right"),
        ("neg", "result.known implies result.value == 0 - operand"),
):
    if compact(expected) not in compact(function_section(source_text, f"linear_{operation}_safe")):
        raise SystemExit(f"linear_{operation}_safe no longer specifies its exact successful result")

positive_names = {
    "negate_nonminimum", "linear_negation_known_exactly_away_from_minimum",
    "known_addition_returns_exact_sum", "checked_addition_has_a_right_zero_identity",
    "checked_addition_is_commutative", "known_subtraction_returns_exact_difference",
    "checked_subtraction_has_a_right_zero_identity",
    "known_multiplication_returns_exact_product", "checked_multiplication_has_zero_as_an_annihilator",
    "checked_multiplication_has_left_one_as_an_identity",
    "checked_multiplication_has_right_one_as_an_identity",
    "checked_multiplication_by_negative_one_matches_negation",
    "checked_multiplication_is_commutative", "checked_subtraction_has_an_order_sensitive_result",
    "known_negation_returns_exact_difference", "checked_negation_maps_zero_to_zero",
    "failed_addition_returns_zero", "failed_subtraction_returns_zero",
    "failed_multiplication_returns_zero", "failed_negation_returns_zero",
    "semantic_addition_guard_is_exact", "semantic_subtraction_guard_is_exact",
    "semantic_multiplication_guard_is_exact",
    "semantic_add_dispatch_matches_checked_add", "semantic_sub_dispatch_matches_checked_sub",
    "semantic_mul_dispatch_matches_checked_mul", "semantic_dispatch_rejects_division",
    "semantic_dispatch_rejects_remainder", "unsupported_arithmetic_operators_fail_closed",
    "signed_arithmetic_overflow_extremes_fail_closed",
    "signed_arithmetic_safe_boundaries_are_admitted",
}
negative_names = {
    "false_minimum_negation_is_safe", "positive_add_overflow_is_known",
    "positive_multiply_overflow_is_known", "checked_multiplication_can_reject_the_reversed_safe_order",
    "checked_subtraction_is_commutative_for_every_pair",
    "checked_multiplication_by_negative_one_always_disagrees_with_negation",
    "negative_add_overflow_is_known",
    "subtraction_overflow_with_negative_subtrahend_is_known",
    "subtraction_underflow_with_positive_subtrahend_is_known",
    "positive_times_negative_multiply_overflow_is_known",
    "negative_times_positive_multiply_overflow_is_known",
    "negative_times_negative_multiply_overflow_is_known",
    "division_is_admitted_by_linear_constant_folding",
    "remainder_is_admitted_by_linear_constant_folding",
}
for path, names in ((POSITIVE, positive_names), (NEGATIVE, negative_names)):
    actual = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))
    if actual != names:
        raise SystemExit(f"{path.name} proof declaration inventory changed")

for operation in ("add", "mul"):
    symmetry_shape = (
        "ensure result == true "
        f"forward: (known: bool, value: i64) = Semantic::proof_linear_{operation}_safe(left, right) "
        f"reverse: (known: bool, value: i64) = Semantic::proof_linear_{operation}_safe(right, left) "
        "return forward.known == reverse.known and forward.value == reverse.value"
    )
    theorem = f"checked_{'addition' if operation == 'add' else 'multiplication'}_is_commutative"
    if compact(symmetry_shape) not in compact(function_section(POSITIVE.read_text(), theorem)):
        raise SystemExit(f"{operation} symmetry theorem no longer compares both production operand orders")

subtraction_witness_shape = (
    "ensure result == true "
    "forward: (known: bool, value: i64) = Semantic::proof_linear_sub_safe(9, 4) "
    "reverse: (known: bool, value: i64) = Semantic::proof_linear_sub_safe(4, 9) "
    "return forward.known and reverse.known and forward.value == 5 and reverse.value == (0 - 5)"
)
if compact(subtraction_witness_shape) not in compact(function_section(
        POSITIVE.read_text(), "checked_subtraction_has_an_order_sensitive_result")):
    raise SystemExit("subtraction asymmetry witness no longer checks concrete, successful opposite orders")

identity_shapes = {
    "checked_addition_has_a_right_zero_identity": (
        "Semantic::proof_linear_add_safe(left, 0)",
        "checked.known and checked.value == left",
    ),
    "checked_subtraction_has_a_right_zero_identity": (
        "Semantic::proof_linear_sub_safe(left, 0)",
        "checked.known and checked.value == left",
    ),
    "checked_multiplication_has_zero_as_an_annihilator": (
        "Semantic::proof_linear_mul_safe(0, operand)",
        "checked.known and checked.value == 0",
    ),
    "checked_multiplication_has_left_one_as_an_identity": (
        "Semantic::proof_linear_mul_safe(1, operand)",
        "checked.known and checked.value == operand",
    ),
    "checked_multiplication_has_right_one_as_an_identity": (
        "Semantic::proof_linear_mul_safe(operand, 1)",
        "checked.known and checked.value == operand",
    ),
    "checked_multiplication_by_negative_one_matches_negation": (
        "Semantic::proof_linear_mul_safe(0 - 1, operand)",
        "Semantic::proof_linear_neg_safe(operand)",
        "product.known == negation.known and product.value == negation.value",
    ),
    "checked_negation_maps_zero_to_zero": (
        "Semantic::proof_linear_neg_safe(0)",
        "checked.known and checked.value == 0",
    ),
}
for name, fragments in identity_shapes.items():
    section = compact(function_section(POSITIVE.read_text(), name))
    if not all(compact(fragment) in section for fragment in fragments):
        raise SystemExit(f"{name} no longer states its production arithmetic identity")

positive_shape = "requires operand != (0 - 9223372036854775807 - 1) ensure result == (0 - operand) checked: (known: bool, value: i64) = Semantic::proof_linear_neg_safe(operand) return checked.value"
if compact(positive_shape) not in compact(function_section(POSITIVE.read_text(), "negate_nonminimum")):
    raise SystemExit("negate_nonminimum no longer proves the production helper's exact-result contract")
known_shape = "ensure result == true checked: (known: bool, value: i64) = Semantic::proof_linear_neg_safe(operand) return checked.known == (operand != (0 - 9223372036854775807 - 1))"
if compact(known_shape) not in compact(function_section(POSITIVE.read_text(), "linear_negation_known_exactly_away_from_minimum")):
    raise SystemExit("positive proof no longer proves the production helper's exact acceptance domain")
for name, operation, exact_value in (
        ("known_addition_returns_exact_sum", "add", "left + right"),
        ("known_subtraction_returns_exact_difference", "sub", "left - right"),
        ("known_multiplication_returns_exact_product", "mul", "left * right"),
        ("known_negation_returns_exact_difference", "neg", "0 - operand"),
):
    operands = "operand" if operation == "neg" else "left, right"
    helper_call = f"Semantic::proof_linear_{operation}_safe({operands})"
    result_claim = f"checked.value == {exact_value}"
    shape = f"ensure result == true checked: (known: bool, value: i64) = {helper_call} return not checked.known or {result_claim}"
    if compact(shape) not in compact(function_section(positive_text, name)):
        raise SystemExit(f"{name} no longer proves the exact result whenever the production helper succeeds")
for name, operation in (
        ("failed_addition_returns_zero", "add"),
        ("failed_subtraction_returns_zero", "sub"),
        ("failed_multiplication_returns_zero", "mul"),
        ("failed_negation_returns_zero", "neg"),
):
    operands = "operand" if operation == "neg" else "left, right"
    helper_call = f"Semantic::proof_linear_{operation}_safe({operands})"
    shape = f"ensure result == true checked: (known: bool, value: i64) = {helper_call} return checked.known or checked.value == 0"
    if compact(shape) not in compact(function_section(positive_text, name)):
        raise SystemExit(f"{name} no longer proves fail-closed zero results for all failed inputs")
unsupported_shape = (
    "requires operator != TokenKind.Plus and operator != TokenKind.Minus and operator != TokenKind.Star "
    "ensure result == true checked: (known: bool, value: i64) = "
    "Semantic::proof_linear_arith_safe(left, operator, right) "
    "return not checked.known and checked.value == 0"
)
if compact(unsupported_shape) not in compact(function_section(positive_text, "unsupported_arithmetic_operators_fail_closed")):
    raise SystemExit("unsupported-operator theorem no longer proves universal rejection with a zero result")
for name, shape in (
        ("semantic_addition_guard_is_exact", "ensure result == true checked: (known: bool, value: i64) = Semantic::proof_linear_add_safe(left, right) return checked.known == (right == 0 or (right > 0 and left <= 9223372036854775807 - right) or (right < 0 and left >= (0 - 9223372036854775807 - 1) - right)"),
        ("semantic_subtraction_guard_is_exact", "ensure result == true checked: (known: bool, value: i64) = Semantic::proof_linear_sub_safe(left, right) return checked.known == (right == 0 or (right > 0 and left >= (0 - 9223372036854775807 - 1) + right) or (right < 0 and left <= 9223372036854775807 + right)"),
        ("semantic_multiplication_guard_is_exact", "ensure result == true checked: (known: bool, value: i64) = Semantic::proof_linear_mul_safe(left, right) return checked.known == (left == 0 or right == 0 or left == 1 or right == 1 or (left == -1 and right != (0 - 9223372036854775807 - 1)) or (right == -1 and left != (0 - 9223372036854775807 - 1)) or (left > 0 and right > 0 and left <= 9223372036854775807 / right) or (left > 0 and right < 0 and right >= (0 - 9223372036854775807 - 1) / left) or (left < 0 and right > 0 and left >= (0 - 9223372036854775807 - 1) / right) or (left < 0 and right < 0 and left >= 9223372036854775807 / right)"),
):
    if compact(shape) not in compact(function_section(positive_text, name)):
        raise SystemExit(f"{name} no longer proves the exact production acceptance predicate")
for name, operator, helper in (
        ("semantic_add_dispatch_matches_checked_add", "Plus", "add"),
        ("semantic_sub_dispatch_matches_checked_sub", "Minus", "sub"),
        ("semantic_mul_dispatch_matches_checked_mul", "Star", "mul"),
):
    shape = f"ensure result == true dispatched: (known: bool, value: i64) = Semantic::proof_linear_arith_safe(left, TokenKind.{operator}, right) checked: (known: bool, value: i64) = Semantic::proof_linear_{helper}_safe(left, right) return dispatched.known == checked.known and dispatched.value == checked.value"
    if compact(shape) not in compact(function_section(positive_text, name)):
        raise SystemExit(f"{name} no longer proves the production operator dispatch")
for name, operator in (("semantic_dispatch_rejects_division", "Slash"),
                       ("semantic_dispatch_rejects_remainder", "Percent")):
    shape = f"ensure result == true dispatched: (known: bool, value: i64) = Semantic::proof_linear_arith_safe(left, TokenKind.{operator}, right) return not dispatched.known and dispatched.value == 0"
    if compact(shape) not in compact(function_section(positive_text, name)):
        raise SystemExit(f"{name} no longer proves unsupported arithmetic is rejected")
extremes = compact(function_section(positive_text, "signed_arithmetic_overflow_extremes_fail_closed"))
for fragment in (
        "Semantic::proof_linear_add_safe(9223372036854775807,1)",
        "Semantic::proof_linear_add_safe(minimum,0-1)",
        "Semantic::proof_linear_sub_safe(9223372036854775807,0-1)",
        "Semantic::proof_linear_sub_safe(minimum,1)",
        "Semantic::proof_linear_mul_safe(9223372036854775807,2)",
        "Semantic::proof_linear_mul_safe(2,minimum)",
        "Semantic::proof_linear_mul_safe(minimum,2)",
        "Semantic::proof_linear_mul_safe(minimum,0-2)",
        "Semantic::proof_linear_mul_safe(minimum,0-1)",
        "Semantic::proof_linear_mul_safe(0-1,minimum)",
        "Semantic::proof_linear_neg_safe(minimum)",
        "Semantic::proof_linear_arith_safe(1,TokenKind.Slash,1)",
        "Semantic::proof_linear_arith_safe(1,TokenKind.Percent,1)",
        "notadd_upper.knownandadd_upper.value==0",
        "notadd_lower.knownandadd_lower.value==0",
        "notsub_upper.knownandsub_upper.value==0",
        "notsub_lower.knownandsub_lower.value==0",
        "notmul_positive.knownandmul_positive.value==0",
        "notmul_positive_negative.knownandmul_positive_negative.value==0",
        "notmul_negative_positive.knownandmul_negative_positive.value==0",
        "notmul_negative.knownandmul_negative.value==0",
        "notmul_minimum_by_negative_one.knownandmul_minimum_by_negative_one.value==0",
        "notmul_negative_one_by_minimum.knownandmul_negative_one_by_minimum.value==0",
        "notneg_minimum.knownandneg_minimum.value==0",
        "notdivide.knownanddivide.value==0",
        "notremainder.knownandremainder.value==0",
):
    if fragment not in extremes:
        raise SystemExit(f"signed arithmetic boundary proof omits fail-closed case {fragment}")
safe_boundaries = compact(function_section(positive_text, "signed_arithmetic_safe_boundaries_are_admitted"))
for fragment in (
        "Semantic::proof_linear_add_safe(9223372036854775807-1,1)",
        "Semantic::proof_linear_add_safe(minimum+1,0-1)",
        "Semantic::proof_linear_sub_safe(minimum+1,1)",
        "Semantic::proof_linear_sub_safe(9223372036854775807-1,0-1)",
        "Semantic::proof_linear_mul_safe(4611686018427387903,2)",
        "Semantic::proof_linear_mul_safe(2,0-4611686018427387904)",
        "Semantic::proof_linear_mul_safe(0-4611686018427387904,2)",
        "Semantic::proof_linear_mul_safe(0-4611686018427387903,0-2)",
        "Semantic::proof_linear_mul_safe(minimum,1)",
        "Semantic::proof_linear_mul_safe(1,minimum)",
        "Semantic::proof_linear_mul_safe(minimum+1,0-1)",
        "Semantic::proof_linear_mul_safe(0-1,minimum+1)",
        "Semantic::proof_linear_neg_safe(minimum+1)",
        "add_upper.knownandadd_upper.value==9223372036854775807",
        "add_lower.knownandadd_lower.value==minimum",
        "sub_lower.knownandsub_lower.value==minimum",
        "sub_upper.knownandsub_upper.value==9223372036854775807",
        "mul_positive.knownandmul_positive.value==9223372036854775806",
        "mul_positive_negative.knownandmul_positive_negative.value==minimum",
        "mul_negative_positive.knownandmul_negative_positive.value==minimum",
        "mul_negative.knownandmul_negative.value==9223372036854775806",
        "mul_minimum_by_one.knownandmul_minimum_by_one.value==minimum",
        "mul_one_by_minimum.knownandmul_one_by_minimum.value==minimum",
        "mul_near_minimum_by_negative_one.knownandmul_near_minimum_by_negative_one.value==9223372036854775807",
        "mul_negative_one_by_near_minimum.knownandmul_negative_one_by_near_minimum.value==9223372036854775807",
        "neg_near_minimum.knownandneg_near_minimum.value==9223372036854775807",
):
    if fragment not in safe_boundaries:
        raise SystemExit(f"signed arithmetic proof omits admitted boundary case {fragment}")
negative_shape = "requires operand == (0 - 9223372036854775807 - 1) ensure result == true checked: (known: bool, value: i64) = Semantic::proof_linear_neg_safe(operand) return checked.known"
if compact(negative_shape) not in compact(function_section(NEGATIVE.read_text(), "false_minimum_negation_is_safe")):
    raise SystemExit("false_minimum_negation_is_safe no longer challenges the excluded i64 minimum")
for name, shape in (
        ("positive_add_overflow_is_known", "requires right > 0 and left > 9223372036854775807 - right ensure result == true checked: (known: bool, value: i64) = Semantic::proof_linear_add_safe(left, right) return checked.known"),
        ("positive_multiply_overflow_is_known", "requires left > 0 and right > 0 and left > 9223372036854775807 / right ensure result == true checked: (known: bool, value: i64) = Semantic::proof_linear_mul_safe(left, right) return checked.known"),
        ("checked_multiplication_can_reject_the_reversed_safe_order", "ensure result == true forward: (known: bool, value: i64) = Semantic::proof_linear_mul_safe(left, right) reverse: (known: bool, value: i64) = Semantic::proof_linear_mul_safe(right, left) return forward.known and not reverse.known"),
        ("checked_subtraction_is_commutative_for_every_pair", "ensure result == true forward: (known: bool, value: i64) = Semantic::proof_linear_sub_safe(left, right) reverse: (known: bool, value: i64) = Semantic::proof_linear_sub_safe(right, left) return forward.known == reverse.known and forward.value == reverse.value"),
        ("checked_multiplication_by_negative_one_always_disagrees_with_negation", "ensure result == true product: (known: bool, value: i64) = Semantic::proof_linear_mul_safe(0 - 1, operand) negation: (known: bool, value: i64) = Semantic::proof_linear_neg_safe(operand) return product.known != negation.known or product.value != negation.value"),
        ("negative_add_overflow_is_known", "requires right < 0 and left < (0 - 9223372036854775807 - 1) - right ensure result == true checked: (known: bool, value: i64) = Semantic::proof_linear_add_safe(left, right) return checked.known"),
        ("subtraction_overflow_with_negative_subtrahend_is_known", "requires right < 0 and left > 9223372036854775807 + right ensure result == true checked: (known: bool, value: i64) = Semantic::proof_linear_sub_safe(left, right) return checked.known"),
        ("subtraction_underflow_with_positive_subtrahend_is_known", "requires right > 0 and left < (0 - 9223372036854775807 - 1) + right ensure result == true checked: (known: bool, value: i64) = Semantic::proof_linear_sub_safe(left, right) return checked.known"),
        ("positive_times_negative_multiply_overflow_is_known", "requires left > 0 and right < 0 and right < (0 - 9223372036854775807 - 1) / left ensure result == true checked: (known: bool, value: i64) = Semantic::proof_linear_mul_safe(left, right) return checked.known"),
        ("negative_times_positive_multiply_overflow_is_known", "requires left < 0 and right > 0 and left < (0 - 9223372036854775807 - 1) / right ensure result == true checked: (known: bool, value: i64) = Semantic::proof_linear_mul_safe(left, right) return checked.known"),
        ("negative_times_negative_multiply_overflow_is_known", "requires left < 0 and right < 0 and left < 9223372036854775807 / right ensure result == true checked: (known: bool, value: i64) = Semantic::proof_linear_mul_safe(left, right) return checked.known"),
        ("division_is_admitted_by_linear_constant_folding", "ensure result == true checked: (known: bool, value: i64) = Semantic::proof_linear_arith_safe(left, TokenKind.Slash, right) return checked.known"),
        ("remainder_is_admitted_by_linear_constant_folding", "ensure result == true checked: (known: bool, value: i64) = Semantic::proof_linear_arith_safe(left, TokenKind.Percent, right) return checked.known"),
):
    if compact(shape) not in compact(function_section(NEGATIVE.read_text(), name)):
        raise SystemExit(f"{name} no longer challenges the production overflow check")

if ARGS.source_only:
    source_closure = source_include_closure([POSITIVE, NEGATIVE])
    print(json.dumps({
        "source_bound": True,
        "positive_declarations": len(positive_names),
        "false_control_declarations": len(negative_names),
        "source_closure_files": len(source_closure),
    }, sort_keys=True))
    raise SystemExit(0)

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("checked arithmetic proofs require a strict proof build")
compiler = product["compiler"]
stage1_product = Path(compiler["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", SOURCE, ARITHMETIC, SEMANTIC,
    PARSER, PARSER_TOKENS, LEXER, TOKEN_KIND, TOKEN_KIND_PROJECTION, POSITIVE, NEGATIVE,
    *sorted(SEMANTIC_SOURCES.glob("*.elisa")),
    *source_include_closure([POSITIVE, NEGATIVE]),
]))
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
assert positive == run(POSITIVE)[1], "checked arithmetic proof report changed across identical runs"
verified_positive = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert positive_names | {
    "linear_i64_max", "linear_i64_min", "linear_add_safe", "linear_sub_safe",
    "linear_mul_safe", "linear_neg_safe", "linear_arith_safe", "proof_linear_add_safe",
    "proof_linear_sub_safe", "proof_linear_mul_safe", "proof_linear_neg_safe",
    "proof_linear_arith_safe",
} <= verified_positive

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["proven"] + 11 == negative["summary"]["obligations"]
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" and row["status"] in {"unknown", "disproved"}
           for row in negative["findings"])
verified_negative = {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert negative_names.isdisjoint(verified_negative)
assert {
    "linear_i64_max", "linear_i64_min", "linear_add_safe", "linear_sub_safe",
    "linear_mul_safe", "linear_neg_safe", "linear_arith_safe", "proof_linear_add_safe",
    "proof_linear_sub_safe", "proof_linear_mul_safe", "proof_linear_neg_safe",
    "proof_linear_arith_safe",
} <= verified_negative
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product
print(json.dumps({
    "admitted": True,
    "scope": "source-linked checked add/subtract/multiply/negate and exact constant-fold operator dispatch contracts",
    "positive_obligations": positive["summary"]["proven"],
    "false_overflow_claims_refused": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": compiler.get("source_revision"),
    "source_sha256": hashes_before,
}, sort_keys=True))
