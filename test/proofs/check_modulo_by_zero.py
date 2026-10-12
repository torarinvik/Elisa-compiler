"""Admit the constant integer modulo-by-zero guard against its semantic pass."""
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
SOURCE = ROOT / "src/semantic/check_modulo_by_zero.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
SEMANTIC_API = ROOT / "src/semantic/semantic_api.elisa"
PARALLEL_PASSES = ROOT / "src/semantic/semantic_parallel_passes.elisa"
AST_NODES = ROOT / "src/parser/ast_nodes.elisa"
AST_SIDE_TABLES = ROOT / "src/parser/ast_side_tables.elisa"
EFFECT_TYPE_SHAPE = ROOT / "src/parser/effect_type_shape.elisa"
POSITIVE = HERE / "modulo_by_zero.elisa"
NEGATIVE = HERE / "modulo_by_zero_rejected.elisa"
DIVISION_CHECKER = HERE / "check_division_by_zero.py"

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
division_checker_text = DIVISION_CHECKER.read_text()
shape_gate = "if not source_shape_matches(source_text):"
if shape_gate not in division_checker_text:
    raise SystemExit("shared division source-walk shape checker is missing")
shape_namespace: dict[str, object] = {"__file__": str(DIVISION_CHECKER)}
shape_prefix = division_checker_text[:division_checker_text.index(shape_gate)]
exec(compile(shape_prefix, str(DIVISION_CHECKER), "exec"), shape_namespace)
shared_source_shape_matches = shape_namespace["source_shape_matches"]
wrap_indented_block = shape_namespace["wrap_indented_block"]


def source_shape_matches(candidate: str) -> bool:
    source = compact(candidate)
    if source.count("ifoperator==TokenKind.Percent:") != 1:
        return False
    if source.count("DiagnosticKind.ModuloByZero") != 1:
        return False
    if source.count("ifdivisor==MODULO_ZERO_LITERAL") != 1:
        return False
    if source.count(compact("const MODULO_ZERO_LITERAL: i64 = 0")) != 1:
        return False
    normalized = (candidate.replace("MODULO_ZERO_LITERAL", "DIVISION_ZERO_LITERAL")
                  .replace("DiagnosticKind.ModuloByZero", "DiagnosticKind.DivisionByZero")
                  .replace("TokenKind.Percent", "TokenKind.Slash")
                  .replace("modulo_by_zero", "division_by_zero")
                  .replace("Modulo", "Division")
                  .replace("modulo", "division"))
    return bool(shared_source_shape_matches(normalized))


if compact(source_text).count(compact("const MODULO_ZERO_LITERAL: i64 = 0")) != 1:
    raise SystemExit("modulo pass must name its exact zero divisor boundary once")
if not source_shape_matches(source_text):
    raise SystemExit("modulo-by-zero pass no longer matches the fully checked recursive zero-division walk")
if 'include "./check_modulo_by_zero.elisa"' not in SEMANTIC.read_text():
    raise SystemExit("semantic root no longer includes the modulo-by-zero pass")
parallel = compact(PARALLEL_PASSES.read_text())
if "ifpass_id==39:table<-check_modulo_by_zero(loop_view.top_decls,table)" not in parallel:
    raise SystemExit("parallel semantic dispatch no longer calls modulo-by-zero at pass id 39")
if "par_pass_run(file,&loop_view,flags,table,shared_pool,35,8)" not in compact(SEMANTIC_API.read_text()):
    raise SystemExit("semantic pipeline no longer schedules the modulo-by-zero pass")

mutations = (
    wrap_indented_block(source_text, "match expression:"),
    wrap_indented_block(source_text, "if operator == TokenKind.Percent:"),
    wrap_indented_block(source_text, "table <- walk_expression_for_modulo_by_zero(left, table)"),
    wrap_indented_block(source_text, "table <- walk_expression_for_modulo_by_zero(right, table)"),
    wrap_indented_block(source_text, "table <- walk_expression_for_modulo_by_zero(condition, table)"),
    wrap_indented_block(source_text, "for argument in arguments |table| -> table:"),
    wrap_indented_block(source_text, "Expr.StaticEffectCall(effect_type, operation, candidates, arguments, argument_names, line):"),
    wrap_indented_block(source_text, "table <- walk_expression_for_modulo_by_zero(child, table)"),
    wrap_indented_block(source_text, "Expr.Move(operand, line):"),
    wrap_indented_block(source_text, "table <- walk_expression_for_modulo_by_zero(operand, table)", 0),
    wrap_indented_block(source_text, "Expr.RegionNew(operand, region, line):"),
    wrap_indented_block(source_text, "table <- walk_expression_for_modulo_by_zero(operand, table)", 1),
    wrap_indented_block(source_text, "table <- walk_expression_for_modulo_by_zero(operand, table)", 2),
    wrap_indented_block(source_text, "table <- walk_expression_for_modulo_by_zero(low, table)"),
    wrap_indented_block(source_text, "Expr.Catch(guarded, arms, line):"),
    wrap_indented_block(source_text, "table <- walk_expression_for_modulo_by_zero(guarded, table)"),
    wrap_indented_block(source_text, "table <- walk_expression_for_modulo_by_zero(arm.guard, table)", 1),
    wrap_indented_block(source_text, "table <- walk_statements_for_modulo_by_zero(arm.body, table)", 1),
    wrap_indented_block(source_text, "Expr.Refinement(base, predicate, line):"),
    wrap_indented_block(source_text, "table <- walk_expression_for_modulo_by_zero(base, table)"),
    wrap_indented_block(source_text, "table <- walk_expression_for_modulo_by_zero(predicate, table)"),
    wrap_indented_block(source_text, "Expr.GetElse(guarded, recovery, line):"),
    wrap_indented_block(source_text, "table <- walk_expression_for_modulo_by_zero(guarded, table)"),
    wrap_indented_block(source_text, "table <- walk_statements_for_modulo_by_zero(recovery, table)"),
    source_text.replace("table <- walk_expression_for_modulo_by_zero(arm.guard, table)", "pass"),
    source_text.replace("if operator == TokenKind.Percent:", "if operator == TokenKind.Slash:", 1),
    source_text.replace("if divisor == MODULO_ZERO_LITERAL", "if divisor != MODULO_ZERO_LITERAL", 1),
    source_text.replace("if divisor == MODULO_ZERO_LITERAL", "if divisor == 0", 1),
    source_text.replace("const MODULO_ZERO_LITERAL: i64 = 0", "const MODULO_ZERO_LITERAL: i64 = 1", 1),
    source_text.replace("DiagnosticKind.ModuloByZero", "DiagnosticKind.DivisionByZero", 1),
    source_text.replace("Expr.IntLit(divisor, _):", "_:", 1),
    source_text.replace("walk_expression_for_modulo_by_zero(right, table) if operator != TokenKind.Is and operator != TokenKind.As", "pass", 1),
)
for mutation in mutations:
    if mutation == source_text or source_shape_matches(mutation):
        raise SystemExit("source checker failed to detect a modulo guard or recursive-walk mutation")

normalized_source_text = (source_text.replace("MODULO_ZERO_LITERAL", "DIVISION_ZERO_LITERAL")
                         .replace("DiagnosticKind.ModuloByZero", "DiagnosticKind.DivisionByZero")
                         .replace("TokenKind.Percent", "TokenKind.Slash")
                         .replace("modulo_by_zero", "division_by_zero")
                         .replace("Modulo", "Division")
                         .replace("modulo", "division"))
modulo_route_lemma_names = {
    "proof_catch_division_children_reported": "proof_catch_modulo_children_reported",
    "proof_static_effect_division_children_reported": "proof_static_effect_modulo_children_reported",
    "proof_unary_division_child_reported": "proof_unary_modulo_child_reported",
    "proof_refinement_division_children_reported": "proof_refinement_modulo_children_reported",
    "proof_get_else_division_children_reported": "proof_get_else_modulo_children_reported",
    "proof_match_children_reported": "proof_match_modulo_children_reported",
    "proof_statement_children_reported": "proof_modulo_statement_children_reported",
    "proof_declaration_children_reported": "proof_modulo_declaration_children_reported",
}
route_bindings = shape_namespace["ROUTE_AGGREGATE_BINDINGS"]
source_sections = {
    "expression": function_section(normalized_source_text, "walk_expression_for_division_by_zero"),
    "statement": function_section(normalized_source_text, "walk_statements_for_division_by_zero"),
    "declaration": function_section(normalized_source_text, "check_division_by_zero"),
    "effect_helper": shape_namespace["function_section"](
        EFFECT_TYPE_SHAPE.read_text(), "effect_runtime_children"
    ),
}
for division_lemma, modulo_lemma in modulo_route_lemma_names.items():
    if not shape_namespace["aggregate_route_is_source_bound"](
        POSITIVE, modulo_lemma, route_bindings[division_lemma], source_sections
    ):
        raise SystemExit(f"{modulo_lemma} is no longer bound to the audited modulo child edges")
all_source_edges = (*shape_namespace["expression_edges"], *shape_namespace["statement_edges"],
                    *shape_namespace["declaration_edges"])
for edge in all_source_edges:
    parent, child = str(edge[0]), str(edge[1])
    occurrence = int(edge[2]) if len(edge) == 3 else 0
    mutation = shape_namespace["wrap_direct_child_block"](
        normalized_source_text, parent, child, occurrence
    )
    if mutation == normalized_source_text or shared_source_shape_matches(mutation):
        raise SystemExit("source checker failed to detect a removed modulo recursive-walk edge")

positive_names = {
    "proof_modulo_by_zero_reported",
    "proof_catch_modulo_children_reported",
    "proof_static_effect_modulo_children_reported",
    "proof_unary_modulo_child_reported",
    "proof_refinement_modulo_children_reported",
    "proof_get_else_modulo_children_reported",
    "proof_match_modulo_children_reported",
    "proof_modulo_statement_children_reported",
    "proof_modulo_declaration_children_reported",
    "integer_zero_modulo_divisor_is_reported",
    "nonzero_modulo_divisor_is_not_reported",
    "zero_under_another_operator_is_not_a_modulo_error",
    "zero_noninteger_literal_is_not_a_modulo_error",
    "catch_scrutinee_zero_modulo_divisor_is_reported",
    "catch_arm_guard_zero_modulo_divisor_is_reported",
    "catch_arm_body_zero_modulo_divisor_is_reported",
    "static_effect_capture_zero_modulo_divisor_is_reported",
    "static_effect_argument_zero_modulo_divisor_is_reported",
    "move_operand_zero_modulo_divisor_is_reported",
    "region_new_operand_zero_modulo_divisor_is_reported",
    "refinement_base_zero_modulo_divisor_is_reported",
    "refinement_predicate_zero_modulo_divisor_is_reported",
    "get_else_guarded_zero_modulo_divisor_is_reported",
    "get_else_recovery_zero_modulo_divisor_is_reported",
}
negative_names = {
    "false_integer_zero_modulo_divisor_is_ignored",
    "false_nonzero_modulo_divisor_is_reported",
    "false_other_operator_zero_is_a_modulo_error",
    "false_noninteger_zero_is_a_modulo_error",
    "false_expression_match_guard_is_dropped_for_modulo",
    "false_statement_variable_type_is_dropped_for_modulo",
    "false_declaration_parameter_default_is_dropped_for_modulo",
}
for path, names in ((POSITIVE, positive_names), (NEGATIVE, negative_names)):
    actual = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))
    if actual != names:
        raise SystemExit(f"{path.name} theorem inventory changed")
if 'include "./modulo_by_zero.elisa"' not in NEGATIVE.read_text():
    raise SystemExit("false modulo controls no longer exercise the admitted predicate")

positive_shapes = {
    "proof_modulo_by_zero_reported": "ensure result == (is_percent and right_is_integer_literal and divisor == MODULO_ZERO_LITERAL) return is_percent and right_is_integer_literal and divisor == MODULO_ZERO_LITERAL",
    "proof_catch_modulo_children_reported": "ensure result == (scrutinee_reported or arm_guard_reported or arm_body_reported) return scrutinee_reported or arm_guard_reported or arm_body_reported",
    "proof_static_effect_modulo_children_reported": "ensure result == (capture_reported or argument_reported) return capture_reported or argument_reported",
    "proof_unary_modulo_child_reported": "ensure result == child_reported return child_reported",
    "proof_refinement_modulo_children_reported": "ensure result == (base_reported or predicate_reported) return base_reported or predicate_reported",
    "proof_get_else_modulo_children_reported": "ensure result == (guarded_reported or recovery_reported) return guarded_reported or recovery_reported",
    "proof_match_modulo_children_reported": "def proof_match_modulo_children_reported(expression_scrutinee: bool, expression_guard: bool, expression_body: bool, statement_scrutinee: bool, statement_guard: bool, statement_body: bool) -> bool: ensure result == (expression_scrutinee or expression_guard or expression_body or statement_scrutinee or statement_guard or statement_body) return (expression_scrutinee or expression_guard or expression_body or statement_scrutinee or statement_guard or statement_body)",
    "proof_modulo_statement_children_reported": "def proof_modulo_statement_children_reported(expression: bool, variable_type: bool, variable_value: bool, assignment_target: bool, assignment_value: bool, if_condition: bool, if_then_body: bool, if_else_body: bool, while_condition: bool, while_body: bool, for_iterable: bool, for_body: bool, return_value: bool, block_body: bool, match_scrutinee: bool, match_guard: bool, match_body: bool, contract_expression: bool) -> bool: ensure result == (expression or variable_type or variable_value or assignment_target or assignment_value or if_condition or if_then_body or if_else_body or while_condition or while_body or for_iterable or for_body or return_value or block_body or match_scrutinee or match_guard or match_body or contract_expression) return (expression or variable_type or variable_value or assignment_target or assignment_value or if_condition or if_then_body or if_else_body or while_condition or while_body or for_iterable or for_body or return_value or block_body or match_scrutinee or match_guard or match_body or contract_expression)",
    "proof_modulo_declaration_children_reported": "def proof_modulo_declaration_children_reported(parameter_type: bool, parameter_default: bool, return_type: bool, function_body: bool, member_type: bool, member_default: bool, bit_member_type: bool, invariant: bool, enum_storage_type: bool, enum_payload_type: bool, enum_variant_value: bool, alias_target: bool, law_predicate: bool, const_type: bool, const_value: bool, module_body: bool, scoped_body: bool) -> bool: ensure result == (parameter_type or parameter_default or return_type or function_body or member_type or member_default or bit_member_type or invariant or enum_storage_type or enum_payload_type or enum_variant_value or alias_target or law_predicate or const_type or const_value or module_body or scoped_body) return (parameter_type or parameter_default or return_type or function_body or member_type or member_default or bit_member_type or invariant or enum_storage_type or enum_payload_type or enum_variant_value or alias_target or law_predicate or const_type or const_value or module_body or scoped_body)",
    "integer_zero_modulo_divisor_is_reported": "ensure result == true return true and true and 0 == 0",
    "nonzero_modulo_divisor_is_not_reported": "requires divisor != 0 ensure result == true return not (true and true and divisor == 0)",
    "zero_under_another_operator_is_not_a_modulo_error": "ensure result == true return not (false and true and 0 == 0)",
    "zero_noninteger_literal_is_not_a_modulo_error": "ensure result == true return not (true and false and 0 == 0)",
    "catch_scrutinee_zero_modulo_divisor_is_reported": "ensure result == true return (true and true and 0 == 0) or false or false",
    "catch_arm_guard_zero_modulo_divisor_is_reported": "ensure result == true return false or (true and true and 0 == 0) or false",
    "catch_arm_body_zero_modulo_divisor_is_reported": "ensure result == true return false or false or (true and true and 0 == 0)",
    "static_effect_capture_zero_modulo_divisor_is_reported": "ensure result == true return (true and true and 0 == 0) or false",
    "static_effect_argument_zero_modulo_divisor_is_reported": "ensure result == true return false or (true and true and 0 == 0)",
    "move_operand_zero_modulo_divisor_is_reported": "ensure result == true return true and true and 0 == 0",
    "region_new_operand_zero_modulo_divisor_is_reported": "ensure result == true return true and true and 0 == 0",
    "refinement_base_zero_modulo_divisor_is_reported": "ensure result == true return (true and true and 0 == 0) or false",
    "refinement_predicate_zero_modulo_divisor_is_reported": "ensure result == true return false or (true and true and 0 == 0)",
    "get_else_guarded_zero_modulo_divisor_is_reported": "ensure result == true return (true and true and 0 == 0) or false",
    "get_else_recovery_zero_modulo_divisor_is_reported": "ensure result == true return false or (true and true and 0 == 0)",
}
negative_shapes = {
    "false_integer_zero_modulo_divisor_is_ignored": "ensure result == true return not (true and true and 0 == 0)",
    "false_nonzero_modulo_divisor_is_reported": "requires divisor != 0 ensure result == true return true and true and divisor == 0",
    "false_other_operator_zero_is_a_modulo_error": "ensure result == true return false and true and 0 == 0",
    "false_noninteger_zero_is_a_modulo_error": "ensure result == true return true and false and 0 == 0",
    "false_expression_match_guard_is_dropped_for_modulo": "ensure result == true return not (false or true or false or false or false or false)",
    "false_statement_variable_type_is_dropped_for_modulo": "ensure result == true return not (false or true or false or false or false or false or false or false or false or false or false or false or false or false or false or false or false or false)",
    "false_declaration_parameter_default_is_dropped_for_modulo": "ensure result == true return not (false or true or false or false or false or false or false or false or false or false or false or false or false or false or false or false or false)",
}
if compact(POSITIVE.read_text()).count(compact("const MODULO_ZERO_LITERAL: i64 = 0")) != 1:
    raise SystemExit("modulo proof must name the production zero divisor boundary")
for path, shapes in ((POSITIVE, positive_shapes), (NEGATIVE, negative_shapes)):
    text = path.read_text()
    for name, shape in shapes.items():
        if compact(shape) not in compact(function_section(text, name)):
            raise SystemExit(f"{name} no longer states its exact modulo-by-zero claim")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("modulo-by-zero proof requires a strict proof build")
compiler = product["compiler"]
stage1_product = Path(compiler["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", DIVISION_CHECKER, SOURCE,
    SEMANTIC, SEMANTIC_API, PARALLEL_PASSES, AST_NODES, AST_SIDE_TABLES, EFFECT_TYPE_SHAPE, POSITIVE, NEGATIVE,
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
assert positive["summary"]["declarations"] == len(positive_names) + 1  # the zero-boundary constant
assert positive["summary"]["proven"] == positive["summary"]["obligations"]
assert not positive["findings"]
assert positive == run(POSITIVE)[1], "modulo-by-zero proof report changed across identical runs"
assert positive_names == {row["name"] for row in positive["declaration_details"] if row.get("verified")}

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["verification_state"] in {"failed", "disproved"}
assert negative["summary"]["declarations"] == len(positive_names) + len(negative_names) + 1
assert negative["summary"]["obligations"] - negative["summary"]["proven"] == len(negative_names)
assert {row["name"] for row in negative["findings"]} == negative_names
assert all(row["kind"] == "ensure-unproven" and row["status"] in {"unknown", "disproved"}
           for row in negative["findings"])
assert not negative_names & {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert hashes_before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert require_current_product(BIN, PROVER) == product
print(json.dumps({
    "admitted": True,
    "scope": "the proof model establishes the literal-zero guard equation and Boolean OR laws; independently, the source checker matches each abstract child-report input to a named AST walk edge and rejects edge-loss mutations across expression, statement, and declaration walks; this is structural correspondence, not a proof of symbol-table state accumulation",
    "positive_obligations": positive["summary"]["proven"],
    "false_claims_refused": sorted(negative_names),
    "proof_revision": product["proof"].get("head"),
    "compiler_revision": compiler.get("source_revision"),
    "source_sha256": hashes_before,
}, sort_keys=True))
