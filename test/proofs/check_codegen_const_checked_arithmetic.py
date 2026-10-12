"""Admit signed-i64 arithmetic and shift guards in backend constant folding."""
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
ARITHMETIC = ROOT / "src/backend/codegen_const_checked_arithmetic.elisa"
FOLDING = ROOT / "src/backend/codegen_const_folding.elisa"
SEMANTIC_ARITHMETIC = ROOT / "src/semantic/check_ensure_strict.elisa"
SEMANTIC_INDEX_FOLD = ROOT / "src/semantic/check_index_out_of_bounds.elisa"
POSITIVE = HERE / "codegen_const_checked_arithmetic.elisa"
NEGATIVE = HERE / "codegen_const_checked_arithmetic_rejected.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    return "".join(text.split())


def function_body(source: str, name: str) -> str:
    matches = list(re.finditer(rf"(?m)^([ \t]*)def {re.escape(name)}\(", source))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    match = matches[0]
    indent = match.group(1)
    following = re.search(rf"(?m)^{re.escape(indent)}def [A-Za-z_][A-Za-z0-9_]*\(", source[match.end():])
    end = match.end() + following.start() if following else len(source)
    return source[match.start():end]


def return_expression(source: str, name: str) -> str:
    body = compact(function_body(source, name))
    if "return" not in body:
        raise SystemExit(f"{name} has no return expression")
    return body.rsplit("return", 1)[1]


def ensure_expression(source: str, name: str) -> str:
    body = compact(function_body(source, name))
    marker = "ensureresult=="
    start = body.find(marker)
    if start < 0:
        raise SystemExit(f"{name} has no result postcondition")
    expression_start = start + len(marker)
    boundaries = [position for position in (
        body.find("ensure", expression_start),
        body.find("return", expression_start),
    ) if position >= 0]
    if not boundaries:
        raise SystemExit(f"{name} postcondition has no return body")
    expression = body[expression_start:min(boundaries)]
    while expression.startswith("(") and expression.endswith(")"):
        depth = 0
        wraps_all = True
        for index, character in enumerate(expression):
            depth += character == "("
            depth -= character == ")"
            if depth == 0 and index != len(expression) - 1:
                wraps_all = False
                break
        if not wraps_all:
            break
        expression = expression[1:-1]
    return expression


def strip_outer_parens(expression: str) -> str:
    while expression.startswith("(") and expression.endswith(")"):
        depth = 0
        wraps_all = True
        for index, character in enumerate(expression):
            depth += character == "("
            depth -= character == ")"
            if depth == 0 and index != len(expression) - 1:
                wraps_all = False
                break
        if not wraps_all:
            break
        expression = expression[1:-1]
    return expression


def declaration_names(path: Path) -> set[str]:
    return set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))


arithmetic_text = ARITHMETIC.read_text()
folding_text = FOLDING.read_text()
proof_text = POSITIVE.read_text()
if 'include "./codegen_const_checked_arithmetic.elisa"' not in folding_text:
    raise SystemExit("backend constant folding no longer imports its checked arithmetic helpers")
arithmetic_compact = compact(arithmetic_text)
for declaration in (
    "module BackendConstArithmetic:",
    "const I64_MAX: i64 = 9223372036854775807",
    "const I64_MIN: i64 = 0 - I64_MAX - 1",
    "const I64_SHIFT_WIDTH: i64 = 64",
):
    if compact(declaration) not in arithmetic_compact:
        raise SystemExit("checked arithmetic module no longer uses the exact signed-i64 bounds")

# The proof file includes the production module and calls these exact functions.
# Require each production contract to describe its executable return expression.
guard_specifications = {
    "add_is_safe": "right == 0 or (right > 0 and left <= I64_MAX - right) or (right < 0 and left >= I64_MIN - right)",
    "subtract_is_safe": "right == 0 or (right > 0 and left >= I64_MIN + right) or (right < 0 and left <= I64_MAX + right)",
    "multiply_is_safe": "left == 0 or right == 0 or (left > 0 and right > 0 and left <= I64_MAX / right) or (left > 0 and right < 0 and right >= I64_MIN / left) or (left < 0 and right > 0 and left >= I64_MIN / right) or (left < 0 and right < 0 and left >= I64_MAX / right)",
    "division_is_safe": "right != 0 and (left != I64_MIN or right != -1)",
    "remainder_is_safe": "right != 0 and (left != I64_MIN or right != -1)",
    "negation_is_safe": "value != I64_MIN",
    "shift_count_is_safe": "count >= 0 and count < I64_SHIFT_WIDTH",
}
if 'include "../../src/backend/codegen_const_checked_arithmetic.elisa"' not in proof_text:
    raise SystemExit("positive arithmetic proofs must include the production guard module")
for name, specification in guard_specifications.items():
    production_return = strip_outer_parens(return_expression(arithmetic_text, name))
    if production_return != compact(specification):
        raise SystemExit(f"{name} no longer implements the checked signed-i64 boundary predicate")
    if ensure_expression(arithmetic_text, name) != production_return:
        raise SystemExit(f"{name} postcondition no longer matches its production return expression")

# The helpers' call contracts expose the range facts consumed by the folder. The
# proofs below call these exact guards as preconditions, so these properties are
# checked by the proof assistant instead of being inferred from detached copies.
range_contracts = {
    "add_is_safe": (
        "ensure result implies (left + right >= I64_MIN and left + right <= I64_MAX)",
    ),
    "subtract_is_safe": (
        "ensure result implies (left - right >= I64_MIN and left - right <= I64_MAX)",
    ),
    "multiply_is_safe": (
        "ensure (result and (left == 0 or right == 0)) implies left * right == 0",
        "ensure (result and left > 0 and right > 0) implies (left * right >= 0 and left * right <= I64_MAX)",
        "ensure (result and left > 0 and right < 0) implies (left * right >= I64_MIN and left * right <= 0)",
        "ensure (result and left < 0 and right > 0) implies (left * right >= I64_MIN and left * right <= 0)",
        "ensure (result and left < 0 and right < 0) implies (left * right >= 0 and left * right <= I64_MAX)",
    ),
    "negation_is_safe": (
        "ensure result implies (0 - value >= I64_MIN and 0 - value <= I64_MAX)",
    ),
}
for name, contracts in range_contracts.items():
    body = compact(function_body(arithmetic_text, name))
    if any(compact(contract) not in body for contract in contracts):
        raise SystemExit(f"{name} no longer exposes its checked-result range contract")

# The backend and semantic folders must reject the same signed overflow cases. These semantic
# helpers already have their own proof-admission gates; pin their checked branches here as the
# cross-layer source relation for this backend proof.
semantic_text = SEMANTIC_ARITHMETIC.read_text()
semantic_max = compact(function_body(semantic_text, "linear_i64_max"))
semantic_min = compact(function_body(semantic_text, "linear_i64_min"))
if "return9223372036854775807" not in semantic_max or \
        "return0-9223372036854775807-1" not in semantic_min:
    raise SystemExit("semantic and backend signed-i64 bounds have diverged")

semantic_add = compact(function_body(semantic_text, "linear_add_safe"))
add_guards = (
    "return(false,0)ifright>0andleft>linear_i64_max()-right",
    "return(false,0)ifright<0andleft<linear_i64_min()-right",
    "return(true,left+right)",
)
add_positions = [semantic_add.find(fragment) for fragment in add_guards]
if any(position < 0 for position in add_positions) or add_positions != sorted(add_positions):
    raise SystemExit("backend addition guard no longer matches the proved semantic overflow conditions")

semantic_subtract = compact(function_body(semantic_text, "linear_sub_safe"))
subtract_guards = (
    "return(false,0)ifright>0andleft<linear_i64_min()+right",
    "return(false,0)ifright<0andleft>linear_i64_max()+right",
    "return(true,left-right)",
)
subtract_positions = [semantic_subtract.find(fragment) for fragment in subtract_guards]
if any(position < 0 for position in subtract_positions) or subtract_positions != sorted(subtract_positions):
    raise SystemExit("backend subtraction guard no longer matches the proved semantic overflow conditions")

semantic_multiply = compact(function_body(semantic_text, "linear_mul_safe"))
multiply_guards = (
    "return(true,0)ifleft==0orright==0",
    "return(true,right)ifleft==1",
    "return(true,left)ifright==1",
    "ifleft==-1:",
    "return(false,0)ifright==linear_i64_min()",
    "return(true,0-right)",
    "ifright==-1:",
    "return(false,0)ifleft==linear_i64_min()",
    "return(true,0-left)",
    "ifleft>0:",
    "return(false,0)ifright>0andleft>linear_i64_max()/right",
    "return(false,0)ifright<0andright<linear_i64_min()/left",
    "else:",
    "return(false,0)ifright>0andleft<linear_i64_min()/right",
    "return(false,0)ifright<0andleft<linear_i64_max()/right",
    "return(true,left*right)",
)
multiply_positions = [semantic_multiply.find(fragment) for fragment in multiply_guards]
if any(position < 0 for position in multiply_positions) or multiply_positions != sorted(multiply_positions):
    raise SystemExit("backend multiplication guard no longer matches the proved semantic overflow conditions")

semantic_negate = compact(function_body(semantic_text, "linear_neg_safe"))
if not semantic_negate.startswith("deflinear_neg_safe(operand:i64)->(known:bool,value:i64):returnlinear_sub_safe(0,operand)"):
    raise SystemExit("backend negation guard no longer matches the proved semantic subtraction guard")

semantic_division = compact(function_body(SEMANTIC_INDEX_FOLD.read_text(), "resolve_fold_binary"))
division_guards = (
    "ifoperator==TokenKind.Slashoroperator==TokenKind.Percent:",
    "return(false,0)ifright==0",
    "return(false,0)ifleft==linear_i64_min()andright==-1",
    "return(true,left/right)ifoperator==TokenKind.Slash",
    "return(true,left%right)",
)
division_positions = [semantic_division.find(fragment) for fragment in division_guards]
if any(position < 0 for position in division_positions) or division_positions != sorted(division_positions):
    raise SystemExit("backend division and remainder guards no longer match semantic constant folding")

fold_binary = compact(function_body(folding_text, "fold_const_binary_values"))
fold_patterns = (
    "ifoperator==TokenKind.Plus:ifBackendConstArithmetic::add_is_safe(left_value,right_value):returnleft_value+right_valueelse:ok<-falsereturn0",
    "ifoperator==TokenKind.Minus:ifBackendConstArithmetic::subtract_is_safe(left_value,right_value):returnleft_value-right_valueelse:ok<-falsereturn0",
    "ifoperator==TokenKind.Star:ifBackendConstArithmetic::multiply_is_safe(left_value,right_value):returnleft_value*right_valueelse:ok<-falsereturn0",
    "ifoperator==TokenKind.Slash:ifBackendConstArithmetic::division_is_safe(left_value,right_value):returnleft_value/right_valueelse:ok<-falsereturn0",
    "ifoperator==TokenKind.Percent:ifBackendConstArithmetic::remainder_is_safe(left_value,right_value):returnleft_value%right_valueelse:ok<-falsereturn0",
    "ifoperator==TokenKind.LShift:ifBackendConstArithmetic::shift_count_is_safe(right_value):returnleft_value<<right_valueelse:ok<-falsereturn0",
    "ifoperator==TokenKind.RShift:ifBackendConstArithmetic::shift_count_is_safe(right_value):returnleft_value>>right_valueelse:ok<-falsereturn0",
)
if any(pattern not in fold_binary for pattern in fold_patterns):
    raise SystemExit("constant arithmetic must be guarded before evaluating the signed operation")
unary = compact(function_body(folding_text, "fold_const_expr"))
if "ifunary_operator==TokenKind.Minus:ifBackendConstArithmetic::negation_is_safe(operand_value):return0-operand_valueelse:ok<-falsereturn0" not in unary:
    raise SystemExit("unary-minus folding no longer rejects i64 minimum before negating it")

positive_names = {
    "positive_add_boundary_is_accepted", "negative_add_boundary_is_accepted", "zero_add_is_accepted",
    "accepted_addition_stays_within_i64",
    "guarded_addition_result_is_i64", "guarded_subtraction_result_is_i64",
    "positive_add_overflow_is_rejected", "negative_add_underflow_is_rejected",
    "positive_subtract_boundary_is_accepted", "negative_subtract_boundary_is_accepted", "zero_subtract_is_accepted",
    "accepted_subtraction_stays_within_i64",
    "positive_subtract_overflow_is_rejected", "negative_subtract_underflow_is_rejected",
    "positive_positive_product_boundary_is_accepted", "positive_negative_product_boundary_is_accepted",
    "negative_positive_product_boundary_is_accepted", "negative_negative_product_boundary_is_accepted",
    "accepted_positive_positive_product_stays_within_i64",
    "accepted_positive_negative_product_stays_within_i64",
    "accepted_negative_positive_product_stays_within_i64",
    "accepted_negative_negative_product_stays_within_i64",
    "guarded_zero_product_is_exact", "guarded_positive_positive_product_is_i64",
    "guarded_positive_negative_product_is_i64", "guarded_negative_positive_product_is_i64",
    "guarded_negative_negative_product_is_i64",
    "positive_positive_product_overflow_is_rejected", "positive_negative_product_overflow_is_rejected",
    "negative_positive_product_overflow_is_rejected", "negative_negative_product_overflow_is_rejected",
    "zero_product_is_accepted", "minimum_by_negative_one_is_rejected",
    "defined_division_operands_are_accepted", "defined_remainder_operands_are_accepted",
    "accepted_quotient_stays_within_i64", "guarded_quotient_stays_within_i64",
    "accepted_remainder_stays_within_i64", "guarded_remainder_stays_within_i64",
    "zero_divisor_is_rejected", "minimum_division_pair_is_rejected",
    "nonminimum_negation_is_accepted", "accepted_negation_stays_within_i64",
    "guarded_negation_result_is_i64", "minimum_negation_is_rejected",
    "zero_shift_count_is_accepted", "last_i64_shift_count_is_accepted",
    "in_range_shift_count_is_accepted", "guarded_shift_count_is_within_width", "negative_shift_count_is_rejected",
    "oversized_shift_count_is_rejected",
}
negative_order = (
    "positive_add_overflow_is_accepted", "negative_add_underflow_is_accepted",
    "positive_subtract_overflow_is_accepted", "negative_subtract_underflow_is_accepted",
    "multiplication_overflow_is_accepted", "positive_negative_product_overflow_is_accepted",
    "negative_positive_product_overflow_is_accepted", "negative_negative_product_overflow_is_accepted",
    "minimum_times_negative_one_is_accepted", "negative_one_times_minimum_is_accepted",
    "zero_division_is_accepted", "minimum_divided_by_negative_one_is_accepted",
    "minimum_remainder_negative_one_is_accepted", "minimum_negation_is_accepted",
    "negative_shift_count_is_accepted", "shift_count_equal_to_width_is_accepted",
)
negative_names = set(negative_order)
if declaration_names(POSITIVE) != positive_names or declaration_names(NEGATIVE) != negative_names:
    raise SystemExit("checked constant-fold arithmetic proof inventory changed")

positive_shapes = {
    "positive_add_boundary_is_accepted": "requires right > 0 and left <= BackendConstArithmetic::I64_MAX - right ensure result == true return BackendConstArithmetic::add_is_safe(left, right)",
    "negative_add_boundary_is_accepted": "requires right < 0 and left >= BackendConstArithmetic::I64_MIN - right ensure result == true return BackendConstArithmetic::add_is_safe(left, right)",
    "zero_add_is_accepted": "ensure result == true return BackendConstArithmetic::add_is_safe(left, 0)",
    "positive_subtract_boundary_is_accepted": "requires right > 0 and left >= BackendConstArithmetic::I64_MIN + right ensure result == true return BackendConstArithmetic::subtract_is_safe(left, right)",
    "negative_subtract_boundary_is_accepted": "requires right < 0 and left <= BackendConstArithmetic::I64_MAX + right ensure result == true return BackendConstArithmetic::subtract_is_safe(left, right)",
    "zero_subtract_is_accepted": "ensure result == true return BackendConstArithmetic::subtract_is_safe(left, 0)",
    "accepted_addition_stays_within_i64": "requires right == 0 or (right > 0 and left <= BackendConstArithmetic::I64_MAX - right) or (right < 0 and left >= BackendConstArithmetic::I64_MIN - right) ensure result == true return left + right >= BackendConstArithmetic::I64_MIN and left + right <= BackendConstArithmetic::I64_MAX",
    "guarded_addition_result_is_i64": "requires BackendConstArithmetic::add_is_safe(left, right) ensure result == true return left + right >= BackendConstArithmetic::I64_MIN and left + right <= BackendConstArithmetic::I64_MAX",
    "guarded_subtraction_result_is_i64": "requires BackendConstArithmetic::subtract_is_safe(left, right) ensure result == true return left - right >= BackendConstArithmetic::I64_MIN and left - right <= BackendConstArithmetic::I64_MAX",
    "positive_add_overflow_is_rejected": "requires right > 0 and left > BackendConstArithmetic::I64_MAX - right ensure result == true return not BackendConstArithmetic::add_is_safe(left, right)",
    "negative_add_underflow_is_rejected": "requires right < 0 and left < BackendConstArithmetic::I64_MIN - right ensure result == true return not BackendConstArithmetic::add_is_safe(left, right)",
    "accepted_subtraction_stays_within_i64": "requires right == 0 or (right > 0 and left >= BackendConstArithmetic::I64_MIN + right) or (right < 0 and left <= BackendConstArithmetic::I64_MAX + right) ensure result == true return left - right >= BackendConstArithmetic::I64_MIN and left - right <= BackendConstArithmetic::I64_MAX",
    "positive_subtract_overflow_is_rejected": "requires right < 0 and left > BackendConstArithmetic::I64_MAX + right ensure result == true return not BackendConstArithmetic::subtract_is_safe(left, right)",
    "negative_subtract_underflow_is_rejected": "requires right > 0 and left < BackendConstArithmetic::I64_MIN + right ensure result == true return not BackendConstArithmetic::subtract_is_safe(left, right)",
    "positive_positive_product_boundary_is_accepted": "requires left > 0 and right > 0 and left <= BackendConstArithmetic::I64_MAX / right ensure result == true return BackendConstArithmetic::multiply_is_safe(left, right)",
    "positive_negative_product_boundary_is_accepted": "requires left > 0 and right < 0 and right >= BackendConstArithmetic::I64_MIN / left ensure result == true return BackendConstArithmetic::multiply_is_safe(left, right)",
    "negative_positive_product_boundary_is_accepted": "requires left < 0 and right > 0 and left >= BackendConstArithmetic::I64_MIN / right ensure result == true return BackendConstArithmetic::multiply_is_safe(left, right)",
    "negative_negative_product_boundary_is_accepted": "requires left < 0 and right < 0 and left >= BackendConstArithmetic::I64_MAX / right ensure result == true return BackendConstArithmetic::multiply_is_safe(left, right)",
    "accepted_positive_positive_product_stays_within_i64": "requires left > 0 and right > 0 and left <= BackendConstArithmetic::I64_MAX / right ensure result == true return left * right >= 0 and left * right <= BackendConstArithmetic::I64_MAX",
    "accepted_positive_negative_product_stays_within_i64": "requires left > 0 and right < 0 and right >= BackendConstArithmetic::I64_MIN / left ensure result == true return left * right >= BackendConstArithmetic::I64_MIN and left * right <= 0",
    "accepted_negative_positive_product_stays_within_i64": "requires left < 0 and right > 0 and left >= BackendConstArithmetic::I64_MIN / right ensure result == true return left * right >= BackendConstArithmetic::I64_MIN and left * right <= 0",
    "accepted_negative_negative_product_stays_within_i64": "requires left < 0 and right < 0 and left >= BackendConstArithmetic::I64_MAX / right ensure result == true return left * right >= 0 and left * right <= BackendConstArithmetic::I64_MAX",
    "guarded_zero_product_is_exact": "requires BackendConstArithmetic::multiply_is_safe(left, right) and (left == 0 or right == 0) ensure result == true return left * right == 0",
    "guarded_positive_positive_product_is_i64": "requires BackendConstArithmetic::multiply_is_safe(left, right) and left > 0 and right > 0 ensure result == true return left * right >= 0 and left * right <= BackendConstArithmetic::I64_MAX",
    "guarded_positive_negative_product_is_i64": "requires BackendConstArithmetic::multiply_is_safe(left, right) and left > 0 and right < 0 ensure result == true return left * right >= BackendConstArithmetic::I64_MIN and left * right <= 0",
    "guarded_negative_positive_product_is_i64": "requires BackendConstArithmetic::multiply_is_safe(left, right) and left < 0 and right > 0 ensure result == true return left * right >= BackendConstArithmetic::I64_MIN and left * right <= 0",
    "guarded_negative_negative_product_is_i64": "requires BackendConstArithmetic::multiply_is_safe(left, right) and left < 0 and right < 0 ensure result == true return left * right >= 0 and left * right <= BackendConstArithmetic::I64_MAX",
    "positive_positive_product_overflow_is_rejected": "requires left > 0 and right > 0 and left > BackendConstArithmetic::I64_MAX / right ensure result == true return not BackendConstArithmetic::multiply_is_safe(left, right)",
    "positive_negative_product_overflow_is_rejected": "requires left > 0 and right < 0 and right < BackendConstArithmetic::I64_MIN / left ensure result == true return not BackendConstArithmetic::multiply_is_safe(left, right)",
    "negative_positive_product_overflow_is_rejected": "requires left < 0 and right > 0 and left < BackendConstArithmetic::I64_MIN / right ensure result == true return not BackendConstArithmetic::multiply_is_safe(left, right)",
    "negative_negative_product_overflow_is_rejected": "requires left < 0 and right < 0 and left < BackendConstArithmetic::I64_MAX / right ensure result == true return not BackendConstArithmetic::multiply_is_safe(left, right)",
    "zero_product_is_accepted": "requires left == 0 or right == 0 ensure result == true return BackendConstArithmetic::multiply_is_safe(left, right)",
    "minimum_by_negative_one_is_rejected": "ensure result == true return not BackendConstArithmetic::multiply_is_safe(BackendConstArithmetic::I64_MIN, -1) and not BackendConstArithmetic::multiply_is_safe(-1, BackendConstArithmetic::I64_MIN)",
    "defined_division_operands_are_accepted": "requires right != 0 and (left != BackendConstArithmetic::I64_MIN or right != -1) ensure result == true return BackendConstArithmetic::division_is_safe(left, right)",
    "accepted_quotient_stays_within_i64": "requires right != 0 and (left != BackendConstArithmetic::I64_MIN or right != -1) ensure result == true return left / right >= BackendConstArithmetic::I64_MIN and left / right <= BackendConstArithmetic::I64_MAX",
    "guarded_quotient_stays_within_i64": "requires BackendConstArithmetic::division_is_safe(left, right) ensure result == true return left / right >= BackendConstArithmetic::I64_MIN and left / right <= BackendConstArithmetic::I64_MAX",
    "defined_remainder_operands_are_accepted": "requires right != 0 and (left != BackendConstArithmetic::I64_MIN or right != -1) ensure result == true return BackendConstArithmetic::remainder_is_safe(left, right)",
    "accepted_remainder_stays_within_i64": "requires right != 0 and (left != BackendConstArithmetic::I64_MIN or right != -1) ensure result == true return left % right >= BackendConstArithmetic::I64_MIN and left % right <= BackendConstArithmetic::I64_MAX",
    "guarded_remainder_stays_within_i64": "requires BackendConstArithmetic::remainder_is_safe(left, right) ensure result == true return left % right >= BackendConstArithmetic::I64_MIN and left % right <= BackendConstArithmetic::I64_MAX",
    "zero_divisor_is_rejected": "ensure result == true return not BackendConstArithmetic::division_is_safe(left, 0) and not BackendConstArithmetic::remainder_is_safe(left, 0)",
    "minimum_division_pair_is_rejected": "ensure result == true return not BackendConstArithmetic::division_is_safe(BackendConstArithmetic::I64_MIN, -1) and not BackendConstArithmetic::remainder_is_safe(BackendConstArithmetic::I64_MIN, -1)",
    "nonminimum_negation_is_accepted": "requires value != BackendConstArithmetic::I64_MIN ensure result == true return BackendConstArithmetic::negation_is_safe(value)",
    "accepted_negation_stays_within_i64": "requires value != BackendConstArithmetic::I64_MIN ensure result == true return 0 - value >= BackendConstArithmetic::I64_MIN and 0 - value <= BackendConstArithmetic::I64_MAX",
    "guarded_negation_result_is_i64": "requires BackendConstArithmetic::negation_is_safe(value) ensure result == true return 0 - value >= BackendConstArithmetic::I64_MIN and 0 - value <= BackendConstArithmetic::I64_MAX",
    "minimum_negation_is_rejected": "ensure result == true return not BackendConstArithmetic::negation_is_safe(BackendConstArithmetic::I64_MIN)",
    "zero_shift_count_is_accepted": "ensure result == true return BackendConstArithmetic::shift_count_is_safe(0)",
    "last_i64_shift_count_is_accepted": "ensure result == true return BackendConstArithmetic::shift_count_is_safe(BackendConstArithmetic::I64_SHIFT_WIDTH - 1)",
    "in_range_shift_count_is_accepted": "requires count >= 0 and count < BackendConstArithmetic::I64_SHIFT_WIDTH ensure result == true return BackendConstArithmetic::shift_count_is_safe(count)",
    "guarded_shift_count_is_within_width": "requires BackendConstArithmetic::shift_count_is_safe(count) ensure result == true return count >= 0 and count < BackendConstArithmetic::I64_SHIFT_WIDTH",
    "negative_shift_count_is_rejected": "requires count < 0 ensure result == true return not BackendConstArithmetic::shift_count_is_safe(count)",
    "oversized_shift_count_is_rejected": "requires count >= BackendConstArithmetic::I64_SHIFT_WIDTH ensure result == true return not BackendConstArithmetic::shift_count_is_safe(count)",
}
for name, shape in positive_shapes.items():
    if compact(shape) not in compact(function_body(proof_text, name)):
        raise SystemExit(f"{name} no longer proves the production guard's accepted boundary")
negative_shapes = {
    "positive_add_overflow_is_accepted": "requires right > 0 and left > BackendConstArithmetic::I64_MAX - right ensure result == true return BackendConstArithmetic::add_is_safe(left, right)",
    "negative_add_underflow_is_accepted": "requires right < 0 and left < BackendConstArithmetic::I64_MIN - right ensure result == true return BackendConstArithmetic::add_is_safe(left, right)",
    "positive_subtract_overflow_is_accepted": "requires right < 0 and left > BackendConstArithmetic::I64_MAX + right ensure result == true return BackendConstArithmetic::subtract_is_safe(left, right)",
    "negative_subtract_underflow_is_accepted": "requires right > 0 and left < BackendConstArithmetic::I64_MIN + right ensure result == true return BackendConstArithmetic::subtract_is_safe(left, right)",
    "multiplication_overflow_is_accepted": "requires left > 0 and right > 0 and left > BackendConstArithmetic::I64_MAX / right ensure result == true return BackendConstArithmetic::multiply_is_safe(left, right)",
    "positive_negative_product_overflow_is_accepted": "requires left > 0 and right < 0 and right < BackendConstArithmetic::I64_MIN / left ensure result == true return BackendConstArithmetic::multiply_is_safe(left, right)",
    "negative_positive_product_overflow_is_accepted": "requires left < 0 and right > 0 and left < BackendConstArithmetic::I64_MIN / right ensure result == true return BackendConstArithmetic::multiply_is_safe(left, right)",
    "negative_negative_product_overflow_is_accepted": "requires left < 0 and right < 0 and left < BackendConstArithmetic::I64_MAX / right ensure result == true return BackendConstArithmetic::multiply_is_safe(left, right)",
    "minimum_times_negative_one_is_accepted": "ensure result == true return BackendConstArithmetic::multiply_is_safe(BackendConstArithmetic::I64_MIN, -1)",
    "negative_one_times_minimum_is_accepted": "ensure result == true return BackendConstArithmetic::multiply_is_safe(-1, BackendConstArithmetic::I64_MIN)",
    "zero_division_is_accepted": "ensure result == true return BackendConstArithmetic::division_is_safe(left, 0)",
    "minimum_divided_by_negative_one_is_accepted": "ensure result == true return BackendConstArithmetic::division_is_safe(BackendConstArithmetic::I64_MIN, -1)",
    "minimum_remainder_negative_one_is_accepted": "ensure result == true return BackendConstArithmetic::remainder_is_safe(BackendConstArithmetic::I64_MIN, -1)",
    "minimum_negation_is_accepted": "ensure result == true return BackendConstArithmetic::negation_is_safe(BackendConstArithmetic::I64_MIN)",
    "negative_shift_count_is_accepted": "ensure result == true return BackendConstArithmetic::shift_count_is_safe(-1)",
    "shift_count_equal_to_width_is_accepted": "ensure result == true return BackendConstArithmetic::shift_count_is_safe(BackendConstArithmetic::I64_SHIFT_WIDTH)",
}
for name, shape in negative_shapes.items():
    if compact(shape) not in compact(function_body(NEGATIVE.read_text(), name)):
        raise SystemExit(f"{name} no longer challenges the source-bound guard at an overflow boundary")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("constant-fold arithmetic proofs require a strict proof build")

stage1_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", ARITHMETIC, FOLDING,
    SEMANTIC_ARITHMETIC, SEMANTIC_INDEX_FOLD,
    POSITIVE, NEGATIVE, *source_include_closure([POSITIVE, NEGATIVE]),
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
if code != 0 or positive["status"] != "proved" or positive["verification_state"] != "proved":
    raise SystemExit("checked constant-fold arithmetic obligations did not all prove")
if positive["summary"]["proven"] != positive["summary"]["obligations"] or positive["findings"]:
    raise SystemExit("checked constant-fold arithmetic proof has unproved obligations")
verified = {row["name"] for row in positive["declaration_details"] if row.get("verified")}
if not positive_names <= verified:
    raise SystemExit("checked constant-fold arithmetic proof omitted verified declarations")

code, negative = run(NEGATIVE)
expected_rejections = [("ensure-unproven", name) for name in negative_order]
actual_rejections = [(finding["kind"], finding["name"]) for finding in negative["findings"]]
if code != 1 or negative["status"] != "failed" or negative["verification_state"] != "failed" or \
        actual_rejections != expected_rejections or \
        negative["summary"]["proven"] + len(negative_names) != negative["summary"]["obligations"]:
    raise SystemExit("one or more deliberately false overflow claims were not rejected")

if require_current_product(BIN, PROVER) != product:
    raise SystemExit("proof-product provenance changed during replay")
if hashes_before != {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}:
    raise SystemExit("proof or compiler sources changed during replay")

print(json.dumps({
    "admitted": True,
    "scope": "backend constant folding accepts in-range signed i64 arithmetic, rejects all signed add/subtract/multiply overflow quadrants, and validates i64 shift counts before execution",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_rejected": [name for _, name in actual_rejections],
    "proof_binary_sha256": hashlib.sha256(BIN.read_bytes()).hexdigest(),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": product["compiler"].get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
