"""Admit the constant integer division-by-zero guard against its semantic pass."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from proof_product_gate import require_current_product, source_include_closure
from division_by_zero_source import (
    compact,
    ordered_fragments,
    direct_child,
    wrap_indented_block,
    wrap_direct_child_block,
    function_section,
    enum_variant_declarations,
    struct_field_declarations,
    ast_bearing_side_table_structs,
    production_zero_constant,
    division_guard_path,
    expression_walk_path,
    expression_edges,
    statement_walk_path,
    statement_edges,
    declaration_edges,
    ROUTE_AGGREGATE_BINDINGS,
)

ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve()
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve()
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
SOURCE = ROOT / "src/semantic/check_division_by_zero.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
SEMANTIC_API = ROOT / "src/semantic/semantic_api/full_pipeline.elisa"
PARALLEL_PASSES = ROOT / "src/semantic/semantic_parallel_passes.elisa"
AST_NODES = ROOT / "src/parser/ast_nodes.elisa"
AST_SIDE_TABLES = ROOT / "src/parser/ast_side_tables.elisa"
EFFECT_TYPE_SHAPE = ROOT / "src/parser/effect_type_shape.elisa"
POSITIVE = HERE / "division_by_zero.elisa"
NEGATIVE = HERE / "division_by_zero_rejected.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


EXPECTED_EXPR_VARIANTS = tuple("""
Invalid
Absent
IntLit(value: i64, pos: Pos)
FloatLit(text: sview @source, pos: Pos)
StringLit(text: sview @source, pos: Pos)
CharLit(text: sview @source, pos: Pos)
BoolLit(value: bool, pos: Pos)
Ident(name: sview @source, pos: Pos)
Call(callee: Expr, arguments: darray[Expr] @source, argument_names: darray[sview @source] @source, pos: Pos)
StaticEffectCall(effect_type: Expr, operation: sview @source, candidates: darray[StaticEffectCandidate] @source, arguments: darray[Expr] @source, argument_names: darray[sview @source] @source, pos: Pos)
Field(object: Expr, field: sview @source, pos: Pos)
Scope(base: Expr, name: sview @source, pos: Pos)
ShorthandMember(parts: darray[sview @source] @source, pos: Pos)
Index(object: Expr, index: Expr, pos: Pos)
Slice(object: Expr, low: Expr, high: Expr, pos: Pos)
IndexN(object: Expr, arguments: darray[Expr] @source, pos: Pos)
Binary(left: Expr, operator: TokenKind, right: Expr, pos: Pos)
Unary(operator: TokenKind, operand: Expr, pos: Pos)
Move(operand: Expr, pos: Pos)
RegionNew(operand: Expr, region: sview @source, pos: Pos)
Paren(inner: Expr, pos: Pos)
Array(elements: darray[Expr] @source, pos: Pos)
Tuple(elements: darray[Expr] @source, pos: Pos)
SetLit(elements: darray[Expr] @source, pos: Pos)
DictLit(entries: darray[DictEntry] @source, pos: Pos)
Construct(type: Expr, fields: darray[FieldInit] @source, pos: Pos)
RecordUpdate(base: Expr, fields: darray[FieldInit] @source, pos: Pos)
If(condition: Expr, then_expr: Expr, else_expr: Expr, pos: Pos)
Match(scrutinee: Expr, arms: darray[MatchArm] @source, pos: Pos)
Catch(guarded: Expr, arms: darray[MatchArm] @source, pos: Pos)
Comprehension(var: sview @source, iterable: Expr, condition: Expr, body: Expr, pos: Pos, query_scope_id: u32)
Refinement(base: Expr, predicate: Expr, pos: Pos)
GetElse(guarded: Expr, recovery: darray[Stmt] @source, pos: Pos)
Lambda(params: darray[sview @source] @source, body: darray[Stmt] @source, pos: Pos)
Block(stmts: darray[Stmt] @source, value: Expr, captures: darray[sview @source] @source, pos: Pos)
""".strip().splitlines())
EXPECTED_STMT_VARIANTS = tuple("""
Invalid
Expr(expression: Expr, pos: Pos)
Block(kind: sview @source, clause: darray[sview @source] @source, binding: sview @source, body: darray[Stmt] @source, pos: Pos)
VarDecl(name: sview @source, type_expression: Expr, value: Expr, pos: Pos)
Assign(target: Expr, operator: TokenKind, value: Expr, pos: Pos)
If(condition: Expr, then_body: darray[Stmt] @source, else_body: darray[Stmt] @source, pos: Pos)
While(condition: Expr, body: darray[Stmt] @source, pos: Pos)
For(bind: sview @source, variables: darray[sview @source] @source, iterable: Expr, body: darray[Stmt] @source, pos: Pos)
Return(value: Expr?, pos: Pos)
Break(label: sview @source, pos: Pos)
Continue(label: sview @source, pos: Pos)
Match(scrutinee: Expr, arms: darray[MatchArm] @source, pos: Pos)
Contract(kind: sview @source, expression: Expr, pos: Pos)
""".strip().splitlines())
EXPECTED_DECL_VARIANT_NAMES = (
    "Invalid", "Func", "Struct", "Enum", "Alias", "Law", "Import", "Scoped", "Extern", "Const", "Module",
)
CHILD_BEARING_EXPR_ARM_NAMES = (
    "Call", "StaticEffectCall", "Field", "Scope", "Index", "Slice", "IndexN", "Binary", "Unary",
    "Move", "RegionNew", "Paren", "Array", "Tuple", "SetLit", "DictLit", "Construct", "RecordUpdate",
    "If", "Match", "Catch", "Comprehension", "Refinement", "GetElse", "Lambda", "Block",
)
CHILD_BEARING_DECL_ARM_NAMES = ("Func", "Struct", "Enum", "Alias", "Law", "Scoped", "Const", "Module")
EXPECTED_SIDE_TABLE_FIELDS = {
    "ParamDecl": ("name:sview @source", "name_pos:Pos", "type_expression:Expr", "is_mutable:bool", "has_default:bool", "default_value:Expr", "is_affine:bool", "value_thread:bool"),
    "LocalRegionAnnotation": ("name:sview @source", "type_expression:Expr", "region:sview @source", "line:u32", "end_line:mutable u32"),
    "BitGroupMember": ("name:sview @source", "type_expression:Expr", "pos:Pos"),
    "StructMember": ("is_private:bool", "name:sview @source", "type_expression:Expr", "omittable:bool", "is_ghost:bool", "has_default:bool", "default_value:Expr", "region:sview @source", "bit_group_kind:sview @source", "bit_group_members:darray[BitGroupMember] @source"),
    "EnumVariant": ("name:sview @source", "fields:darray[Expr] @source", "field_names:darray[sview @source] @source", "value_expr:Expr"),
    "MatchArm": ("pattern:Pattern", "body:darray[Stmt] @source", "guard:Expr", "pos:Pos"),
    "FieldInit": ("name:sview @source", "value:Expr", "is_copy_base:bool"),
    "StructCopyBase": tuple("type_expression:Expr base:Expr pos:Pos".split()),
    "DictEntry": tuple("key:Expr value:Expr".split()),
    "DerivedStateRule": ("owner:sview @source", "state:sview @source", "condition:Expr", "module_name:sview @source", "declaration_line:u32", "declaration_offset:u32", "pos:Pos"),
    "StaticEffectCandidate": ("effect_type:Expr", "callee:sview @source", "captures:darray[Expr] @source", "effect_identity_id:u32", "handler_identity_id:u32", "callee_owner:sview @source"),
    "EffectTypeReference": ("spelling:sview @source", "type_expression:Expr", "position:Pos", "lexical_owner:sview @source", "identity_id:u32"),
}


def explicit_match_arm_names(source: str, match_line: str, prefix: str) -> tuple[str, ...]:
    lines = source.splitlines()
    matches = [index for index, line in enumerate(lines) if line.strip() == match_line]
    if len(matches) != 1:
        return ()
    parent_indent = len(lines[matches[0]]) - len(lines[matches[0]].lstrip(" \t"))
    arm_indent = parent_indent + 4
    names = []
    for line in lines[matches[0] + 1:]:
        if line.strip() and len(line) - len(line.lstrip(" \t")) <= parent_indent:
            break
        if len(line) - len(line.lstrip(" \t")) != arm_indent:
            continue
        value = line.strip()
        if value.startswith(prefix) and value.endswith(":"):
            name = re.match(r"[A-Za-z_][A-Za-z0-9_]*", value[len(prefix):])
            if name:
                names.append(name.group(0))
    return tuple(names)


def ast_and_helper_shapes_match(walk: str, statements: str, declarations: str) -> bool:
    ast_text = AST_NODES.read_text()
    side_table_text = AST_SIDE_TABLES.read_text()
    if enum_variant_declarations(ast_text, "Expr", "Stmt") != EXPECTED_EXPR_VARIANTS:
        return False
    if enum_variant_declarations(ast_text, "Stmt", "Decl") != EXPECTED_STMT_VARIANTS:
        return False
    decl_variants = enum_variant_declarations(ast_text, "Decl", "Pattern")
    if tuple(value.split("(", 1)[0] for value in decl_variants) != EXPECTED_DECL_VARIANT_NAMES:
        return False
    if any(struct_field_declarations(side_table_text, name) != expected for name, expected in EXPECTED_SIDE_TABLE_FIELDS.items()):
        return False
    if ast_bearing_side_table_structs(side_table_text) != set(EXPECTED_SIDE_TABLE_FIELDS):
        return False
    expr_arms = explicit_match_arm_names(walk, "match expression:", "Expr.")
    if len(expr_arms) != len(CHILD_BEARING_EXPR_ARM_NAMES) or set(expr_arms) != set(CHILD_BEARING_EXPR_ARM_NAMES):
        return False
    stmt_arms = explicit_match_arm_names(statements, "match statement:", "Stmt.")
    expected_stmt_names = tuple(value.split("(", 1)[0] for value in EXPECTED_STMT_VARIANTS)
    if len(stmt_arms) != len(expected_stmt_names) or set(stmt_arms) != set(expected_stmt_names):
        return False
    decl_arms = explicit_match_arm_names(declarations, "match declaration:", "Decl.")
    if len(decl_arms) != len(CHILD_BEARING_DECL_ARM_NAMES) or set(decl_arms) != set(CHILD_BEARING_DECL_ARM_NAMES):
        return False

    helper = compact(function_section(EFFECT_TYPE_SHAPE.read_text(), "effect_runtime_children"))
    expected_helper = compact("""def effect_runtime_children(candidates: darray[StaticEffectCandidate], arguments: darray[Expr]) -> darray[Expr]:
            children: mutable darray[Expr] = []
            for candidate in candidates |children|:
                children.extend(candidate.captures)
            children.extend(arguments)
            return children""")
    return helper == expected_helper and route_aggregate_bindings_match(walk, statements, declarations)


source_text = SOURCE.read_text()


def aggregate_route_is_source_bound(
    proof_path: Path,
    lemma_name: str,
    bindings: dict[str, tuple[tuple[object, ...], ...]],
    source_sections: dict[str, str],
) -> bool:
    section = function_section(proof_path.read_text(), lemma_name)
    signature = re.search(rf"def {re.escape(lemma_name)}\((.*?)\)\s*->\s*bool:", section, re.S)
    if not signature:
        return False
    parameter_names = tuple(re.findall(r"([A-Za-z_][A-Za-z0-9_]*)\s*:\s*bool", signature.group(1)))
    fields = tuple(bindings)
    if parameter_names != fields:
        return False
    formula = " or ".join(fields)
    normalized = compact(section)
    ensure_shapes = (compact(f"ensure result == {formula}"), compact(f"ensure result == ({formula})"))
    return_shapes = (compact(f"return {formula}"), compact(f"return ({formula})"))
    if not any(shape in normalized for shape in ensure_shapes) or not any(shape in normalized for shape in return_shapes):
        return False
    for routes in bindings.values():
        for route in routes:
            group, parent_or_fragment, *edge = route
            if group == "effect_helper":
                if compact(str(parent_or_fragment)) not in compact(source_sections[group]):
                    return False
            else:
                child = edge[0]
                occurrence = int(edge[1]) if len(edge) > 1 else 0
                if not direct_child(source_sections[str(group)], str(parent_or_fragment), str(child), occurrence):
                    return False
    return True


def route_aggregate_bindings_match(walk: str, statements: str, declarations: str) -> bool:
    source_sections = {
        "expression": walk,
        "statement": statements,
        "declaration": declarations,
        "effect_helper": function_section(EFFECT_TYPE_SHAPE.read_text(), "effect_runtime_children"),
    }
    for lemma_name, bindings in ROUTE_AGGREGATE_BINDINGS.items():
        if not aggregate_route_is_source_bound(POSITIVE, lemma_name, bindings, source_sections):
            return False
    return True


def all_edges_are_direct(source: str, edges: tuple[tuple[object, ...], ...]) -> bool:
    for edge in edges:
        parent, child = edge[:2]
        occurrence = edge[2] if len(edge) == 3 else 0
        if not direct_child(source, str(parent), str(child), int(occurrence)):
            return False
    return True


def source_shape_matches(candidate: str) -> bool:
    if compact(candidate).count(compact(production_zero_constant)) != 1:
        return False
    walk = function_section(candidate, "walk_expression_for_division_by_zero")
    statements = function_section(candidate, "walk_statements_for_division_by_zero")
    declarations = function_section(candidate, "check_division_by_zero")
    return (
        ordered_fragments(walk, division_guard_path)
        and all_edges_are_direct(walk, expression_edges)
        and ordered_fragments(walk, expression_walk_path)
        and ordered_fragments(statements, statement_walk_path)
        and all_edges_are_direct(statements, statement_edges)
        and ast_and_helper_shapes_match(walk, statements, declarations)
        and all_edges_are_direct(declarations, declaration_edges)
        and compact(candidate).count("kind:DiagnosticKind.DivisionByZero") == 1
    )


if not source_shape_matches(source_text):
    raise SystemExit("division-by-zero pass no longer matches the exact literal-zero guard and recursive walk")
if 'include "./check_division_by_zero.elisa"' not in SEMANTIC.read_text():
    raise SystemExit("semantic root no longer includes the division-by-zero pass")
parallel = compact(PARALLEL_PASSES.read_text())
if "ifpass_id==4:table<-check_division_by_zero(loop_view.top_decls,table)" not in parallel:
    raise SystemExit("parallel semantic dispatch no longer calls division-by-zero at its assigned pass id")
if "par_pass_run(file,flags,table,shared_pool,loop_view,0,5)" not in compact(SEMANTIC_API.read_text()):
    raise SystemExit("semantic pipeline no longer schedules the division-by-zero pass")

mutations = (
    wrap_indented_block(source_text, "match expression:"),
    wrap_indented_block(source_text, "if operator == TokenKind.Slash:"),
    wrap_indented_block(source_text, "table <- walk_expression_for_division_by_zero(left, table)"),
    wrap_indented_block(source_text, "table <- walk_expression_for_division_by_zero(right, table)"),
    wrap_indented_block(source_text, "table <- walk_expression_for_division_by_zero(condition, table)"),
    wrap_indented_block(source_text, "for argument in arguments |table| -> table:"),
    wrap_indented_block(source_text, "Expr.StaticEffectCall(effect_type, operation, candidates, arguments, argument_names, line):"),
    wrap_indented_block(source_text, "table <- walk_expression_for_division_by_zero(child, table)"),
    wrap_indented_block(source_text, "Expr.Move(operand, line):"),
    wrap_indented_block(source_text, "table <- walk_expression_for_division_by_zero(operand, table)", 0),
    wrap_indented_block(source_text, "Expr.RegionNew(operand, region, line):"),
    wrap_indented_block(source_text, "table <- walk_expression_for_division_by_zero(operand, table)", 1),
    wrap_indented_block(source_text, "table <- walk_expression_for_division_by_zero(operand, table)", 2),
    wrap_indented_block(source_text, "table <- walk_expression_for_division_by_zero(low, table)"),
    wrap_indented_block(source_text, "Expr.Catch(guarded, arms, line):"),
    wrap_indented_block(source_text, "table <- walk_expression_for_division_by_zero(guarded, table)"),
    wrap_indented_block(source_text, "table <- walk_expression_for_division_by_zero(arm.guard, table)", 1),
    wrap_indented_block(source_text, "table <- walk_statements_for_division_by_zero(arm.body, table)", 1),
    wrap_indented_block(source_text, "Expr.Refinement(base, predicate, line):"),
    wrap_indented_block(source_text, "table <- walk_expression_for_division_by_zero(base, table)"),
    wrap_indented_block(source_text, "table <- walk_expression_for_division_by_zero(predicate, table)"),
    wrap_indented_block(source_text, "Expr.GetElse(guarded, recovery, line):"),
    wrap_indented_block(source_text, "table <- walk_expression_for_division_by_zero(guarded, table)"),
    wrap_indented_block(source_text, "table <- walk_statements_for_division_by_zero(recovery, table)"),
    source_text.replace("table <- walk_expression_for_division_by_zero(arm.guard, table)", "pass"),
    source_text.replace("if operator == TokenKind.Slash:", "if operator == TokenKind.Percent:", 1),
    source_text.replace("if divisor == DIVISION_ZERO_LITERAL", "if divisor != DIVISION_ZERO_LITERAL", 1),
    source_text.replace("if divisor == DIVISION_ZERO_LITERAL", "if divisor == 0", 1),
    source_text.replace(production_zero_constant, "const DIVISION_ZERO_LITERAL: i64 = 1", 1),
    source_text.replace("DiagnosticKind.DivisionByZero", "DiagnosticKind.ModuloByZero", 1),
    source_text.replace("Expr.IntLit(divisor, _):", "_:", 1),
    source_text.replace("walk_expression_for_division_by_zero(right, table) if operator != TokenKind.Is and operator != TokenKind.As", "pass", 1),
)
all_source_edges = (*expression_edges, *statement_edges, *declaration_edges)
edge_mutations = tuple(
    wrap_direct_child_block(
        source_text,
        str(edge[0]),
        str(edge[1]),
        int(edge[2]) if len(edge) == 3 else 0,
    )
    for edge in all_source_edges
)
mutations = (*mutations, *edge_mutations)
for mutation in mutations:
    if mutation == source_text or source_shape_matches(mutation):
        raise SystemExit("source checker failed to detect a division guard or recursive-walk mutation")

positive_names = {
    "proof_division_by_zero_reported",
    "proof_catch_division_children_reported",
    "proof_static_effect_division_children_reported",
    "proof_unary_division_child_reported",
    "proof_refinement_division_children_reported",
    "proof_get_else_division_children_reported",
    "proof_match_children_reported",
    "proof_statement_children_reported",
    "proof_declaration_children_reported",
    "integer_zero_divisor_is_reported",
    "nonzero_integer_divisor_is_not_reported",
    "zero_under_another_operator_is_not_reported",
    "zero_noninteger_literal_is_not_reported",
    "catch_scrutinee_zero_divisor_is_reported",
    "catch_arm_guard_zero_divisor_is_reported",
    "catch_arm_body_zero_divisor_is_reported",
    "static_effect_capture_zero_divisor_is_reported",
    "static_effect_argument_zero_divisor_is_reported",
    "move_operand_zero_divisor_is_reported",
    "region_new_operand_zero_divisor_is_reported",
    "refinement_base_zero_divisor_is_reported",
    "refinement_predicate_zero_divisor_is_reported",
    "get_else_guarded_zero_divisor_is_reported",
    "get_else_recovery_zero_divisor_is_reported",
}
negative_names = {
    "false_integer_zero_divisor_is_ignored",
    "false_nonzero_integer_divisor_is_reported",
    "false_other_operator_zero_is_reported",
    "false_noninteger_zero_is_reported",
    "false_expression_match_guard_is_dropped",
    "false_statement_variable_type_is_dropped",
    "false_declaration_parameter_default_is_dropped",
}
for path, names in ((POSITIVE, positive_names), (NEGATIVE, negative_names)):
    actual = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))
    if actual != names:
        raise SystemExit(f"{path.name} theorem inventory changed")
if 'include "./division_by_zero.elisa"' not in NEGATIVE.read_text():
    raise SystemExit("false controls no longer exercise the admitted division predicate")

positive_shapes = {
    "proof_division_by_zero_reported": "ensure result == (is_slash and right_is_integer_literal and divisor == DIVISION_ZERO_LITERAL) return is_slash and right_is_integer_literal and divisor == DIVISION_ZERO_LITERAL",
    "proof_catch_division_children_reported": "ensure result == (scrutinee_reported or arm_guard_reported or arm_body_reported) return scrutinee_reported or arm_guard_reported or arm_body_reported",
    "proof_static_effect_division_children_reported": "ensure result == (capture_reported or argument_reported) return capture_reported or argument_reported",
    "proof_unary_division_child_reported": "ensure result == child_reported return child_reported",
    "proof_refinement_division_children_reported": "ensure result == (base_reported or predicate_reported) return base_reported or predicate_reported",
    "proof_get_else_division_children_reported": "ensure result == (guarded_reported or recovery_reported) return guarded_reported or recovery_reported",
    "proof_match_children_reported": "def proof_match_children_reported(expression_scrutinee: bool, expression_guard: bool, expression_body: bool, statement_scrutinee: bool, statement_guard: bool, statement_body: bool) -> bool: ensure result == (expression_scrutinee or expression_guard or expression_body or statement_scrutinee or statement_guard or statement_body) return (expression_scrutinee or expression_guard or expression_body or statement_scrutinee or statement_guard or statement_body)",
    "proof_statement_children_reported": "def proof_statement_children_reported(expression: bool, variable_type: bool, variable_value: bool, assignment_target: bool, assignment_value: bool, if_condition: bool, if_then_body: bool, if_else_body: bool, while_condition: bool, while_body: bool, for_iterable: bool, for_body: bool, return_value: bool, block_body: bool, match_scrutinee: bool, match_guard: bool, match_body: bool, contract_expression: bool) -> bool: ensure result == (expression or variable_type or variable_value or assignment_target or assignment_value or if_condition or if_then_body or if_else_body or while_condition or while_body or for_iterable or for_body or return_value or block_body or match_scrutinee or match_guard or match_body or contract_expression) return (expression or variable_type or variable_value or assignment_target or assignment_value or if_condition or if_then_body or if_else_body or while_condition or while_body or for_iterable or for_body or return_value or block_body or match_scrutinee or match_guard or match_body or contract_expression)",
    "proof_declaration_children_reported": "def proof_declaration_children_reported(parameter_type: bool, parameter_default: bool, return_type: bool, function_body: bool, member_type: bool, member_default: bool, bit_member_type: bool, invariant: bool, enum_storage_type: bool, enum_payload_type: bool, enum_variant_value: bool, alias_target: bool, law_predicate: bool, const_type: bool, const_value: bool, module_body: bool, scoped_body: bool) -> bool: ensure result == (parameter_type or parameter_default or return_type or function_body or member_type or member_default or bit_member_type or invariant or enum_storage_type or enum_payload_type or enum_variant_value or alias_target or law_predicate or const_type or const_value or module_body or scoped_body) return (parameter_type or parameter_default or return_type or function_body or member_type or member_default or bit_member_type or invariant or enum_storage_type or enum_payload_type or enum_variant_value or alias_target or law_predicate or const_type or const_value or module_body or scoped_body)",
    "integer_zero_divisor_is_reported": "ensure result == true return true and true and 0 == 0",
    "nonzero_integer_divisor_is_not_reported": "requires divisor != 0 ensure result == true return not (true and true and divisor == 0)",
    "zero_under_another_operator_is_not_reported": "ensure result == true return not (false and true and 0 == 0)",
    "zero_noninteger_literal_is_not_reported": "ensure result == true return not (true and false and 0 == 0)",
    "catch_scrutinee_zero_divisor_is_reported": "ensure result == true return (true and true and 0 == 0) or false or false",
    "catch_arm_guard_zero_divisor_is_reported": "ensure result == true return false or (true and true and 0 == 0) or false",
    "catch_arm_body_zero_divisor_is_reported": "ensure result == true return false or false or (true and true and 0 == 0)",
    "static_effect_capture_zero_divisor_is_reported": "ensure result == true return (true and true and 0 == 0) or false",
    "static_effect_argument_zero_divisor_is_reported": "ensure result == true return false or (true and true and 0 == 0)",
    "move_operand_zero_divisor_is_reported": "ensure result == true return true and true and 0 == 0",
    "region_new_operand_zero_divisor_is_reported": "ensure result == true return true and true and 0 == 0",
    "refinement_base_zero_divisor_is_reported": "ensure result == true return (true and true and 0 == 0) or false",
    "refinement_predicate_zero_divisor_is_reported": "ensure result == true return false or (true and true and 0 == 0)",
    "get_else_guarded_zero_divisor_is_reported": "ensure result == true return (true and true and 0 == 0) or false",
    "get_else_recovery_zero_divisor_is_reported": "ensure result == true return false or (true and true and 0 == 0)",
}
negative_shapes = {
    "false_integer_zero_divisor_is_ignored": "ensure result == true return not (true and true and 0 == 0)",
    "false_nonzero_integer_divisor_is_reported": "requires divisor != 0 ensure result == true return true and true and divisor == 0",
    "false_other_operator_zero_is_reported": "ensure result == true return false and true and 0 == 0",
    "false_noninteger_zero_is_reported": "ensure result == true return true and false and 0 == 0",
    "false_expression_match_guard_is_dropped": "ensure result == true return not (false or true or false or false or false or false)",
    "false_statement_variable_type_is_dropped": "ensure result == true return not (false or true or false or false or false or false or false or false or false or false or false or false or false or false or false or false or false or false)",
    "false_declaration_parameter_default_is_dropped": "ensure result == true return not (false or true or false or false or false or false or false or false or false or false or false or false or false or false or false or false or false)",
}
positive_text = POSITIVE.read_text()
if compact(positive_text).count(compact("const DIVISION_ZERO_LITERAL: i64 = 0")) != 1:
    raise SystemExit("division model must name the exact zero literal used by the semantic guard")
for path, shapes in ((POSITIVE, positive_shapes), (NEGATIVE, negative_shapes)):
    text = path.read_text()
    for name, shape in shapes.items():
        if compact(shape) not in compact(function_section(text, name)):
            raise SystemExit(f"{name} no longer states its exact division-by-zero claim")

if "--source-only" in sys.argv[1:]:
    print(json.dumps({"admitted": True, "source_only": True}, sort_keys=True))
    raise SystemExit(0)

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof-product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("division-by-zero proof requires a strict proof build")
compiler = product["compiler"]
stage1_product = Path(compiler["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST.with_name(MANIFEST.name + ".sha256"),
    PROVER / "ELISA_COMPILER_REV", stage1_product, stage1_provenance,
    Path(__file__), HERE / "proof_product_gate.py", HERE / "division_by_zero_source.py", SOURCE, SEMANTIC,
    SEMANTIC_API, PARALLEL_PASSES, AST_NODES, AST_SIDE_TABLES, EFFECT_TYPE_SHAPE, POSITIVE, NEGATIVE,
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
assert positive == run(POSITIVE)[1], "division-by-zero proof report changed across identical runs"
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
