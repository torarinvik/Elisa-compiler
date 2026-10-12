"""Admit the fixed-array literal arity decision against its semantic pass."""
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
SOURCE = ROOT / "src/semantic/check_array_literal_arity.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
SEMANTIC_API = ROOT / "src/semantic/semantic_api.elisa"
POSITIVE = HERE / "array_literal_arity.elisa"
NEGATIVE = HERE / "array_literal_arity_rejected.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    return "".join(text.split())


def ordered_fragments(text: str, fragments: tuple[str, ...]) -> bool:
    normalized = compact(text)
    positions = [normalized.find(compact(fragment)) for fragment in fragments]
    return all(position >= 0 for position in positions) and positions == sorted(positions)


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"^[ \t]*def {re.escape(name)}\(", source, re.MULTILINE))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    start = matches[0].start()
    following = re.search(r"^[ \t]*def [A-Za-z_][A-Za-z0-9_]*\(", source[matches[0].end():], re.MULTILINE)
    end = matches[0].end() + following.start() if following else len(source)
    return source[start:end]


source_text = SOURCE.read_text()
extract_steps = (
    "match type_expr:",
    "Expr.Index(object, index, line):",
    "match index:",
    "Expr.IntLit(size_value, _):",
)
arity_path = (
    "expected_size:i64=extract_array_size(type_expression)",
    "ifexpected_size>=MIN_FIXED_ARRAY_EXTENT:",
    "Expr.Array(elements,array_line):",
    "actual_size:i64=elements.count.i64()",
    "ifactual_size!=expected_size:",
    "kind:DiagnosticKind.ArrayLiteralArity",
)
single_index_sequence_path = (
    "Expr.Index(object, index, line):",
    'base_is_container: bool = ident_name_of(object) == "darray" or ident_name_of(object) == "array"',
    "is_fixed_array: bool = match index:",
    "Expr.IntLit(size_value, _): true",
    "return base_is_container or is_fixed_array",
    "Expr.IndexN(object, indices, line):",
    'return ident_name_of(object) == "darray" or ident_name_of(object) == "array"',
    "return false",
)
growth_path = (
    "for statement in statements",
    "Stmt.Expr(expression, line):",
    "expression_grows_name(expression, name)",
    "Stmt.VarDecl(var_name, type_expression, value, line):",
    "expression_grows_name(value, name)",
    "Stmt.Assign(target, operator, value, line):",
    "Stmt.If(condition, then_body, else_body, line):",
    "name_is_grown(then_body, name) or name_is_grown(else_body, name)",
    "Stmt.While(condition, body, line):",
    "Stmt.For(bind, variables, iterable, body, line):",
    "Stmt.Block(kind, clause, binding, body, line):",
    "Stmt.Match(scrutinee, arms, line):",
    "name_is_grown(arm.body, name)",
    "return false",
)
expression_growth_path = (
    "Expr.Call(callee, arguments, argument_names, line):",
    "Expr.Field(receiver, method, field_line):",
    'method == "push" or method == "extend"',
    "ident_name_of(receiver) == name",
    "true return if grows",
    "return any argument in arguments where expression_grows_name(argument, name)",
    "Expr.Binary(left, operator, right, line):",
    "Expr.Paren(inner, line):",
    "return false",
)
returned_name_path = (
    "for statement in statements",
    "Stmt.Return(value, line):",
    "if value is returned_value:",
    "Expr.Ident(returned_name, ident_line): returned_name == name",
    "true return if returns_name",
    "Stmt.If(condition, then_body, else_body, line):",
    "name_is_returned(then_body, name) or name_is_returned(else_body, name)",
    "Stmt.While(condition, body, line):",
    "Stmt.For(bind, variables, iterable, body, line):",
    "Stmt.Block(kind, clause, binding, body, line):",
    "Stmt.Match(scrutinee, arms, line):",
    "name_is_returned(arm.body, name)",
    "return false",
)
empty_context_path = (
    "Stmt.Assign(target, operator, value, line):",
    "Expr.Ident(name, target_line):",
    "Expr.Array(elements, array_line):",
    "determined: bool = name_is_grown(func_body, name) or (name_is_returned(func_body, name) and type_is_sequence(func_return))",
    "kind: DiagnosticKind.EmptyArrayWithoutContext",
    "if operator == TokenKind.Assign and elements.count == EMPTY_ARRAY_ELEMENT_COUNT and not determined",
)
empty_list_value_path = (
    "match expression:",
    "Expr.Paren(inner, paren_pos):",
    "return empty_list_value(inner)",
    "Expr.Array(elements, array_pos):",
    "return (elements.count == EMPTY_ARRAY_ELEMENT_COUNT, array_pos)",
    "return (false, Ast::pos_at_line(0))",
)
match_arms_empty_lists_path = (
    "for arm in arms |table| -> table:",
    "if arm.body.count > EMPTY_ARRAY_ELEMENT_COUNT:",
    "arm.body[arm.body.count - ARRAY_LAST_INDEX_OFFSET] is Stmt.Expr(arm_value, arm_value_pos)",
    "empty: (found: bool, pos: Ast::Pos) = empty_list_value(arm_value)",
    "DiagnosticKind.EmptyArrayWithoutContext",
    "if empty.found",
    "table <- walk_match_arm_empty_lists(arm.body, table)",
)
expr_match_arm_empty_lists_path = (
    "Expr.Match(scrutinee, arms, match_pos):",
    "table <- match_arms_empty_lists(arms, table)",
    "Expr.Paren(inner, paren_pos):",
    "table <- expr_match_arm_empty_lists(inner, table)",
)
walk_match_arm_empty_lists_path = (
    "Stmt.VarDecl(name, type_expression, value, line): table <- expr_match_arm_empty_lists(value, table)",
    "Stmt.Assign(target, operator, value, line): table <- expr_match_arm_empty_lists(value, table)",
    "Stmt.Return(value, line): if value is returned: table <- expr_match_arm_empty_lists(returned, table)",
    "Stmt.Expr(expression, line): table <- expr_match_arm_empty_lists(expression, table)",
    "Stmt.Match(scrutinee, arms, line): table <- match_arms_empty_lists(arms, table)",
    "Stmt.If(condition, then_body, else_body, line): table <- walk_match_arm_empty_lists(then_body, table) table <- walk_match_arm_empty_lists(else_body, table)",
    "Stmt.While(condition, while_body, line): table <- walk_match_arm_empty_lists(while_body, table)",
    "Stmt.For(bind, variables, iterable, for_body, line): table <- walk_match_arm_empty_lists(for_body, table)",
    "Stmt.Block(kind, clause, binding, body, line): table <- walk_match_arm_empty_lists(body, table)",
)


def source_shape_matches(candidate: str) -> bool:
    compact_source = compact(candidate)
    source_constants = (
        "const ARRAY_SIZE_UNKNOWN: i64 = 0 - 1",
        "const MIN_FIXED_ARRAY_EXTENT: i64 = 1",
        "const EMPTY_ARRAY_ELEMENT_COUNT: usize = 0",
        "const ARRAY_LAST_INDEX_OFFSET: usize = 1",
    )
    if any(compact(constant) not in compact_source for constant in source_constants):
        return False
    extract = compact(function_section(candidate, "extract_array_size"))
    extract_positions = [extract.find(compact(step)) for step in extract_steps]
    if (any(pos < 0 for pos in extract_positions) or extract_positions != sorted(extract_positions)
            or "Expr.IntLit(size_value,_):returnsize_value_:" not in extract
            or extract.count("returnARRAY_SIZE_UNKNOWN") != 2):
        return False
    walk = compact(function_section(candidate, "walk_array_arity_check"))
    walk_positions = [walk.find(fragment) for fragment in arity_path]
    if any(pos < 0 for pos in walk_positions) or walk_positions != sorted(walk_positions):
        return False
    if compact(candidate).count("kind:DiagnosticKind.ArrayLiteralArity") != 1:
        return False
    assignment_start = walk.find(compact(empty_context_path[0]))
    if assignment_start < 0:
        return False
    assignment_branch = walk[assignment_start:]
    context_positions = [assignment_branch.find(compact(fragment)) for fragment in empty_context_path]
    if any(pos < 0 for pos in context_positions) or context_positions != sorted(context_positions):
        return False
    sequence = function_section(candidate, "type_is_sequence")
    grown = function_section(candidate, "name_is_grown")
    expression_growth = function_section(candidate, "expression_grows_name")
    returned_name = function_section(candidate, "name_is_returned")
    empty_value = function_section(candidate, "empty_list_value")
    match_arms = function_section(candidate, "match_arms_empty_lists")
    match_expression = function_section(candidate, "expr_match_arm_empty_lists")
    match_walk = function_section(candidate, "walk_match_arm_empty_lists")
    entry = function_section(candidate, "check_array_literal_arity")
    return (
        ordered_fragments(sequence, single_index_sequence_path)
        and ordered_fragments(grown, growth_path)
        and ordered_fragments(expression_growth, expression_growth_path)
        and ordered_fragments(returned_name, returned_name_path)
        and ordered_fragments(empty_value, empty_list_value_path)
        and ordered_fragments(match_arms, match_arms_empty_lists_path)
        and "type_is_sequence" not in compact(match_arms)
        and ordered_fragments(match_expression, expr_match_arm_empty_lists_path)
        and ordered_fragments(match_walk, walk_match_arm_empty_lists_path)
        and ordered_fragments(entry, (
            "table <- walk_array_arity_check(body, body, func_return, table)",
            "table <- walk_match_arm_empty_lists(body, table)",
        ))
    )


if not source_shape_matches(source_text):
    raise SystemExit("array-arity source no longer matches its arity, context, and match-arm proof model")
if 'include "./check_array_literal_arity.elisa"' not in SEMANTIC.read_text():
    raise SystemExit("semantic root no longer includes the fixed-array arity pass")
if "table<-check_array_literal_arity(loop_view.top_decls,table)" not in compact(SEMANTIC_API.read_text()):
    raise SystemExit("semantic pipeline no longer invokes the fixed-array arity pass")

mutations = (
    source_text.replace("if expected_size >= MIN_FIXED_ARRAY_EXTENT:", "if expected_size >= 0:", 1),
    source_text.replace("if actual_size != expected_size:", "if actual_size == expected_size:", 1),
    source_text.replace("return size_value", "return size_value + 1", 1),
    source_text.replace("actual_size: i64 = elements.count.i64()", "actual_size: i64 = expected_size", 1),
    source_text.replace("return ARRAY_SIZE_UNKNOWN", "return (0 - 2)", 1),
    source_text.replace("const ARRAY_SIZE_UNKNOWN: i64 = 0 - 1", "const ARRAY_SIZE_UNKNOWN: i64 = 0 - 2", 1),
    source_text.replace("base_is_container or is_fixed_array", "base_is_container and is_fixed_array", 1),
    source_text.replace("name_is_grown(func_body, name) or (name_is_returned(func_body, name)", "name_is_grown(func_body, name) and (name_is_returned(func_body, name)", 1),
    source_text.replace("name_is_returned(func_body, name) and type_is_sequence(func_return)", "name_is_returned(func_body, name) or type_is_sequence(func_return)", 1),
    source_text.replace("elements.count == EMPTY_ARRAY_ELEMENT_COUNT and not determined", "elements.count > EMPTY_ARRAY_ELEMENT_COUNT and not determined", 1),
    source_text.replace('method == "push" or method == "extend"', 'method == "push" and method == "extend"', 1),
    source_text.replace("returned_name == name", "returned_name != name", 1),
    source_text.replace("return empty_list_value(inner)", "return (false, paren_pos)", 1),
    source_text.replace("elements.count == EMPTY_ARRAY_ELEMENT_COUNT, array_pos", "elements.count > EMPTY_ARRAY_ELEMENT_COUNT, array_pos", 1),
    source_text.replace("arm.body.count - ARRAY_LAST_INDEX_OFFSET", "arm.body.count", 1),
    source_text.replace("if empty.found", "if empty.found and type_is_sequence(Ast::Expr.Invalid)", 1),
    source_text.replace("table <- walk_match_arm_empty_lists(then_body, table)", "table <- walk_match_arm_empty_lists(else_body, table)", 1),
)
for mutation in mutations:
    if mutation == source_text or source_shape_matches(mutation):
        raise SystemExit("source checker failed to detect an extent/count/guard mutation")

positive_names = {
    "proof_single_index_type_is_sequence",
    "proof_multi_index_type_is_sequence",
    "proof_array_literal_arity_mismatch",
    "equal_positive_arity_is_accepted",
    "shorter_literal_is_rejected",
    "longer_literal_is_rejected",
    "empty_literal_is_rejected_for_positive_extent",
    "zero_extent_is_not_an_arity_diagnostic",
    "negative_unmodeled_extent_is_not_an_arity_diagnostic",
    "one_element_literal_matches_one_element_extent",
    "one_element_literal_mismatches_two_element_extent",
    "fixed_extent_type_is_a_sequence",
    "container_type_is_a_sequence",
    "scalar_indexed_type_is_not_a_sequence",
    "multi_index_container_type_is_a_sequence",
    "multi_index_scalar_type_is_not_a_sequence",
    "proof_empty_assignment_needs_context",
    "empty_assignment_without_context_is_reported",
    "later_push_or_extend_supplies_context",
    "returning_empty_binding_with_sequence_type_supplies_context",
    "returning_empty_binding_with_nonsequence_type_needs_context",
    "a_nonassignment_empty_literal_does_not_trigger_this_rule",
    "a_nonempty_assignment_does_not_trigger_this_rule",
    "parenthesized_empty_array_value",
    "proof_match_arm_requires_empty_context",
    "arbitrary_parentheses_preserve_array_emptiness",
    "several_parentheses_preserve_an_empty_array",
    "several_parentheses_preserve_a_nonempty_array",
    "empty_final_match_expression_is_reported_for_any_return_context",
    "nonempty_final_match_expression_is_not_reported",
    "nonexpression_match_arm_tail_is_not_reported",
    "empty_match_arm_body_is_not_reported",
}
negative_names = {
    "false_equal_positive_arity_is_rejected",
    "false_shorter_literal_is_accepted",
    "false_longer_literal_is_accepted",
    "false_zero_extent_reports_mismatch",
    "false_negative_extent_reports_mismatch",
    "false_empty_literal_is_accepted_for_positive_extent",
    "false_fixed_extent_type_is_not_a_sequence",
    "false_container_type_is_not_a_sequence",
    "false_scalar_indexed_type_is_a_sequence",
    "false_multi_index_scalar_type_is_a_sequence",
    "false_empty_assignment_without_context_is_suppressed",
    "false_later_growth_fails_to_supply_context",
    "false_returned_sequence_fails_to_supply_context",
    "false_returned_nonsequence_suppresses_context_error",
    "false_nonassignment_triggers_empty_context_error",
    "false_nonempty_assignment_triggers_empty_context_error",
    "false_parentheses_change_empty_array_classification",
    "false_nonempty_array_is_classified_empty",
    "false_empty_final_match_expression_is_ignored",
    "false_nonempty_final_match_expression_is_reported",
    "false_nonexpression_match_arm_tail_is_reported",
    "false_empty_match_arm_body_is_reported",
    "false_sequence_return_context_suppresses_match_arm_error",
}
for path, names in ((POSITIVE, positive_names), (NEGATIVE, negative_names)):
    actual = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))
    if actual != names:
        raise SystemExit(f"{path.name} theorem inventory changed")
if 'include "./array_literal_arity.elisa"' not in NEGATIVE.read_text():
    raise SystemExit("false controls no longer exercise the admitted arity predicate")

positive_shapes = {
    "proof_single_index_type_is_sequence": "ensure result == (base_is_container or index_is_integer_literal) return base_is_container or index_is_integer_literal",
    "proof_multi_index_type_is_sequence": "ensure result == base_is_container return base_is_container",
    "proof_array_literal_arity_mismatch": "ensure result == (expected_size >= MIN_FIXED_ARRAY_EXTENT and actual_size != expected_size) return expected_size >= MIN_FIXED_ARRAY_EXTENT and actual_size != expected_size",
    "equal_positive_arity_is_accepted": "requires expected_size >= MIN_FIXED_ARRAY_EXTENT and actual_size == expected_size ensure result == true return not proof_array_literal_arity_mismatch(expected_size, actual_size)",
    "shorter_literal_is_rejected": "requires expected_size >= MIN_FIXED_ARRAY_EXTENT and actual_size >= EMPTY_ARRAY_LITERAL_COUNT and actual_size < expected_size ensure result == true return proof_array_literal_arity_mismatch(expected_size, actual_size)",
    "longer_literal_is_rejected": "requires expected_size >= MIN_FIXED_ARRAY_EXTENT and actual_size > expected_size ensure result == true return proof_array_literal_arity_mismatch(expected_size, actual_size)",
    "empty_literal_is_rejected_for_positive_extent": "requires expected_size >= MIN_FIXED_ARRAY_EXTENT ensure result == true return proof_array_literal_arity_mismatch(expected_size, EMPTY_ARRAY_LITERAL_COUNT)",
    "zero_extent_is_not_an_arity_diagnostic": "requires actual_size >= EMPTY_ARRAY_LITERAL_COUNT ensure result == true return not proof_array_literal_arity_mismatch(EMPTY_ARRAY_LITERAL_COUNT, actual_size)",
    "negative_unmodeled_extent_is_not_an_arity_diagnostic": "requires actual_size >= EMPTY_ARRAY_LITERAL_COUNT ensure result == true return not proof_array_literal_arity_mismatch(ARRAY_SIZE_UNKNOWN, actual_size)",
    "one_element_literal_matches_one_element_extent": "ensure result == true return not proof_array_literal_arity_mismatch(MIN_FIXED_ARRAY_EXTENT, MIN_FIXED_ARRAY_EXTENT)",
    "one_element_literal_mismatches_two_element_extent": "ensure result == true return proof_array_literal_arity_mismatch(TWO_ELEMENT_EXTENT, MIN_FIXED_ARRAY_EXTENT)",
    "fixed_extent_type_is_a_sequence": "ensure result == true return proof_single_index_type_is_sequence(false, true)",
    "container_type_is_a_sequence": "ensure result == true return proof_single_index_type_is_sequence(true, false)",
    "scalar_indexed_type_is_not_a_sequence": "ensure result == false return proof_single_index_type_is_sequence(false, false)",
    "multi_index_container_type_is_a_sequence": "ensure result == true return proof_multi_index_type_is_sequence(true)",
    "multi_index_scalar_type_is_not_a_sequence": "ensure result == false return proof_multi_index_type_is_sequence(false)",
    "proof_empty_assignment_needs_context": "ensure result == (is_assignment and is_empty and not (has_later_growth or (is_returned and return_type_is_sequence))) return is_assignment and is_empty and not (has_later_growth or (is_returned and return_type_is_sequence))",
    "empty_assignment_without_context_is_reported": "ensure result == true return proof_empty_assignment_needs_context(true, true, false, false, false)",
    "later_push_or_extend_supplies_context": "ensure result == true return not proof_empty_assignment_needs_context(true, true, true, false, false)",
    "returning_empty_binding_with_sequence_type_supplies_context": "ensure result == true return not proof_empty_assignment_needs_context(true, true, false, true, true)",
    "returning_empty_binding_with_nonsequence_type_needs_context": "ensure result == true return proof_empty_assignment_needs_context(true, true, false, true, false)",
    "a_nonassignment_empty_literal_does_not_trigger_this_rule": "ensure result == true return not proof_empty_assignment_needs_context(false, true, false, false, false)",
    "a_nonempty_assignment_does_not_trigger_this_rule": "ensure result == true return not proof_empty_assignment_needs_context(true, false, false, false, false)",
    "parenthesized_empty_array_value": "decreases parentheses_remaining ensure result == (element_count == EMPTY_ARRAY_ELEMENT_COUNT) if parentheses_remaining == EMPTY_ARRAY_ELEMENT_COUNT: return element_count == EMPTY_ARRAY_ELEMENT_COUNT else: assert(parentheses_remaining > EMPTY_ARRAY_ELEMENT_COUNT) return parenthesized_empty_array_value(parentheses_remaining - ARRAY_LAST_INDEX_OFFSET, element_count)",
    "proof_match_arm_requires_empty_context": "ensure result == (body_is_nonempty and final_statement_is_expression and final_expression_is_empty) return body_is_nonempty and final_statement_is_expression and final_expression_is_empty",
    "arbitrary_parentheses_preserve_array_emptiness": "ensure result == true parsed: bool = parenthesized_empty_array_value(parentheses_remaining, element_count) return parsed == (element_count == EMPTY_ARRAY_ELEMENT_COUNT)",
    "several_parentheses_preserve_an_empty_array": "ensure result == true return parenthesized_empty_array_value(5, EMPTY_ARRAY_ELEMENT_COUNT)",
    "several_parentheses_preserve_a_nonempty_array": "ensure result == false return parenthesized_empty_array_value(5, ONE_ELEMENT_ARRAY_COUNT)",
    "empty_final_match_expression_is_reported_for_any_return_context": "ensure result == true return proof_match_arm_requires_empty_context(true, true, true, return_type_is_sequence)",
    "nonempty_final_match_expression_is_not_reported": "ensure result == false return proof_match_arm_requires_empty_context(true, true, false, return_type_is_sequence)",
    "nonexpression_match_arm_tail_is_not_reported": "ensure result == false return proof_match_arm_requires_empty_context(true, false, true, return_type_is_sequence)",
    "empty_match_arm_body_is_not_reported": "ensure result == false return proof_match_arm_requires_empty_context(false, true, true, return_type_is_sequence)",
}
positive_text = POSITIVE.read_text()
positive_compact = compact(positive_text)
proof_constants = (
    "const ARRAY_SIZE_UNKNOWN: i64 = 0 - 1",
    "const MIN_FIXED_ARRAY_EXTENT: i64 = 1",
    "const EMPTY_ARRAY_LITERAL_COUNT: i64 = 0",
    "const TWO_ELEMENT_EXTENT: i64 = 2",
    "const EMPTY_ARRAY_ELEMENT_COUNT: usize = 0",
    "const ONE_ELEMENT_ARRAY_COUNT: usize = 1",
    "const ARRAY_LAST_INDEX_OFFSET: usize = 1",
)
if any(positive_compact.count(compact(constant)) != 1 for constant in proof_constants):
    raise SystemExit("proof model must name and match the production sentinel and fixed-array extent boundary")
for name, shape in positive_shapes.items():
    if compact(shape) not in compact(function_section(positive_text, name)):
        raise SystemExit(f"{name} no longer states its intended arity law")
negative_shapes = {
    "false_equal_positive_arity_is_rejected": "requires expected_size >= MIN_FIXED_ARRAY_EXTENT and actual_size == expected_size ensure result == true proof_array_literal_arity_mismatch(expected_size, actual_size)",
    "false_shorter_literal_is_accepted": "requires expected_size >= MIN_FIXED_ARRAY_EXTENT and actual_size >= EMPTY_ARRAY_LITERAL_COUNT and actual_size < expected_size ensure result == true not proof_array_literal_arity_mismatch(expected_size, actual_size)",
    "false_longer_literal_is_accepted": "requires expected_size >= MIN_FIXED_ARRAY_EXTENT and actual_size > expected_size ensure result == true not proof_array_literal_arity_mismatch(expected_size, actual_size)",
    "false_zero_extent_reports_mismatch": "requires actual_size > EMPTY_ARRAY_LITERAL_COUNT ensure result == true proof_array_literal_arity_mismatch(EMPTY_ARRAY_LITERAL_COUNT, actual_size)",
    "false_negative_extent_reports_mismatch": "requires actual_size >= EMPTY_ARRAY_LITERAL_COUNT ensure result == true proof_array_literal_arity_mismatch(ARRAY_SIZE_UNKNOWN, actual_size)",
    "false_empty_literal_is_accepted_for_positive_extent": "requires expected_size >= MIN_FIXED_ARRAY_EXTENT ensure result == true not proof_array_literal_arity_mismatch(expected_size, EMPTY_ARRAY_LITERAL_COUNT)",
    "false_fixed_extent_type_is_not_a_sequence": "ensure result == true not proof_single_index_type_is_sequence(false, true)",
    "false_container_type_is_not_a_sequence": "ensure result == true not proof_single_index_type_is_sequence(true, false)",
    "false_scalar_indexed_type_is_a_sequence": "ensure result == true proof_single_index_type_is_sequence(false, false)",
    "false_multi_index_scalar_type_is_a_sequence": "ensure result == true proof_multi_index_type_is_sequence(false)",
    "false_empty_assignment_without_context_is_suppressed": "ensure result == true not proof_empty_assignment_needs_context(true, true, false, false, false)",
    "false_later_growth_fails_to_supply_context": "ensure result == true proof_empty_assignment_needs_context(true, true, true, false, false)",
    "false_returned_sequence_fails_to_supply_context": "ensure result == true proof_empty_assignment_needs_context(true, true, false, true, true)",
    "false_returned_nonsequence_suppresses_context_error": "ensure result == true not proof_empty_assignment_needs_context(true, true, false, true, false)",
    "false_nonassignment_triggers_empty_context_error": "ensure result == true proof_empty_assignment_needs_context(false, true, false, false, false)",
    "false_nonempty_assignment_triggers_empty_context_error": "ensure result == true proof_empty_assignment_needs_context(true, false, false, false, false)",
    "false_parentheses_change_empty_array_classification": "ensure result == true not parenthesized_empty_array_value(parentheses_remaining, EMPTY_ARRAY_ELEMENT_COUNT)",
    "false_nonempty_array_is_classified_empty": "requires parentheses_remaining > EMPTY_ARRAY_ELEMENT_COUNT ensure result == true parenthesized_empty_array_value(parentheses_remaining, ONE_ELEMENT_ARRAY_COUNT)",
    "false_empty_final_match_expression_is_ignored": "ensure result == true not proof_match_arm_requires_empty_context(true, true, true, return_type_is_sequence)",
    "false_nonempty_final_match_expression_is_reported": "ensure result == true proof_match_arm_requires_empty_context(true, true, false, return_type_is_sequence)",
    "false_nonexpression_match_arm_tail_is_reported": "ensure result == true proof_match_arm_requires_empty_context(true, false, true, return_type_is_sequence)",
    "false_empty_match_arm_body_is_reported": "ensure result == true proof_match_arm_requires_empty_context(false, true, true, return_type_is_sequence)",
    "false_sequence_return_context_suppresses_match_arm_error": "ensure result == true not proof_match_arm_requires_empty_context(true, true, true, true)",
}
negative_text = NEGATIVE.read_text()
for name, shape in negative_shapes.items():
    if compact(shape) not in compact(function_section(negative_text, name)):
        raise SystemExit(f"{name} no longer challenges the arity boundary")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("array-literal arity proof requires a strict proof build")
compiler = product["compiler"]
stage1_product = Path(compiler["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", SOURCE, SEMANTIC, SEMANTIC_API,
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
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["declarations"] == len(positive_names)
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
assert positive["summary"]["obligations"] >= len(positive_names)
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "array-literal arity proof report changed across identical runs"
assert positive_names <= {row["name"] for row in positive["declaration_details"] if row.get("verified")}

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["verification_state"] in {"failed", "disproved"}
assert negative["summary"]["declarations"] == len(positive_names) + len(negative_names)
assert negative["summary"]["obligations"] - negative["summary"]["proven"] == len(negative_names)
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" and row["status"] in {"unknown", "disproved"}
           for row in negative["findings"])
assert not negative_names & {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product
print(json.dumps({
    "admitted": True,
    "scope": "fixed-array literal arity, empty-assignment inference context, and empty final match-arm expressions",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": compiler.get("source_revision"),
    "sources_sha256": hashes_before,
}, sort_keys=True))
