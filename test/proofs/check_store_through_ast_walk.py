"""Source-bind conservative store-through collection to runtime-value AST children."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from proof_product_gate import require_current_product, source_include_closure


ROOT = Path(__file__).resolve().parents[2]
PROVER = Path(os.environ.get("ELISA_PROOF_ROOT", ROOT.parent / "elisa-proof")).resolve(strict=True)
HERE = Path(__file__).resolve().parent
BIN = Path(os.environ.get("ELISA_PROOF_BIN", PROVER / "build/elisa-proof")).resolve(strict=True)
SUMMARY = ROOT / "src/semantic/store_through_summary.elisa"
HOLDER_SOURCE = ROOT / "src/semantic/check_call_holder_view_store.elisa"
AST_NODES = ROOT / "src/parser/ast_nodes.elisa"
AST_SIDE_TABLES = ROOT / "src/parser/ast_side_tables.elisa"
EFFECT_SHAPE = ROOT / "src/parser/effect_type_shape.elisa"
POSITIVE = HERE / "store_through_ast_walk.elisa"
NEGATIVE = HERE / "store_through_ast_walk_rejected.elisa"
MANIFEST = BIN.with_name(BIN.name + ".manifest.json")
MANIFEST_CHECKSUM = MANIFEST.with_name(MANIFEST.name + ".sha256")
PROOF_TIMEOUT_SECONDS = 120

EXPECTED_EXPR_NAMES = tuple("""Invalid Absent IntLit FloatLit StringLit CharLit BoolLit Ident Call
    StaticEffectCall Field Scope ShorthandMember Index Slice IndexN Binary Unary Move RegionNew Paren
    Array Tuple SetLit DictLit Construct RecordUpdate If Match Catch Comprehension Refinement GetElse Lambda Block""".split())
EXPECTED_STMT_NAMES = tuple("Invalid Expr Block VarDecl Assign If While For Return Break Continue Match Contract".split())
EXPECTED_SIDE_TABLE_FIELDS = {
    "MatchArm": ("pattern:Pattern", "body:darray[Stmt] @source", "guard:Expr", "pos:Pos"),
    "DictEntry": ("key:Expr", "value:Expr"),
    "FieldInit": ("name:sview @source", "value:Expr", "is_copy_base:bool"),
    "StaticEffectCandidate": (
        "effect_type:Expr", "callee:sview @source", "captures:darray[Expr] @source",
        "effect_identity_id:u32", "handler_identity_id:u32", "callee_owner:sview @source",
    ),
}
CHV_FLOW_NAMES = (
    "flow", "then_flow", "else_flow", "merged_flow", "arm_flow", "guarded_flow",
    "entry_flow", "recovery_flow", "comprehension_flow", "lambda_flow", "loop_flow",
    "left_flow", "right_flow",
)


def compact(text: str) -> str:
    return re.sub(r'"(?:\\.|[^"\\])*"|\s+',
                  lambda match: match.group(0) if match.group(0).startswith('"') else "", text)


def compact_code(text: str) -> str:
    return compact("\n".join(line for line in text.splitlines()
                              if not line.lstrip().startswith("#")))


def function_section(text: str, name: str) -> str:
    match = re.search(rf"(?m)^\s*def {re.escape(name)}\([^\n]*\n(.*?)(?=^\s*def |\Z)", text, re.DOTALL)
    if not match:
        raise SystemExit(f"missing source function {name}")
    return match.group(1)


def enum_variant_names(text: str, name: str, next_name: str) -> tuple[str, ...]:
    match = re.search(rf"(?ms)^    enum {re.escape(name)} is Node:\n(.*?)(?=^    enum {re.escape(next_name)} is Node:)", text)
    if not match:
        raise SystemExit(f"AST enum {name} is missing")
    variants = []
    for line in match.group(1).splitlines():
        if len(line) - len(line.lstrip(" \t")) != 8:
            continue
        variant = re.match(r"([A-Z][A-Za-z0-9_]*)(?:\(|$)", line.strip())
        if variant:
            variants.append(variant.group(1))
    return tuple(variants)


def explicit_match_arm_names(source: str, match_line: str, prefix: str) -> tuple[str, ...]:
    lines = source.splitlines()
    matches = [index for index, line in enumerate(lines) if line.strip() == match_line]
    if len(matches) != 1:
        return ()
    parent_indent = len(lines[matches[0]]) - len(lines[matches[0]].lstrip(" \t"))
    names = []
    for line in lines[matches[0] + 1:]:
        if line.strip() and len(line) - len(line.lstrip(" \t")) <= parent_indent:
            break
        if len(line) - len(line.lstrip(" \t")) != parent_indent + 4:
            continue
        value = line.strip()
        # A guarded arm can make the displayed AST variant unreachable (for
        # example, `Stmt.For(...) if false:`). Do not let the broad prefix
        # check count it as an exhaustive recursive case.
        if value.startswith(prefix) and value.endswith(":") and " if " not in value:
            match = re.match(r"[A-Za-z_][A-Za-z0-9_]*", value[len(prefix):])
            if match:
                names.append(match.group(0))
    return tuple(names)


_GUARDED_ARM_SAMPLE = """match statement:
    Stmt.For(bind, variables, iterable, body, _) if false:
        pass
"""
if "For" in explicit_match_arm_names(_GUARDED_ARM_SAMPLE, "match statement:", "Stmt."):
    raise SystemExit("guarded AST match arms must not satisfy exhaustive-source checks")


def match_arm_body(source: str, match_line: str, arm_text: str) -> str | None:
    lines = source.splitlines()
    matches = [index for index, line in enumerate(lines) if line.strip() == match_line]
    if len(matches) != 1:
        return None
    match_index = matches[0]
    match_indent = len(lines[match_index]) - len(lines[match_index].lstrip(" \t"))
    arm_indent = match_indent + 4
    arm_indices = [index for index in range(match_index + 1, len(lines))
                   if lines[index].strip() == arm_text
                   and len(lines[index]) - len(lines[index].lstrip(" \t")) == arm_indent]
    if len(arm_indices) != 1:
        return None
    arm_index = arm_indices[0]
    end = arm_index + 1
    while end < len(lines):
        line = lines[end]
        if line.strip() and len(line) - len(line.lstrip(" \t")) <= arm_indent:
            break
        end += 1
    return "\n".join(lines[arm_index + 1:end])


def source_route(line: str) -> str:
    # Explicit `&flow` and the implicit mutable-place borrow identify the same
    # CHVViewFlow row for this source-bound dataflow check.
    for flow_name in CHV_FLOW_NAMES:
        line = re.sub(rf"([,(])(\s*)&{flow_name}\b", rf"\1\2{flow_name}", line)
    return line.strip()


def direct_child(source: str, parent: str, child: str, occurrence: int = 0) -> bool:
    lines = source.splitlines()
    parents = [index for index, line in enumerate(lines) if line.strip() == parent]
    if occurrence >= len(parents):
        return False
    parent_index = parents[occurrence]
    parent_indent = len(lines[parent_index]) - len(lines[parent_index].lstrip(" \t"))
    end = parent_index + 1
    while end < len(lines):
        line = lines[end]
        if line.strip() and len(line) - len(line.lstrip(" \t")) <= parent_indent:
            break
        end += 1
    children = [index for index in range(parent_index + 1, end)
                if source_route(lines[index]) == child
                and len(lines[index]) - len(lines[index].lstrip(" \t")) == parent_indent + 4]
    return len(children) == 1


def validate_ordered_source_lines(source: str, expected_lines: tuple[str, ...], label: str) -> None:
    """Require selected source steps to appear in execution order within one AST arm."""
    lines = [source_route(line) for line in source.splitlines()]
    previous_index = -1
    for expected in expected_lines:
        next_index = next((index for index in range(previous_index + 1, len(lines))
                           if lines[index] == expected), None)
        if next_index is None:
            raise SystemExit(f"{label} is missing or reorders step: {expected}")
        previous_index = next_index


def edge_parts(edge: tuple) -> tuple[str, str, int]:
    if len(edge) == 2:
        return edge[0], edge[1], 0
    if len(edge) == 3:
        return edge[0], edge[1], edge[2]
    raise SystemExit("malformed store-through source edge")


def wrap_direct_child_block(source: str, parent: str, child: str, occurrence: int = 0) -> str:
    lines = source.splitlines()
    parents = [index for index, line in enumerate(lines) if line.strip() == parent]
    if occurrence >= len(parents):
        return source
    parent_index = parents[occurrence]
    parent_indent = len(lines[parent_index]) - len(lines[parent_index].lstrip(" \t"))
    end = parent_index + 1
    while end < len(lines):
        line = lines[end]
        if line.strip() and len(line) - len(line.lstrip(" \t")) <= parent_indent:
            break
        end += 1
    children = [index for index in range(parent_index + 1, end)
                if source_route(lines[index]) == child
                and len(lines[index]) - len(lines[index].lstrip(" \t")) == parent_indent + 4]
    if len(children) != 1:
        return source
    child_index = children[0]
    child_indent = len(lines[child_index]) - len(lines[child_index].lstrip(" \t"))
    block_end = child_index + 1
    while block_end < end:
        line = lines[block_end]
        if line.strip() and len(line) - len(line.lstrip(" \t")) <= child_indent:
            break
        block_end += 1
    indentation = lines[child_index][:child_indent]
    wrapped = [indentation + "if false:"]
    wrapped.extend("    " + line if line.strip() else line for line in lines[child_index:block_end])
    lines[child_index:block_end] = wrapped
    return "\n".join(lines) + ("\n" if source.endswith("\n") else "")


def struct_fields(text: str, name: str) -> tuple[str, ...]:
    match = re.search(rf"(?ms)^    struct {re.escape(name)}:\n(.*?)(?=^    (?:struct|enum|def)\b|\Z)", text)
    if not match:
        raise SystemExit(f"AST side-table record {name} is missing")
    fields = []
    for line in match.group(1).splitlines():
        field = re.fullmatch(r"        ([A-Za-z_][A-Za-z0-9_]*): ([^=]+?)(?: = .+)?", line)
        if field:
            fields.append(f"{field.group(1)}:{field.group(2).strip()}")
    return tuple(fields)


EXPRESSION_EDGES = (
    ("Expr.Call(callee, arguments, _, _):", "sts_collect_names(callee, out)"),
    ("Expr.Call(callee, arguments, _, _):", "for argument in arguments |out|:"),
    ("for argument in arguments |out|:", "sts_collect_names(argument, out)", 0),
    ("for argument in arguments |out|:", "sts_collect_names(argument, out)", 1),
    ("Expr.StaticEffectCall(candidates: candidates, arguments: arguments, _):", "for candidate in candidates |out|:"),
    ("for candidate in candidates |out|:", "for capture in candidate.captures |out|:"),
    ("for capture in candidate.captures |out|:", "sts_collect_names(capture, out)"),
    ("Expr.StaticEffectCall(candidates: candidates, arguments: arguments, _):", "for argument in arguments |out|:"),
    ("for argument in arguments |out|:", "sts_collect_names(argument, out)", 2),
    ("Expr.Field(object, _, _):", "sts_collect_names(object, out)"),
    ("Expr.Index(object, index, _):", "sts_collect_names(object, out)"),
    ("Expr.Index(object, index, _):", "sts_collect_names(index, out)"),
    ("Expr.Slice(object, low, high, _):", "sts_collect_names(object, out)"),
    ("Expr.Slice(object, low, high, _):", "sts_collect_names(low, out)"),
    ("Expr.Slice(object, low, high, _):", "sts_collect_names(high, out)"),
    ("Expr.IndexN(object, arguments, _):", "sts_collect_names(object, out)"),
    ("Expr.IndexN(object, arguments, _):", "for argument in arguments |out|:"),
    ("Expr.Binary(left, _, right, _):", "sts_collect_names(left, out)"),
    ("Expr.Binary(left, _, right, _):", "sts_collect_names(right, out)"),
    ("Expr.Unary(_, operand, _):", "sts_collect_names(operand, out)"),
    ("Expr.Move(operand, _):", "sts_collect_names(operand, out)"),
    ("Expr.RegionNew(operand, _, _):", "sts_collect_names(operand, out)"),
    ("Expr.Paren(inner, _):", "sts_collect_names(inner, out)"),
    ("Expr.Array(elements, _):", "for element in elements |out|:"),
    ("Expr.Tuple(elements, _):", "for element in elements |out|:"),
    ("Expr.SetLit(elements, _):", "for element in elements |out|:"),
    ("for element in elements |out|:", "sts_collect_names(element, out)", 0),
    ("for element in elements |out|:", "sts_collect_names(element, out)", 1),
    ("for element in elements |out|:", "sts_collect_names(element, out)", 2),
    ("Expr.DictLit(entries, _):", "for entry in entries |out|:"),
    ("for entry in entries |out|:", "sts_collect_names(entry.key, out)"),
    ("for entry in entries |out|:", "sts_collect_names(entry.value, out)"),
    ("Expr.Construct(_, fields, _):", "for field in fields |out|:"),
    ("Expr.RecordUpdate(base, fields, _):", "sts_collect_names(base, out)"),
    ("Expr.RecordUpdate(base, fields, _):", "for field in fields |out|:"),
    ("for field in fields |out|:", "sts_collect_names(field.value, out)", 0),
    ("for field in fields |out|:", "sts_collect_names(field.value, out)", 1),
    ("Expr.If(condition, then_value, else_value, _):", "sts_collect_names(condition, out)"),
    ("Expr.If(condition, then_value, else_value, _):", "sts_collect_names(then_value, out)"),
    ("Expr.If(condition, then_value, else_value, _):", "sts_collect_names(else_value, out)"),
    ("Expr.Match(scrutinee, arms, _):", "sts_collect_names(scrutinee, out)"),
    ("Expr.Match(scrutinee, arms, _):", "for arm in arms |out|:"),
    ("Expr.Catch(guarded, arms, _):", "sts_collect_names(guarded, out)"),
    ("Expr.Catch(guarded, arms, _):", "for arm in arms |out|:"),
    ("for arm in arms |out|:", "sts_collect_names(arm.guard, out)", 0),
    ("for arm in arms |out|:", "sts_collect_names(arm.guard, out)", 1),
    ("for arm in arms |out|:", "sts_collect_statement_names(arm.body, out)", 0),
    ("for arm in arms |out|:", "sts_collect_statement_names(arm.body, out)", 1),
    ("Expr.Comprehension(iterable: iterable, condition: condition, body: body, _):", "sts_collect_names(iterable, out)"),
    ("Expr.Comprehension(iterable: iterable, condition: condition, body: body, _):", "sts_collect_names(condition, out)"),
    ("Expr.Comprehension(iterable: iterable, condition: condition, body: body, _):", "sts_collect_names(body, out)"),
    ("Expr.Refinement(base, predicate, _):", "sts_collect_names(base, out)"),
    ("Expr.Refinement(base, predicate, _):", "sts_collect_names(predicate, out)"),
    ("Expr.GetElse(guarded, recovery, _):", "sts_collect_names(guarded, out)"),
    ("Expr.GetElse(guarded, recovery, _):", "sts_collect_statement_names(recovery, out)"),
    ("Expr.Lambda(_, body, _):", "sts_collect_statement_names(body, out)"),
    ("Expr.Block(statements, value, captures, _):", "for capture in captures |out|:"),
    ("for capture in captures |out|:", "out.push(capture) if capture != \"\""),
    ("Expr.Block(statements, value, captures, _):", "sts_collect_statement_names(statements, out)"),
    ("Expr.Block(statements, value, captures, _):", "sts_collect_names(value, out)"),
)

STATEMENT_COLLECTOR_EDGES = (
    ("Stmt.Expr(expression, _):", "sts_collect_names(expression, out)"),
    ("Stmt.Block(body: body, _):", "sts_collect_statement_names(body, out)"),
    ("Stmt.VarDecl(value: value, _):", "sts_collect_names(value, out)"),
    ("Stmt.Assign(target, _, value, _):", "sts_collect_names(target, out)"),
    ("Stmt.Assign(target, _, value, _):", "sts_collect_names(value, out)"),
    ("Stmt.If(condition, then_body, else_body, _):", "sts_collect_names(condition, out)"),
    ("Stmt.If(condition, then_body, else_body, _):", "sts_collect_statement_names(then_body, out)"),
    ("Stmt.If(condition, then_body, else_body, _):", "sts_collect_statement_names(else_body, out)"),
    ("Stmt.While(condition, body, _):", "sts_collect_names(condition, out)"),
    ("Stmt.While(condition, body, _):", "sts_collect_statement_names(body, out)"),
    ("Stmt.For(iterable: iterable, body: body, _):", "sts_collect_names(iterable, out)"),
    ("Stmt.For(iterable: iterable, body: body, _):", "sts_collect_statement_names(body, out)"),
    ("Stmt.Return(value, _):", "sts_collect_names(return_value, out) if value is return_value"),
    ("Stmt.Match(scrutinee, arms, _):", "sts_collect_names(scrutinee, out)"),
    ("Stmt.Match(scrutinee, arms, _):", "for arm in arms |out|:"),
    ("for arm in arms |out|:", "sts_collect_names(arm.guard, out)"),
    ("for arm in arms |out|:", "sts_collect_statement_names(arm.body, out)"),
    ("Stmt.Contract(_, expression, _):", "sts_collect_names(expression, out)"),
)

STATEMENT_UNIFIER_EDGES = (
    ("Stmt.VarDecl(declared_name, declared_type, declared_value, _):", "sts_unify_bound(declared_name, declared_type, declared_value, summary, has_unreadable_binder, function_owner, reference_sites, table, classes)"),
    ("Stmt.Assign(assign_target, assign_operator, assign_value, _):", "if not sts_same_target_lmut_rebind(assign_target, assign_operator, assign_value, has_unreadable_binder, function_owner, reference_sites, table) and not sts_assignment_rhs_is_reference_free(assign_value, assign_operator, has_unreadable_binder, function_owner, reference_sites, table):"),
    ("if not sts_same_target_lmut_rebind(assign_target, assign_operator, assign_value, has_unreadable_binder, function_owner, reference_sites, table) and not sts_assignment_rhs_is_reference_free(assign_value, assign_operator, has_unreadable_binder, function_owner, reference_sites, table):", "sts_collect_names(assign_target, assign_names)"),
    ("if not sts_same_target_lmut_rebind(assign_target, assign_operator, assign_value, has_unreadable_binder, function_owner, reference_sites, table) and not sts_assignment_rhs_is_reference_free(assign_value, assign_operator, has_unreadable_binder, function_owner, reference_sites, table):", "sts_collect_names(assign_value, assign_names)"),
    ("if not sts_same_target_lmut_rebind(assign_target, assign_operator, assign_value, has_unreadable_binder, function_owner, reference_sites, table) and not sts_assignment_rhs_is_reference_free(assign_value, assign_operator, has_unreadable_binder, function_owner, reference_sites, table):", "sts_unify_all(classes, assign_names)"),
    ("Stmt.Assign(assign_target, assign_operator, assign_value, _):", "sts_unify_calls(assign_target, summary, has_unreadable_binder, function_owner, reference_sites, table, classes)"),
    ("Stmt.Assign(assign_target, assign_operator, assign_value, _):", "sts_unify_calls(assign_value, summary, has_unreadable_binder, function_owner, reference_sites, table, classes)"),
    ("Stmt.Expr(statement_value, _):", "sts_unify_calls(statement_value, summary, has_unreadable_binder, function_owner, reference_sites, table, classes)"),
    ("Stmt.Return(returned, _):", "if returned is returned_value:"),
    ("if returned is returned_value:", "sts_unify_return_calls(returned_value, summary, has_unreadable_binder, function_owner, reference_sites, table, classes)"),
    ("Stmt.If(condition, then_body, else_body, _):", "sts_unify_calls(condition, summary, has_unreadable_binder, function_owner, reference_sites, table, classes)"),
    ("Stmt.If(condition, then_body, else_body, _):", "sts_statements(then_body, summary, has_unreadable_binder, function_owner, reference_sites, table, classes)"),
    ("Stmt.If(condition, then_body, else_body, _):", "sts_statements(else_body, summary, has_unreadable_binder, function_owner, reference_sites, table, classes)"),
    ("Stmt.While(condition, loop_body, _):", "sts_unify_calls(condition, summary, has_unreadable_binder, function_owner, reference_sites, table, classes)"),
    ("Stmt.While(condition, loop_body, _):", "sts_statements(loop_body, summary, has_unreadable_binder, function_owner, reference_sites, table, classes)"),
    ("Stmt.For(_, loop_variables, iterable, loop_body, _):", "for loop_variable in loop_variables |classes, reference_sites|:"),
    ("for loop_variable in loop_variables |classes, reference_sites|:", "sts_unify_bound(loop_variable, Expr.Invalid, iterable, summary, has_unreadable_binder, function_owner, reference_sites, table, classes)"),
    ("Stmt.For(_, loop_variables, iterable, loop_body, _):", "sts_unify_calls(iterable, summary, has_unreadable_binder, function_owner, reference_sites, table, classes)"),
    ("Stmt.For(_, loop_variables, iterable, loop_body, _):", "sts_statements(loop_body, summary, has_unreadable_binder, function_owner, reference_sites, table, classes)"),
    ("Stmt.Block(body: block_body, _):", "sts_statements(block_body, summary, has_unreadable_binder, function_owner, reference_sites, table, classes)"),
    ("Stmt.Match(scrutinee, arms, _):", "sts_unify_calls(scrutinee, summary, has_unreadable_binder, function_owner, reference_sites, table, classes)"),
    ("Stmt.Match(scrutinee, arms, _):", "for arm in arms |classes, reference_sites|:"),
    ("for arm in arms |classes, reference_sites|:", "sts_unify_calls(arm.guard, summary, has_unreadable_binder, function_owner, reference_sites, table, classes)"),
    ("for arm in arms |classes, reference_sites|:", "sts_statements(arm.body, summary, has_unreadable_binder, function_owner, reference_sites, table, classes)"),
    ("Stmt.Contract(_, expression, _):", "sts_unify_calls(expression, summary, has_unreadable_binder, function_owner, reference_sites, table, classes)"),
)

EXPRESSION_UNIFIER_EDGES = (
    ("Expr.Call(callee, arguments, argument_names, _):", "sts_unify_calls(callee, summary, has_unreadable_binder, function_owner, reference_sites, table, classes)"),
    ("Expr.Call(callee, arguments, argument_names, _):", "for argument in arguments |classes, reference_sites|:"),
    ("for argument in arguments |classes, reference_sites|:", "sts_unify_calls(argument, summary, has_unreadable_binder, function_owner, reference_sites, table, classes)"),
    ("Expr.Ident(callee_name, callee_position):", "shadowed: bool = borrow_reference_site_is_local(reference_sites, function_owner, callee_position, table) or has_unreadable_binder"),
    ("Expr.Ident(callee_name, callee_position):", "if sts_is_declared(summary, callee_name) and not shadowed and not (any argument_name in argument_names where argument_name != \"\"):", 0),
    ("Expr.Field(object, _, _):", "sts_unify_calls(object, summary, has_unreadable_binder, function_owner, reference_sites, table, classes)"),
    ("Expr.Index(object, index, _):", "sts_unify_calls(object, summary, has_unreadable_binder, function_owner, reference_sites, table, classes)"),
    ("Expr.Index(object, index, _):", "sts_unify_calls(index, summary, has_unreadable_binder, function_owner, reference_sites, table, classes)"),
    ("Expr.Binary(left, _, right, _):", "sts_unify_calls(left, summary, has_unreadable_binder, function_owner, reference_sites, table, classes)"),
    ("Expr.Binary(left, _, right, _):", "sts_unify_calls(right, summary, has_unreadable_binder, function_owner, reference_sites, table, classes)"),
    ("Expr.Unary(_, operand, _):", "sts_unify_calls(operand, summary, has_unreadable_binder, function_owner, reference_sites, table, classes)"),
    ("Expr.Move(operand, _):", "sts_unify_calls(operand, summary, has_unreadable_binder, function_owner, reference_sites, table, classes)"),
    ("Expr.Paren(inner, _):", "sts_unify_calls(inner, summary, has_unreadable_binder, function_owner, reference_sites, table, classes)"),
    ("Expr.If(condition, then_value, else_value, _):", "sts_unify_calls(condition, summary, has_unreadable_binder, function_owner, reference_sites, table, classes)"),
    ("Expr.If(condition, then_value, else_value, _):", "sts_unify_calls(then_value, summary, has_unreadable_binder, function_owner, reference_sites, table, classes)"),
    ("Expr.If(condition, then_value, else_value, _):", "sts_unify_calls(else_value, summary, has_unreadable_binder, function_owner, reference_sites, table, classes)"),
)

HOLDER_SCAN_STATEMENT_EDGES = (
    ("Stmt.VarDecl(declared_name, type_expression, declared_value, _):", "chv_scan_expression_locals(declared_value, in_region, binders, owned, view_names, view_values)"),
    ("Stmt.Assign(target, _, assigned_value, _):", "chv_scan_expression_locals(target, in_region, binders, owned, view_names, view_values)"),
    ("Stmt.Assign(target, _, assigned_value, _):", "chv_scan_expression_locals(assigned_value, in_region, binders, owned, view_names, view_values)"),
    ("Stmt.If(condition, then_body, else_body, _):", "chv_scan_expression_locals(condition, in_region, binders, owned, view_names, view_values)"),
    ("Stmt.If(condition, then_body, else_body, _):", "chv_scan_locals(then_body, in_region, binders, owned, view_names, view_values)"),
    ("Stmt.If(condition, then_body, else_body, _):", "chv_scan_locals(else_body, in_region, binders, owned, view_names, view_values)"),
    ("Stmt.While(condition, loop_body, _):", "chv_scan_expression_locals(condition, in_region, binders, owned, view_names, view_values)"),
    ("Stmt.While(condition, loop_body, _):", "chv_scan_locals(loop_body, in_region, binders, owned, view_names, view_values)"),
    ("Stmt.For(_, loop_variables, iterable, loop_body, _):", "chv_scan_expression_locals(iterable, in_region, binders, owned, view_names, view_values)"),
    ("Stmt.For(_, loop_variables, iterable, loop_body, _):", "chv_scan_locals(loop_body, in_region, binders, owned, view_names, view_values)"),
    ("Stmt.Block(kind, _, binding, block_body, _):", "chv_scan_locals(block_body, in_region or kind == \"region\" or kind == \"in\", binders, owned, view_names, view_values)"),
    ("Stmt.Match(scrutinee, arms, _):", "chv_scan_expression_locals(scrutinee, in_region, binders, owned, view_names, view_values)"),
    ("Stmt.Match(scrutinee, arms, _):", "for arm in arms |binders, owned, view_names, view_values|:"),
    ("for arm in arms |binders, owned, view_names, view_values|:", "chv_scan_expression_locals(arm.guard, in_region, binders, owned, view_names, view_values)"),
    ("for arm in arms |binders, owned, view_names, view_values|:", "chv_scan_locals(arm.body, in_region, binders, owned, view_names, view_values)"),
    ("Stmt.Expr(expression, _):", "chv_scan_expression_locals(expression, in_region, binders, owned, view_names, view_values)"),
    ("Stmt.Return(value, _):", "chv_scan_expression_locals(returned_value, in_region, binders, owned, view_names, view_values) if value is returned_value"),
    ("Stmt.Contract(_, expression, _):", "chv_scan_expression_locals(expression, in_region, binders, owned, view_names, view_values)"),
)

HOLDER_SCAN_EXPRESSION_EDGES = (
    ("Expr.Call(callee, arguments, _, _):", "chv_scan_expression_locals(callee, in_region, binders, owned, view_names, view_values)"),
    ("Expr.Call(callee, arguments, _, _):", "for argument in arguments |binders, owned, view_names, view_values|:"),
    ("for argument in arguments |binders, owned, view_names, view_values|:", "chv_scan_expression_locals(argument, in_region, binders, owned, view_names, view_values)"),
    ("Expr.StaticEffectCall(candidates: candidates, arguments: arguments, _):", "for child in Ast::effect_runtime_children(candidates, arguments) |binders, owned, view_names, view_values|:"),
    ("Expr.Field(object, _, _):", "chv_scan_expression_locals(object, in_region, binders, owned, view_names, view_values)"),
    ("Expr.Scope(base, _, _):", "chv_scan_expression_locals(base, in_region, binders, owned, view_names, view_values)"),
    ("Expr.Index(object, index, _):", "chv_scan_expression_locals(object, in_region, binders, owned, view_names, view_values)"),
    ("Expr.Index(object, index, _):", "chv_scan_expression_locals(index, in_region, binders, owned, view_names, view_values) if not index_receiver_is_type_application(object)"),
    ("Expr.Slice(object, low, high, _):", "chv_scan_expression_locals(low, in_region, binders, owned, view_names, view_values)"),
    ("Expr.Slice(object, low, high, _):", "chv_scan_expression_locals(high, in_region, binders, owned, view_names, view_values)"),
    ("Expr.IndexN(object, arguments, _):", "for argument in arguments |binders, owned, view_names, view_values|:"),
    ("Expr.Binary(left, _, right, _):", "chv_scan_expression_locals(left, in_region, binders, owned, view_names, view_values)"),
    ("Expr.Binary(left, _, right, _):", "chv_scan_expression_locals(right, in_region, binders, owned, view_names, view_values)"),
    ("Expr.Unary(_, operand, _):", "chv_scan_expression_locals(operand, in_region, binders, owned, view_names, view_values)"),
    ("Expr.Move(operand, _):", "chv_scan_expression_locals(operand, in_region, binders, owned, view_names, view_values)"),
    ("Expr.RegionNew(operand, _, _):", "chv_scan_expression_locals(operand, in_region, binders, owned, view_names, view_values)"),
    ("Expr.Paren(inner, _):", "chv_scan_expression_locals(inner, in_region, binders, owned, view_names, view_values)"),
    ("Expr.Array(elements, _):", "for element in elements |binders, owned, view_names, view_values|:"),
    ("Expr.Tuple(elements, _):", "for element in elements |binders, owned, view_names, view_values|:"),
    ("Expr.SetLit(elements, _):", "for element in elements |binders, owned, view_names, view_values|:"),
    ("Expr.DictLit(entries, _):", "for entry in entries |binders, owned, view_names, view_values|:"),
    ("for entry in entries |binders, owned, view_names, view_values|:", "chv_scan_expression_locals(entry.key, in_region, binders, owned, view_names, view_values)"),
    ("for entry in entries |binders, owned, view_names, view_values|:", "chv_scan_expression_locals(entry.value, in_region, binders, owned, view_names, view_values)"),
    ("Expr.Construct(_, fields, _):", "for field in fields |binders, owned, view_names, view_values|:"),
    ("Expr.RecordUpdate(base, fields, _):", "chv_scan_expression_locals(base, in_region, binders, owned, view_names, view_values)"),
    ("Expr.If(condition, then_value, else_value, _):", "chv_scan_expression_locals(condition, in_region, binders, owned, view_names, view_values)"),
    ("Expr.If(condition, then_value, else_value, _):", "chv_scan_expression_locals(then_value, in_region, binders, owned, view_names, view_values)"),
    ("Expr.If(condition, then_value, else_value, _):", "chv_scan_expression_locals(else_value, in_region, binders, owned, view_names, view_values)"),
    ("Expr.Match(scrutinee, arms, _):", "for arm in arms |binders, owned, view_names, view_values|:"),
    ("Expr.Catch(guarded, arms, _):", "for arm in arms |binders, owned, view_names, view_values|:"),
    ("for arm in arms |binders, owned, view_names, view_values|:", "chv_scan_expression_locals(arm.guard, in_region, binders, owned, view_names, view_values)", 0),
    ("for arm in arms |binders, owned, view_names, view_values|:", "chv_scan_expression_locals(arm.guard, in_region, binders, owned, view_names, view_values)", 1),
    ("for arm in arms |binders, owned, view_names, view_values|:", "chv_scan_locals(arm.body, in_region, binders, owned, view_names, view_values)", 0),
    ("for arm in arms |binders, owned, view_names, view_values|:", "chv_scan_locals(arm.body, in_region, binders, owned, view_names, view_values)", 1),
    ("Expr.Comprehension(variable, iterable, condition, body, _, _):", "chv_scan_expression_locals(iterable, in_region, binders, owned, view_names, view_values)"),
    ("Expr.Comprehension(variable, iterable, condition, body, _, _):", "comprehension_binders.push(variable)"),
    ("Expr.Refinement(base, predicate, _):", "chv_scan_expression_locals(base, in_region, binders, owned, view_names, view_values)"),
    ("Expr.Refinement(base, predicate, _):", "chv_scan_expression_locals(predicate, in_region, binders, owned, view_names, view_values)"),
    ("Expr.GetElse(guarded, recovery, _):", "chv_scan_expression_locals(guarded, in_region, binders, owned, view_names, view_values)"),
    ("Expr.GetElse(guarded, recovery, _):", "chv_scan_locals(recovery, in_region, binders, owned, view_names, view_values)"),
    ("Expr.Block(statements, value, _, _):", "chv_scan_locals(statements, in_region, binders, owned, view_names, view_values)"),
    ("Expr.Block(statements, value, _, _):", "chv_scan_expression_locals(value, in_region, binders, owned, view_names, view_values)"),
)

HOLDER_WALK_STATEMENT_EDGES = (
    ("Stmt.Expr(statement_value, _):", "table <- chv_walk_expression(statement_value, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Stmt.VarDecl(declared_name, type_expression, declared_value, _):", "table <- chv_walk_expression(declared_value, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Stmt.Assign(target, operator, assigned_value, assign_pos):", "table <- chv_walk_expression(target, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Stmt.Assign(target, operator, assigned_value, assign_pos):", "if parallel_shape:"),
    ("if parallel_shape:", "for parallel_value in parallel_values |table, parallel_owned_views, parallel_alias_refs, parallel_contained_alias_refs, parallel_scalar_sviews, parallel_yield_scalar_sviews, flow, assigned_value_may_be_owned_view, assigned_value_may_alias_reference, assigned_value_may_contain_alias_reference| -> table:"),
    ("for parallel_value in parallel_values |table, parallel_owned_views, parallel_alias_refs, parallel_contained_alias_refs, parallel_scalar_sviews, parallel_yield_scalar_sviews, flow, assigned_value_may_be_owned_view, assigned_value_may_alias_reference, assigned_value_may_contain_alias_reference| -> table:", "table <- chv_walk_expression(parallel_value, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Stmt.Assign(target, operator, assigned_value, assign_pos):", "else:"),
    ("else:", "table <- chv_walk_expression(assigned_value, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)", 0),
    ("Stmt.Return(value, _):", "table <- chv_walk_expression(return_value, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table) if value is return_value"),
    ("Stmt.If(condition, then_body, else_body, _):", "table <- chv_walk_expression(condition, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Stmt.If(condition, then_body, else_body, _):", "table <- chv_walk_statements(then_body, in_region, ref_params, binders, owned, view_names, view_values, then_flow, summary, table)"),
    ("Stmt.If(condition, then_body, else_body, _):", "table <- chv_walk_statements(else_body, in_region, ref_params, binders, owned, view_names, view_values, else_flow, summary, table)"),
    ("Stmt.While(condition, loop_body, _):", "table <- chv_walk_expression(condition, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Stmt.While(condition, loop_body, _):", "table <- chv_walk_statements(loop_body, in_region, ref_params, binders, owned, view_names, view_values, loop_flow, summary, table)"),
    ("Stmt.For(bind, loop_variables, iterable, loop_body, _):", "table <- chv_walk_expression(iterable, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Stmt.For(bind, loop_variables, iterable, loop_body, _):", "table <- chv_walk_statements(loop_body, in_region, ref_params, binders, owned, view_names, view_values, loop_flow, summary, table)"),
    ("Stmt.Block(kind, _, binding, block_body, _):", "table <- chv_walk_statements(block_body, in_region or kind == \"region\" or kind == \"in\", ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Stmt.Match(scrutinee, arms, _):", "table <- chv_walk_expression(scrutinee, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Stmt.Match(scrutinee, arms, _):", "for arm in arms |table| -> table:"),
    ("for arm in arms |table| -> table:", "table <- chv_walk_expression(arm.guard, in_region, ref_params, binders, owned, view_names, view_values, arm_flow, summary, table)"),
    ("for arm in arms |table| -> table:", "table <- chv_walk_statements(arm.body, in_region, ref_params, binders, owned, view_names, view_values, arm_flow, summary, table)"),
    ("Stmt.Contract(_, expression, _):", "table <- chv_walk_expression(expression, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Stmt.VarDecl(declared_name, type_expression, declared_value, _):", "chv_flow_bind(flow, declared_name, not in_region and (typed_owned or literal_owned), flow.last_value_may_be_owned_view, declared_alias_ref)"),
)

FOR_ITERATOR_VIEW_TAINT_EDGES = (
    ("Stmt.For(bind, loop_variables, iterable, loop_body, _):", "iterable_may_be_owned_view: bool = chv_iterable_element_may_be_owned_view(iterable, flow, view_names, view_values, flow.last_value_may_be_owned_view, 0)"),
    ("for loop_variable_index in 0..<loop_variables.count |loop_flow, loop_variables|:", "loop_variable_may_be_owned_view: bool = element_facts.may_owned_view if element_facts.known else iterable_may_be_owned_view"),
    ("for loop_variable_index in 0..<loop_variables.count |loop_flow, loop_variables|:", "chv_flow_bind(loop_flow, loop_variable, false, loop_variable_may_be_owned_view, loop_variable_may_alias_reference)"),
)

FOR_ITERATOR_REF_ALIAS_EDGES = (
    ("Stmt.For(bind, loop_variables, iterable, loop_body, _):", "iterable_may_alias_reference: bool = chv_expression_may_alias_ref(iterable, ref_params, flow, table, 0)"),
    ("Stmt.For(bind, loop_variables, iterable, loop_body, _):", "loop_element_may_alias_reference: bool = chv_iterable_element_may_alias_reference(iterable, ref_params, flow, table, 0)"),
    ("Stmt.For(bind, loop_variables, iterable, loop_body, _):", "loop_element_may_contain_alias_reference: bool = chv_iterable_element_may_contain_alias_ref(iterable, ref_params, flow, table, 0)"),
    ("Stmt.For(bind, loop_variables, iterable, loop_body, _):", "loop_variable_may_alias_reference: bool = loop_element_may_alias_reference or (bind == \"mutable\" and iterable_may_alias_reference)"),
    ("for loop_variable_index in 0..<loop_variables.count |loop_flow, loop_variables|:", "element_facts: (known: bool, may_owned_view: bool, may_alias_reference: bool, may_contain_alias_reference: bool, may_be_scalar_sview: bool, may_yield_scalar_sview: bool) = chv_iterable_binding_facts(iterable, loop_variable_index, loop_variables.count > 1, ref_params, flow, table, view_names, view_values)"),
    ("for loop_variable_index in 0..<loop_variables.count |loop_flow, loop_variables|:", "loop_variable_may_alias_reference: mutable bool = element_facts.may_alias_reference if element_facts.known else loop_element_may_alias_reference"),
    ("for loop_variable_index in 0..<loop_variables.count |loop_flow, loop_variables|:", "loop_variable_may_alias_reference <- loop_variable_may_alias_reference or (bind == \"mutable\" and iterable_may_alias_reference)"),
    ("for loop_variable_index in 0..<loop_variables.count |loop_flow, loop_variables|:", "chv_flow_bind(loop_flow, loop_variable, false, loop_variable_may_be_owned_view, loop_variable_may_alias_reference)"),
    ("for loop_variable_index in 0..<loop_variables.count |loop_flow, loop_variables|:", "loop_flow.may_contain_alias_reference[loop_index] <- loop_variable_may_contain_alias_reference if loop_index < loop_flow.names.count"),
)

ITERABLE_BINDING_FACTS_ALIAS_EDGES = (
    ("can Memory.Allocate, Abort.Panic:", "known, outer_shape = chv_known_iterable_shape_with_locals(iterable, flow, view_names, view_values, 0)"),
    ("for outer_index in 0..<outer_count |may_owned_view, may_alias_reference, may_contain_alias_reference, may_be_scalar_sview, may_yield_scalar_sview, ref_params, flow, table, view_names, view_values, slot, destructure, outer_shape|:", "element_is_aggregate, nested_shape = chv_known_iterable_shape_with_locals(element, flow, view_names, view_values, 0)"),
    ("for outer_index in 0..<outer_count |may_owned_view, may_alias_reference, may_contain_alias_reference, may_be_scalar_sview, may_yield_scalar_sview, ref_params, flow, table, view_names, view_values, slot, destructure, outer_shape|:", "may_alias_reference <- may_alias_reference or (not element_is_aggregate and chv_expression_may_alias_ref(element, ref_params, flow, table, 0))"),
    ("for outer_index in 0..<outer_count |may_owned_view, may_alias_reference, may_contain_alias_reference, may_be_scalar_sview, may_yield_scalar_sview, ref_params, flow, table, view_names, view_values, slot, destructure, outer_shape|:", "may_contain_alias_reference <- may_contain_alias_reference or chv_expression_may_contain_alias_ref(element, ref_params, flow, table, 0)"),
    ("can Memory.Allocate, Abort.Panic:", "return (true, may_owned_view, may_alias_reference, may_contain_alias_reference, may_be_scalar_sview, may_yield_scalar_sview)"),
)

HOLDER_WALK_EXPRESSION_EDGES = (
    ("Expr.Call(callee, arguments, _, _):", "table <- chv_walk_call_callee(callee, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, receiver_may_be_owned_view, receiver_may_alias_reference, callee_may_be_owned_view, table)"),
    ("Expr.Call(callee, arguments, _, _):", "for argument in arguments |table, argument_may_alias_refs, argument_owned_views, flow, arguments_may_be_owned_view| -> table:"),
    ("for argument in arguments |table, argument_may_alias_refs, argument_owned_views, flow, arguments_may_be_owned_view| -> table:", "argument_owned_views.push(flow.last_value_may_be_owned_view)", 0),
    ("for argument in arguments |table, argument_may_alias_refs, argument_owned_views, flow, arguments_may_be_owned_view| -> table:", "argument_may_alias_refs.push(chv_expression_may_alias_ref(argument, ref_params, flow, table, 0))", 0),
    ("Expr.Call(callee, arguments, _, _):", "table <- chv_check_call(expression, argument_owned_views, argument_may_alias_refs, receiver_may_be_owned_view, receiver_may_alias_reference, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.StaticEffectCall(candidates: candidates, arguments: arguments, argument_names: argument_names, _):", "runtime_children: darray[Ast::Expr] = Ast::effect_runtime_children(candidates, arguments)"),
    ("Expr.StaticEffectCall(candidates: candidates, arguments: arguments, argument_names: argument_names, _):", "for child in runtime_children |table, runtime_owned_views, runtime_may_alias_refs|:"),
    ("for child in runtime_children |table, runtime_owned_views, runtime_may_alias_refs|:", "runtime_owned_views.push(flow.last_value_may_be_owned_view)"),
    ("for child in runtime_children |table, runtime_owned_views, runtime_may_alias_refs|:", "runtime_may_alias_refs.push(chv_expression_may_alias_ref(child, ref_params, flow, table, 0))"),
    ("Expr.StaticEffectCall(candidates: candidates, arguments: arguments, argument_names: argument_names, _):", "table <- chv_check_static_effect_call(candidates, arguments, argument_names, runtime_owned_views, runtime_may_alias_refs, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.Field(object, _, _):", "table <- chv_walk_expression(object, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.Scope(base, _, _):", "table <- chv_walk_expression(base, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.Index(object, index, _):", "table <- chv_walk_expression(object, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.Index(object, index, _):", "if not index_receiver_is_type_application(object):"),
    ("if not index_receiver_is_type_application(object):", "table <- chv_walk_expression(index, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)", 0),
    ("Expr.Slice(object, low, high, _):", "table <- chv_walk_expression(low, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.Slice(object, low, high, _):", "table <- chv_walk_expression(high, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.IndexN(object, arguments, _):", "table <- chv_walk_expression(object, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.IndexN(object, arguments, _):", "if not index_receiver_is_type_application(object):"),
    ("if not index_receiver_is_type_application(object):", "for argument in arguments |table|:", 1),
    ("for argument in arguments |table|:", "table <- chv_walk_expression(argument, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.Binary(left, binary_operator, right, _):", "table <- chv_walk_expression(left, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.Binary(left, binary_operator, right, _):", "binary_rhs_is_runtime_value: bool = not chv_binary_operator_has_non_runtime_target(binary_operator)"),
    ("if binary_operator != TokenKind.And:", "table <- chv_walk_expression(right, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.Binary(left, binary_operator, right, _):", "binary_arguments: darray[Ast::Expr] = [left, right]"),
    ("Expr.Binary(left, binary_operator, right, _):", "binary_owned_views: darray[bool] = [left_may_be_owned_view, right_may_be_owned_view]"),
    ("Expr.Binary(left, binary_operator, right, _):", "binary_alias_refs: darray[bool] = [left_may_alias_ref, right_may_alias_ref]"),
    ("Expr.Binary(left, binary_operator, right, _):", "if binary_rhs_is_runtime_value and binary_operator != TokenKind.And and binary_operator != TokenKind.Or:"),
    ("Expr.Unary(operator, operand, _):", "table <- chv_walk_expression(operand, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.Move(operand, _):", "table <- chv_walk_expression(operand, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.RegionNew(operand, _, _):", "table <- chv_walk_expression(operand, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.Paren(inner, _):", "table <- chv_walk_expression(inner, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.Array(elements, _):", "for element in elements |table, aggregate_may_be_owned_view, flow| -> table:"),
    ("Expr.Tuple(elements, _):", "for element in elements |table, aggregate_may_be_owned_view, flow| -> table:"),
    ("Expr.SetLit(elements, _):", "for element in elements |table, aggregate_may_be_owned_view, flow| -> table:"),
    ("Expr.DictLit(entries, _):", "for entry in entries |table, aggregate_may_be_owned_view, flow| -> table:"),
    ("for entry in entries |table, aggregate_may_be_owned_view, flow| -> table:", "table <- chv_walk_expression(entry.key, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("for entry in entries |table, aggregate_may_be_owned_view, flow| -> table:", "table <- chv_walk_expression(entry.value, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.Construct(_, fields, _):", "for field in fields |table, aggregate_may_be_owned_view, flow| -> table:"),
    ("Expr.RecordUpdate(base, fields, _):", "table <- chv_walk_expression(base, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.If(condition, then_value, else_value, _):", "table <- chv_walk_expression(condition, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.If(condition, then_value, else_value, _):", "table <- chv_walk_expression(then_value, in_region, ref_params, binders, owned, view_names, view_values, then_flow, summary, table)"),
    ("Expr.If(condition, then_value, else_value, _):", "table <- chv_walk_expression(else_value, in_region, ref_params, binders, owned, view_names, view_values, else_flow, summary, table)"),
    ("Expr.Match(scrutinee, arms, _):", "for arm in arms |table, branch_value_may_be_owned, merged_flow, merged_ready| -> table:"),
    ("Expr.Catch(guarded, arms, _):", "table <- chv_walk_expression(guarded, in_region, ref_params, binders, owned, view_names, view_values, guarded_flow, summary, table)"),
    ("Expr.Catch(guarded, arms, _):", "for arm in arms |table, branch_value_may_be_owned, merged_flow, arm_index| -> table:"),
    ("for arm in arms |table, branch_value_may_be_owned, merged_flow, merged_ready| -> table:", "table <- chv_walk_expression(arm.guard, in_region, ref_params, binders, owned, view_names, view_values, arm_flow, summary, table)"),
    ("for arm in arms |table, branch_value_may_be_owned, merged_flow, arm_index| -> table:", "table <- chv_walk_expression(arm.guard, in_region, ref_params, binders, owned, view_names, view_values, arm_flow, summary, table)"),
    ("for arm in arms |table, branch_value_may_be_owned, merged_flow, merged_ready| -> table:", "table <- chv_walk_statements(arm.body, in_region, ref_params, binders, owned, view_names, view_values, arm_flow, summary, table)"),
    ("for arm in arms |table, branch_value_may_be_owned, merged_flow, arm_index| -> table:", "table <- chv_walk_statements(arm.body, in_region, ref_params, binders, owned, view_names, view_values, arm_flow, summary, table)"),
    ("Expr.Comprehension(variable, iterable, condition, body, _, _):", "table <- chv_walk_expression(iterable, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.Comprehension(variable, iterable, condition, body, _, _):", "for outer_ref in ref_params |comprehension_ref_params|:"),
    ("for outer_ref in ref_params |comprehension_ref_params|:", "comprehension_ref_params.push(outer_ref) if outer_ref != variable"),
    ("Expr.Comprehension(variable, iterable, condition, body, _, _):", "comprehension_binders.push(variable)"),
    ("Expr.Comprehension(variable, iterable, condition, body, _, _):", "table <- chv_walk_expression(condition, in_region, comprehension_ref_params, comprehension_binders, comprehension_owned, comprehension_view_names, comprehension_view_values, comprehension_flow, summary, table)"),
    ("Expr.Comprehension(variable, iterable, condition, body, _, _):", "chv_flow_bind_truthy_condition_binders(condition, comprehension_ref_params, comprehension_flow, table)"),
    ("Expr.Comprehension(variable, iterable, condition, body, _, _):", "table <- chv_walk_expression(body, in_region, comprehension_ref_params, comprehension_binders, comprehension_owned, comprehension_view_names, comprehension_view_values, comprehension_flow, summary, table)"),
    ("Expr.Refinement(base, predicate, _):", "table <- chv_walk_expression(base, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.Refinement(base, predicate, _):", "table <- chv_walk_expression(predicate, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.GetElse(guarded, recovery, _):", "table <- chv_walk_expression(guarded, in_region, ref_params, binders, owned, view_names, view_values, guarded_flow, summary, table)"),
    ("Expr.GetElse(guarded, recovery, _):", "table <- chv_walk_statements(recovery, in_region, ref_params, binders, owned, view_names, view_values, recovery_flow, summary, table)"),
    ("Expr.Lambda(parameters, body, _):", "for outer_ref in ref_params |lambda_ref_params, parameters|:"),
    ("Expr.Lambda(parameters, body, _):", "table <- chv_walk_statements(body, in_region, lambda_ref_params, lambda_binders, lambda_owned, lambda_view_names, lambda_view_values, lambda_flow, summary, table)"),
    ("Expr.Block(block_statements, block_value, _, _):", "table <- chv_walk_statements(block_statements, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.Block(block_statements, block_value, _, _):", "table <- chv_walk_expression(block_value, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
)

CATCH_ARM_PROVENANCE_EDGES = (
    ("for arm in arms |table, branch_value_may_be_owned, merged_flow, arm_index| -> table:",
     "is_success_arm: bool = arm_index == 0"),
    ("for arm in arms |table, branch_value_may_be_owned, merged_flow, arm_index| -> table:",
     "chv_flow_bind_pattern(arm.pattern, true, guarded_flow.last_value_may_be_owned_view if is_success_arm else true, guarded_may_alias_reference if is_success_arm else true, arm_flow)"),
)

EXPRESSION_BINDING_FACTS_OR_EDGES = (
    ("Expr.Binary(left, operator, right, _):", "if operator == TokenKind.Or:"),
    ("if operator == TokenKind.Or:",
     "return (left_facts.found and right_facts.found, left_facts.may_owned_view or right_facts.may_owned_view, left_facts.may_alias_reference or right_facts.may_alias_reference)"),
)

PARALLEL_ASSIGNMENT_FLOW_EDGES = (
    ("Stmt.Assign(target, operator, assigned_value, assign_pos):", "parallel_values_found, parallel_values = chv_parallel_value_elements(assigned_value)"),
    ("if parallel_shape:", "for parallel_value in parallel_values |table, parallel_owned_views, parallel_alias_refs, parallel_contained_alias_refs, parallel_scalar_sviews, parallel_yield_scalar_sviews, flow, assigned_value_may_be_owned_view, assigned_value_may_alias_reference, assigned_value_may_contain_alias_reference| -> table:"),
    ("for parallel_value in parallel_values |table, parallel_owned_views, parallel_alias_refs, parallel_contained_alias_refs, parallel_scalar_sviews, parallel_yield_scalar_sviews, flow, assigned_value_may_be_owned_view, assigned_value_may_alias_reference, assigned_value_may_contain_alias_reference| -> table:", "table <- chv_walk_expression(parallel_value, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("for parallel_value in parallel_values |table, parallel_owned_views, parallel_alias_refs, parallel_contained_alias_refs, parallel_scalar_sviews, parallel_yield_scalar_sviews, flow, assigned_value_may_be_owned_view, assigned_value_may_alias_reference, assigned_value_may_contain_alias_reference| -> table:", "parallel_owned_views.push(value_may_be_owned_view)"),
    ("for parallel_value in parallel_values |table, parallel_owned_views, parallel_alias_refs, parallel_contained_alias_refs, parallel_scalar_sviews, parallel_yield_scalar_sviews, flow, assigned_value_may_be_owned_view, assigned_value_may_alias_reference, assigned_value_may_contain_alias_reference| -> table:", "parallel_alias_refs.push(value_may_alias_reference)"),
    ("elif target is Expr.Array(target_elements, _):", "for target_index in 0..<target_elements.count |flow, operator, assigned_value_may_be_owned_view, assigned_value_may_alias_reference, assigned_value_may_contain_alias_reference, assigned_value_may_be_scalar_sview, assigned_value_may_yield_scalar_sview, parallel_shape, parallel_owned_views, parallel_alias_refs, parallel_contained_alias_refs, parallel_scalar_sviews, parallel_yield_scalar_sviews, target_elements|:"),
    ("for target_index in 0..<target_elements.count |flow, operator, assigned_value_may_be_owned_view, assigned_value_may_alias_reference, assigned_value_may_contain_alias_reference, assigned_value_may_be_scalar_sview, assigned_value_may_yield_scalar_sview, parallel_shape, parallel_owned_views, parallel_alias_refs, parallel_contained_alias_refs, parallel_scalar_sviews, parallel_yield_scalar_sviews, target_elements|:", "if target_elements[target_index] is Expr.Ident(target_name, _):"),
    ("if target_elements[target_index] is Expr.Ident(target_name, _):", "element_may_be_owned_view: bool = parallel_owned_views[target_index] if parallel_shape else assigned_value_may_be_owned_view"),
    ("if target_elements[target_index] is Expr.Ident(target_name, _):", "element_may_alias_reference: bool = parallel_alias_refs[target_index] if parallel_shape else assigned_value_may_alias_reference"),
    ("if target_elements[target_index] is Expr.Ident(target_name, _):", "element_may_contain_alias_reference: bool = parallel_contained_alias_refs[target_index] if parallel_shape else assigned_value_may_contain_alias_reference"),
    ("if target_elements[target_index] is Expr.Ident(target_name, _):", "element_may_be_scalar_sview: bool = parallel_scalar_sviews[target_index] if parallel_shape else assigned_value_may_be_scalar_sview"),
    ("if target_elements[target_index] is Expr.Ident(target_name, _):", "element_may_yield_scalar_sview: bool = parallel_yield_scalar_sviews[target_index] if parallel_shape else assigned_value_may_yield_scalar_sview"),
    ("if target_elements[target_index] is Expr.Ident(target_name, _):", "target_alias: bool = element_may_be_owned_view or (operator != TokenKind.Assign and previous_target_may_be_owned_view)"),
    ("if operator == TokenKind.Assign and not target_is_rebind_claim:", "chv_flow_bind(flow, target_name, false, target_alias, target_alias_ref)"),
)

BINARY_AND_RIGHT_WALK_EDGE = (
    "if binary_operator == TokenKind.And:",
    "table <- chv_walk_expression(right, in_region, ref_params, binders, owned, view_names, view_values, right_flow, summary, table)",
)

BINARY_RIGHT_VIEW_EDGES = (
    ("if binary_operator == TokenKind.And:", "right_may_be_owned_view <- right_flow.last_value_may_be_owned_view"),
    ("if binary_operator != TokenKind.And:", "right_may_be_owned_view <- flow.last_value_may_be_owned_view"),
)

BINARY_OPERATOR_FALLBACK_EDGES = (
    ("Expr.Binary(left, binary_operator, right, _):", "binary_arguments: darray[Ast::Expr] = [left, right]"),
    ("Expr.Binary(left, binary_operator, right, _):", "binary_owned_views: darray[bool] = [left_may_be_owned_view, right_may_be_owned_view]"),
    ("Expr.Binary(left, binary_operator, right, _):", "binary_alias_refs: darray[bool] = [left_may_alias_ref, right_may_alias_ref]"),
    ("Expr.Binary(left, binary_operator, right, _):", "if binary_rhs_is_runtime_value and binary_operator != TokenKind.And and binary_operator != TokenKind.Or:"),
    ("if binary_rhs_is_runtime_value and binary_operator != TokenKind.And and binary_operator != TokenKind.Or:", "table <- chv_check_unknown_call(binary_arguments, binary_owned_views, binary_alias_refs, ref_params, binders, owned, view_names, view_values, flow, table)"),
)

BINARY_NON_RUNTIME_TARGET_EDGES = (
    ("can Abort.Panic:", "return operator == TokenKind.Is or operator == TokenKind.As"),
    ("Expr.Binary(left, binary_operator, right, _):", "binary_rhs_is_runtime_value: bool = not chv_binary_operator_has_non_runtime_target(binary_operator)"),
)

CONSTRUCT_VIEW_TAINT_EDGES = (
    ("Expr.Construct(_, fields, _):", "for field in fields |table, aggregate_may_be_owned_view, flow| -> table:"),
    ("for field in fields |table, aggregate_may_be_owned_view, flow| -> table:", "table <- chv_walk_expression(field.value, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("for field in fields |table, aggregate_may_be_owned_view, flow| -> table:", "aggregate_may_be_owned_view <- aggregate_may_be_owned_view or flow.last_value_may_be_owned_view"),
    ("Expr.Construct(_, fields, _):", "flow.last_value_may_be_owned_view <- aggregate_may_be_owned_view"),
)

RECORD_UPDATE_VIEW_TAINT_EDGES = (
    ("Expr.RecordUpdate(base, fields, _):", "table <- chv_walk_expression(base, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.RecordUpdate(base, fields, _):", "aggregate_may_be_owned_view: mutable bool = flow.last_value_may_be_owned_view"),
    ("Expr.RecordUpdate(base, fields, _):", "for field in fields |table, aggregate_may_be_owned_view, flow| -> table:"),
    ("for field in fields |table, aggregate_may_be_owned_view, flow| -> table:", "table <- chv_walk_expression(field.value, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("for field in fields |table, aggregate_may_be_owned_view, flow| -> table:", "aggregate_may_be_owned_view <- aggregate_may_be_owned_view or flow.last_value_may_be_owned_view"),
    ("Expr.RecordUpdate(base, fields, _):", "flow.last_value_may_be_owned_view <- aggregate_may_be_owned_view"),
)

FIELD_PROJECTION_VIEW_TAINT_EDGES = (
    ("Expr.Field(_, _, _):", "root_name: sview = chv_place_root(argument)"),
    ("Expr.Field(_, _, _):", "index: usize = chv_flow_latest(flow, root_name) if root_name != \"\" else flow.names.count"),
    ("Expr.Field(_, _, _):", "return index < flow.names.count and flow.may_owned_view[index]"),
)

ARRAY_VIEW_TAINT_EDGES = (
    ("Expr.Array(elements, _):", "for element in elements |table, aggregate_may_be_owned_view, flow| -> table:"),
    ("for element in elements |table, aggregate_may_be_owned_view, flow| -> table:", "table <- chv_walk_expression(element, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("for element in elements |table, aggregate_may_be_owned_view, flow| -> table:", "aggregate_may_be_owned_view <- aggregate_may_be_owned_view or flow.last_value_may_be_owned_view"),
    ("Expr.Array(elements, _):", "flow.last_value_may_be_owned_view <- aggregate_may_be_owned_view"),
    ("Expr.Tuple(elements, _):", "for element in elements |table, aggregate_may_be_owned_view, flow| -> table:"),
    ("for element in elements |table, aggregate_may_be_owned_view, flow| -> table:", "table <- chv_walk_expression(element, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)", 1),
    ("for element in elements |table, aggregate_may_be_owned_view, flow| -> table:", "aggregate_may_be_owned_view <- aggregate_may_be_owned_view or flow.last_value_may_be_owned_view", 1),
    ("Expr.Tuple(elements, _):", "flow.last_value_may_be_owned_view <- aggregate_may_be_owned_view"),
    ("Expr.SetLit(elements, _):", "for element in elements |table, aggregate_may_be_owned_view, flow| -> table:"),
    ("for element in elements |table, aggregate_may_be_owned_view, flow| -> table:", "table <- chv_walk_expression(element, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)", 2),
    ("for element in elements |table, aggregate_may_be_owned_view, flow| -> table:", "aggregate_may_be_owned_view <- aggregate_may_be_owned_view or flow.last_value_may_be_owned_view", 2),
    ("Expr.SetLit(elements, _):", "flow.last_value_may_be_owned_view <- aggregate_may_be_owned_view"),
)

DICT_VIEW_TAINT_EDGES = (
    ("Expr.DictLit(entries, _):", "for entry in entries |table, aggregate_may_be_owned_view, flow| -> table:"),
    ("for entry in entries |table, aggregate_may_be_owned_view, flow| -> table:", "table <- chv_walk_expression(entry.key, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("for entry in entries |table, aggregate_may_be_owned_view, flow| -> table:", "key_may_be_owned_view: bool = flow.last_value_may_be_owned_view"),
    ("for entry in entries |table, aggregate_may_be_owned_view, flow| -> table:", "table <- chv_walk_expression(entry.value, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("for entry in entries |table, aggregate_may_be_owned_view, flow| -> table:", "aggregate_may_be_owned_view <- aggregate_may_be_owned_view or key_may_be_owned_view or flow.last_value_may_be_owned_view"),
    ("Expr.DictLit(entries, _):", "flow.last_value_may_be_owned_view <- aggregate_may_be_owned_view"),
)

COMPREHENSION_VIEW_TAINT_EDGES = (
    ("Expr.Comprehension(variable, iterable, condition, body, _, _):", "table <- chv_walk_expression(body, in_region, comprehension_ref_params, comprehension_binders, comprehension_owned, comprehension_view_names, comprehension_view_values, comprehension_flow, summary, table)"),
    ("Expr.Comprehension(variable, iterable, condition, body, _, _):", "body_may_be_owned_view: bool = comprehension_flow.last_value_may_be_owned_view"),
    ("Expr.Comprehension(variable, iterable, condition, body, _, _):", "flow.last_value_may_be_owned_view <- body_may_be_owned_view"),
)

COMPREHENSION_BINDER_VIEW_TAINT_EDGES = (
    ("Expr.Comprehension(variable, iterable, condition, body, _, _):", "table <- chv_walk_expression(iterable, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.Comprehension(variable, iterable, condition, body, _, _):", "iterable_may_yield_owned_view: bool = element_facts.may_owned_view if element_facts.known else chv_iterable_element_may_be_owned_view(iterable, flow, view_names, view_values, flow.last_value_may_be_owned_view, 0)"),
    ("Expr.Comprehension(variable, iterable, condition, body, _, _):", "chv_flow_bind(comprehension_flow, variable, false, iterable_may_yield_owned_view, iterable_may_yield_alias_reference)"),
    ("Expr.Comprehension(variable, iterable, condition, body, _, _):", "table <- chv_walk_expression(body, in_region, comprehension_ref_params, comprehension_binders, comprehension_owned, comprehension_view_names, comprehension_view_values, comprehension_flow, summary, table)"),
    ("Expr.Comprehension(variable, iterable, condition, body, _, _):", "body_may_be_owned_view: bool = comprehension_flow.last_value_may_be_owned_view"),
    ("Expr.Comprehension(variable, iterable, condition, body, _, _):", "flow.last_value_may_be_owned_view <- body_may_be_owned_view"),
)

IDENTIFIER_VIEW_TAINT_EDGES = (
    ("Expr.Ident(bound_name, _):", "index: usize = chv_flow_latest(flow, bound_name)"),
    ("Expr.Ident(bound_name, _):", "return index < flow.names.count and flow.may_owned_view[index]"),
)

METHOD_CALL_VIEW_RESULT_EDGES = (
    ("Expr.Call(Expr.Field(receiver, _, _), call_arguments, _, _):", "receiver_root: sview = chv_place_root(receiver)"),
    ("Expr.Call(Expr.Field(receiver, _, _), call_arguments, _, _):", "receiver_index: usize = chv_flow_latest(flow, receiver_root) if receiver_root != \"\" else flow.names.count"),
    ("Expr.Call(Expr.Field(receiver, _, _), call_arguments, _, _):", "receiver_may_be_owned: bool = chv_is_owned_view(receiver, flow, depth + 1) or (receiver_index < flow.names.count and (flow.owned[receiver_index] or flow.may_owned_view[receiver_index]))"),
    ("Expr.Call(Expr.Field(receiver, _, _), call_arguments, _, _):", "arguments_may_be_owned: bool = any call_argument in call_arguments where chv_is_owned_view(call_argument, flow, depth + 1)"),
    ("Expr.Call(Expr.Field(receiver, _, _), call_arguments, _, _):", "return receiver_may_be_owned or arguments_may_be_owned"),
)

CALLABLE_VIEW_RESULT_EDGES = (
    ("Expr.Call(arguments: call_arguments, _):", "return any call_argument in call_arguments where chv_is_owned_view(call_argument, flow, depth + 1)"),
)

CALL_RESULT_VIEW_TAINT_EDGES = (
    ("Expr.Call(callee, arguments, _, _):", "result_may_be_owned_view: mutable bool = chv_is_owned_view(expression, flow, 0)"),
    ("for argument in arguments |table, argument_may_alias_refs, argument_owned_views, flow, arguments_may_be_owned_view| -> table:", "arguments_may_be_owned_view <- arguments_may_be_owned_view or flow.last_value_may_be_owned_view"),
    ("Expr.Call(callee, arguments, _, _):", "flow.last_value_may_be_owned_view <- result_may_be_owned_view or arguments_may_be_owned_view"),
)

CALL_RESULT_CALLEE_JOIN_EDGE = (
    "Expr.Call(callee, arguments, _, _):",
    "result_may_be_owned_view <- chv_is_owned_view(expression, flow, 0) or (method_found and receiver_may_be_owned_view and (method_name == \"as_sview\" or method_name == \"as_cstr\" or method_name == \"view\")) or callee_may_be_owned_view",
)

CALL_CALLEE_INDEXED_VIEW_EDGES = (
    ("match callee:", "Expr.Index(head, index, _):"),
    ("Expr.Index(head, index, _):", "table <- chv_walk_call_callee(head, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, receiver_owned_view, receiver_may_alias_reference, callee_may_be_owned_view, table)"),
    ("Expr.Index(head, index, _):", "head_may_be_owned_view: bool = callee_may_be_owned_view or chv_is_owned_view(head, flow, 0)"),
    ("Expr.Index(head, index, _):", "index_may_be_owned_view: mutable bool = false"),
    ("Expr.Index(head, index, _):", "if not index_receiver_is_type_application(head):"),
    ("if not index_receiver_is_type_application(head):", "table <- chv_walk_expression(index, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("if not index_receiver_is_type_application(head):", "index_may_be_owned_view <- flow.last_value_may_be_owned_view"),
    ("if not index_receiver_is_type_application(head):", "indexed_arguments: darray[Ast::Expr] = [head, index]"),
    ("if not index_receiver_is_type_application(head):", "indexed_owned_views: darray[bool] = [head_may_be_owned_view, index_may_be_owned_view]"),
    ("if not index_receiver_is_type_application(head):", "indexed_alias_refs: darray[bool] = [chv_expression_may_alias_ref(head, ref_params, flow, table, 0), chv_expression_may_alias_ref(index, ref_params, flow, table, 0)]"),
    ("if not index_receiver_is_type_application(head):", "table <- chv_check_unknown_call(indexed_arguments, indexed_owned_views, indexed_alias_refs, ref_params, binders, owned, view_names, view_values, flow, table)"),
    ("Expr.Index(head, index, _):", "callee_may_be_owned_view <- head_may_be_owned_view or index_may_be_owned_view"),
    ("match callee:", "Expr.IndexN(head, arguments, _):"),
    ("Expr.IndexN(head, arguments, _):", "table <- chv_walk_call_callee(head, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, receiver_owned_view, receiver_may_alias_reference, callee_may_be_owned_view, table)"),
    ("Expr.IndexN(head, arguments, _):", "head_may_be_owned_view: bool = callee_may_be_owned_view or chv_is_owned_view(head, flow, 0)"),
    ("Expr.IndexN(head, arguments, _):", "# In call position IndexN is explicit generic application. Its"),
    ("Expr.IndexN(head, arguments, _):", "# bracket arguments are type/shape inputs and never runtime values."),
    ("Expr.IndexN(head, arguments, _):", "callee_may_be_owned_view <- head_may_be_owned_view"),
    ("Expr.IndexN(head, arguments, _):", "flow.last_value_may_be_owned_view <- callee_may_be_owned_view"),
)

STATIC_EFFECT_RESULT_VIEW_TAINT_EDGES = (
    ("Expr.StaticEffectCall(candidates: candidates, arguments: arguments, argument_names: argument_names, _):", "runtime_children: darray[Ast::Expr] = Ast::effect_runtime_children(candidates, arguments)"),
    ("for child in runtime_children |table, runtime_owned_views, runtime_may_alias_refs|:", "runtime_may_be_owned_view <- runtime_may_be_owned_view or flow.last_value_may_be_owned_view"),
    ("Expr.StaticEffectCall(candidates: candidates, arguments: arguments, argument_names: argument_names, _):", "flow.last_value_may_be_owned_view <- runtime_may_be_owned_view"),
)

ASSIGN_VIEW_TAINT_EDGES = (
    ("Stmt.Assign(target, operator, assigned_value, assign_pos):", "assigned_root: sview = chv_place_root(target)"),
    ("Stmt.Assign(target, operator, assigned_value, assign_pos):", "projection_assignment: bool = assigned_name == \"\" and assigned_root != \"\""),
    ("Stmt.Assign(target, operator, assigned_value, assign_pos):", "previous_index: usize = chv_flow_latest(flow, assigned_root) if assigned_root != \"\" else flow.names.count"),
    ("Stmt.Assign(target, operator, assigned_value, assign_pos):", "previous_may_owned_view <- flow.may_owned_view[previous_index] if previous_index < flow.names.count"),
    ("else:", "table <- chv_walk_expression(assigned_value, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)", 0),
    ("else:", "assigned_value_may_be_owned_view <- flow.last_value_may_be_owned_view", 0),
    ("for parallel_value in parallel_values |table, parallel_owned_views, parallel_alias_refs, parallel_contained_alias_refs, parallel_scalar_sviews, parallel_yield_scalar_sviews, flow, assigned_value_may_be_owned_view, assigned_value_may_alias_reference, assigned_value_may_contain_alias_reference| -> table:", "value_may_be_owned_view: bool = flow.last_value_may_be_owned_view"),
    ("for parallel_value in parallel_values |table, parallel_owned_views, parallel_alias_refs, parallel_contained_alias_refs, parallel_scalar_sviews, parallel_yield_scalar_sviews, flow, assigned_value_may_be_owned_view, assigned_value_may_alias_reference, assigned_value_may_contain_alias_reference| -> table:", "assigned_value_may_be_owned_view <- assigned_value_may_be_owned_view or value_may_be_owned_view"),
    ("Stmt.Assign(target, operator, assigned_value, assign_pos):", "table <- chv_walk_expression(target, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Stmt.Assign(target, operator, assigned_value, assign_pos):", "assigned_alias: bool = assigned_value_may_be_owned_view or ((operator != TokenKind.Assign or projection_assignment) and previous_may_owned_view)"),
    ("Stmt.Assign(target, operator, assigned_value, assign_pos):", "if assigned_root != \"\":"),
    ("if assigned_root != \"\":", "elif assigned_index < flow.names.count:"),
    ("elif assigned_index < flow.names.count:", "flow.may_owned_view[assigned_index] <- assigned_alias"),
)

PLACE_ROOT_PROJECTION_EDGES = (
    ("Expr.Field(object, _, _):", "return chv_place_root(object)"),
    ("Expr.Index(object, _, _):", "return chv_place_root(object)"),
    ("Expr.IndexN(object, _, _):", "return chv_place_root(object)"),
    ("Expr.Slice(object: object, _):", "return chv_place_root(object)"),
)

EFFECT_CANDIDATE_EDGES = (
    ("for candidate in candidates |table, flow, candidate_capture_offset| -> table:", "candidate_arguments.extend(candidate.captures)"),
    ("for candidate in candidates |table, flow, candidate_capture_offset| -> table:", "candidate_arguments.extend(arguments)"),
    ("for candidate in candidates |table, flow, candidate_capture_offset| -> table:", "chv_check_call_target(candidate.callee, candidate_arguments, candidate_owned_views, candidate_may_alias_refs, ref_params, binders, owned, view_names, view_values, flow, summary, table) if not chv_call_has_named_arguments(argument_names)"),
)

VIEW_FLOW_MERGE_EDGES = (
    ("while index < visible_count and index < target.names.count and index < left.names.count and index < right.names.count |index, target, left, right|:", "target.may_owned_view[index] <- left.may_owned_view[index] or right.may_owned_view[index]"),
)

REF_ALIAS_FLOW_MERGE_EDGES = (
    ("while index < visible_count and index < target.names.count and index < left.names.count and index < right.names.count |index, target, left, right|:", "target.may_alias_reference[index] <- left.may_alias_reference[index] or right.may_alias_reference[index]"),
)

REF_ALIAS_HELPER_EDGES = (
    ("_:", "if index < flow.names.count:"),
    ("if index < flow.names.count:", "return flow.may_alias_reference[index] or flow.may_contain_alias_reference[index]"),
    ("_:", "return any reference_parameter in ref_params where reference_parameter == root"),
    ("Expr.Call(_, _, _, _):", "return ref_params.count > 0"),
    ("Expr.Binary(left, binary_operator, right, _):", "return chv_expression_may_alias_ref(left, ref_params, flow, table, depth + 1) or chv_expression_may_alias_ref(right, ref_params, flow, table, depth + 1)"),
    ("Expr.Field(_, _, _) | Expr.Index(_, _, _) | Expr.IndexN(_, _, _) | Expr.Slice(_, _, _, _) | Expr.Block(_, _, _, _) | Expr.GetElse(_, _, _) | Expr.Match(_, _, _) | Expr.Catch(_, _, _) | Expr.StaticEffectCall(_, _, _, _, _, _):", "return ref_params.count > 0"),
    ("Expr.Binary(left, binary_operator, right, _):", "return false if chv_binary_operator_returns_bool(binary_operator, right)"),
    ("Expr.Unary(operator, operand, _):", "return false if operator == TokenKind.Not"),
    ("Expr.Tuple(elements, _) | Expr.Array(elements, _) | Expr.SetLit(elements, _):", "return any element in elements where chv_expression_may_alias_ref(element, ref_params, flow, table, depth + 1)"),
    ("Expr.DictLit(entries, _):", "return any entry in entries where chv_expression_may_alias_ref(entry.key, ref_params, flow, table, depth + 1) or chv_expression_may_alias_ref(entry.value, ref_params, flow, table, depth + 1)"),
    ("Expr.Construct(_, fields, _):", "return any field in fields where chv_expression_may_alias_ref(field.value, ref_params, flow, table, depth + 1)"),
    ("Expr.RecordUpdate(base, fields, _):", "return chv_expression_may_alias_ref(base, ref_params, flow, table, depth + 1) or any field in fields where chv_expression_may_alias_ref(field.value, ref_params, flow, table, depth + 1)"),
)

COMPREHENSION_REF_ALIAS_EDGES = (
    ("Expr.Comprehension(variable, iterable, condition, body, _, _):", "iterable_may_yield_alias_reference: bool = chv_iterable_element_may_alias_reference(iterable, ref_params, flow, table, depth + 1)"),
    ("Expr.Comprehension(variable, iterable, condition, body, _, _):", "chv_flow_bind(comprehension_flow, variable, false, false, iterable_may_yield_alias_reference)"),
    ("Expr.Comprehension(variable, iterable, condition, body, _, _):", "chv_flow_bind_truthy_condition_binders(condition, comprehension_ref_params, comprehension_flow, table)"),
    ("Expr.Comprehension(variable, iterable, condition, body, _, _):", "return chv_expression_may_alias_ref(body, comprehension_ref_params, comprehension_flow, table, depth + 1)"),
)

COMPREHENSION_CONTAIN_ALIAS_EDGES = (
    ("can Memory.Allocate, Abort.Panic:", "return false if chv_flow_iterable_is_scalar_sview(expression, flow, depth + 1)"),
    ("if known_elements:", "return any element in elements where chv_expression_may_alias_ref(element, ref_params, flow, table, depth + 1)"),
    ("match expression:", "Expr.If(condition, then_value, else_value, _):"),
    ("Expr.If(condition, then_value, else_value, _):", "chv_flow_bind_truthy_condition_binders(condition, ref_params, then_flow, table)"),
    ("Expr.If(condition, then_value, else_value, _):", "return chv_expression_may_contain_alias_ref(then_value, ref_params, then_flow, table, depth + 1) or chv_expression_may_contain_alias_ref(else_value, ref_params, flow, table, depth + 1)"),
    ("Expr.Ident(name, _):", "if index < flow.names.count:"),
    ("if index < flow.names.count:", "return flow.may_contain_alias_reference[index] or flow.may_alias_reference[index]"),
    ("Expr.Ident(name, _):", "return any reference_parameter in ref_params where reference_parameter == name"),
)

ITERABLE_REF_ALIAS_EDGES = (
    ("if known_elements:", "for element in elements |may_yield_alias_reference|:"),
    ("for element in elements |may_yield_alias_reference|:", "element_is_aggregate, nested_elements = chv_known_iterable_elements(element)"),
    ("for element in elements |may_yield_alias_reference|:", "may_yield_alias_reference <- may_yield_alias_reference or (not element_is_aggregate and chv_expression_may_alias_ref(element, ref_params, flow, table, depth + 1))"),
    ("if known_elements:", "return may_yield_alias_reference"),
    ("can Memory.Allocate, Abort.Panic:", "return false if chv_flow_iterable_is_scalar_sview(iterable, flow, depth + 1)"),
    ("can Memory.Allocate, Abort.Panic:", "return chv_iterable_element_may_contain_alias_ref(iterable, ref_params, flow, table, depth + 1)"),
)

ITERABLE_CONTAIN_ALIAS_EDGES = (
    ("can Memory.Allocate, Abort.Panic:", "return false if chv_flow_iterable_is_scalar_sview(iterable, flow, depth + 1)"),
    ("if known_elements:", "return any element in elements where chv_expression_may_contain_alias_ref(element, ref_params, flow, table, depth + 1)"),
    ("match iterable:", "Expr.Ident(name, _):"),
    ("match iterable:", "Expr.Paren(inner, _) | Expr.Move(inner, _):"),
    ("Expr.Paren(inner, _) | Expr.Move(inner, _):", "return chv_iterable_element_may_contain_alias_ref(inner, ref_params, flow, table, depth + 1)"),
    ("match iterable:", "Expr.If(condition, then_value, else_value, _):"),
    ("Expr.If(condition, then_value, else_value, _):", "then_flow: mutable CHVViewFlow = chv_flow_clone(flow)"),
    ("Expr.If(condition, then_value, else_value, _):", "chv_flow_bind_truthy_condition_binders(condition, ref_params, then_flow, table)"),
    ("Expr.If(condition, then_value, else_value, _):", "return chv_iterable_element_may_contain_alias_ref(then_value, ref_params, then_flow, table, depth + 1) or chv_iterable_element_may_contain_alias_ref(else_value, ref_params, flow, table, depth + 1)"),
    ("Expr.Ident(name, _):", "index: usize = chv_flow_latest(flow, name)"),
    ("Expr.Ident(name, _):", "if index < flow.names.count:"),
    ("if index < flow.names.count:", "return flow.may_contain_alias_reference[index]"),
    ("can Memory.Allocate, Abort.Panic:", "return chv_expression_may_contain_alias_ref(iterable, ref_params, flow, table, depth + 1)"),
)

GETELSE_RECOVERY_TERMINATION_EDGES = (
    ("Expr.GetElse(guarded, recovery, _):", "recovery_terminates: bool = statements_terminate(recovery, table)"),
    ("Expr.GetElse(guarded, recovery, _):", "branch_value_may_be_owned <- branch_value_may_be_owned or recovery_flow.last_value_may_be_owned_view if not recovery_terminates"),
    ("Expr.GetElse(guarded, recovery, _):", "chv_flow_set_merge(flow, guarded_flow, recovery_flow, branch_mark) if not recovery_terminates"),
    ("Expr.GetElse(guarded, recovery, _):", "chv_flow_set_merge(flow, guarded_flow, guarded_flow, branch_mark) if recovery_terminates"),
)

SCALAR_SVIEW_FLOW_EDGES = (
    ("Expr.Ident(name, _):", "index: usize = chv_flow_latest(flow, name)"),
    ("Expr.Ident(name, _):", "if index < flow.names.count:"),
    ("if index < flow.names.count:", "return flow.may_be_scalar_sview[index]"),
    ("Expr.Ident(name, _):", "return chv_iterable_is_scalar_sview(expression, view_names, view_values, depth + 1)"),
)

VIEW_ALIAS_BINARY_EDGES = (
    ("Expr.Binary(left, binary_operator, right, _):", "return chv_is_owned_view(left, flow, depth + 1) or chv_is_owned_view(right, flow, depth + 1)"),
    ("Expr.Binary(left, binary_operator, right, _):", "return false if chv_binary_operator_returns_bool(binary_operator, right)"),
)

INDEX_OPERATOR_EDGES = (
    ("Expr.Index(object, index, _):", "table <- chv_walk_expression(object, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.Index(object, index, _):", "if not index_receiver_is_type_application(object):"),
    ("if not index_receiver_is_type_application(object):", "table <- chv_walk_expression(index, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)", 0),
    ("if not index_receiver_is_type_application(object):", "indexed_arguments: darray[Ast::Expr] = [object, index]", 0),
    ("if not index_receiver_is_type_application(object):", "indexed_owned_views: darray[bool] = [object_may_be_owned_view, index_may_be_owned_view]", 0),
    ("if not index_receiver_is_type_application(object):", "indexed_alias_refs: darray[bool] = [object_may_alias_ref, index_may_alias_ref]", 0),
    ("if not index_receiver_is_type_application(object):", "table <- chv_check_unknown_call(indexed_arguments, indexed_owned_views, indexed_alias_refs, ref_params, binders, owned, view_names, view_values, flow, table)", 0),
    ("Expr.IndexN(object, arguments, _):", "table <- chv_walk_expression(object, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.IndexN(object, arguments, _):", "if not index_receiver_is_type_application(object):"),
    ("if not index_receiver_is_type_application(object):", "for argument in arguments |table|:", 1),
    ("for argument in arguments |table|:", "table <- chv_walk_expression(argument, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
)

INDEX_VIEW_RESULT_EDGES = (
    ("Expr.Index(object, index, _):", "index_may_be_owned_view: mutable bool = false"),
    ("Expr.Index(object, index, _):", "if not index_receiver_is_type_application(object):"),
    ("if not index_receiver_is_type_application(object):", "index_may_be_owned_view <- chv_is_owned_view(index, flow, depth + 1)"),
    ("Expr.Index(object, index, _):", "return chv_is_owned_view(object, flow, depth + 1) or index_may_be_owned_view"),
)

INDEXN_VIEW_RESULT_EDGES = (
    ("Expr.IndexN(object, arguments, _):", "# IndexN represents multi-index selection or generic application. Unlike"),
    ("Expr.IndexN(object, arguments, _):", "# single-key Index, it does not lower through the __index__ protocol, so"),
    ("Expr.IndexN(object, arguments, _):", "# selector/type arguments cannot become the returned view's storage."),
    ("Expr.IndexN(object, arguments, _):", "return chv_is_owned_view(object, flow, depth + 1)"),
)

INDEXN_VIEW_WALK_EDGES = (
    ("Expr.IndexN(object, arguments, _):", "flow.last_value_may_be_owned_view <- object_may_be_owned_view or chv_is_owned_view(expression, flow, 0)"),
)

UNARY_NEGATION_EDGES = (
    ("Expr.Unary(operator, operand, _):", "table <- chv_walk_expression(operand, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.Unary(operator, operand, _):", "operand_may_be_owned_view: bool = flow.last_value_may_be_owned_view"),
    ("Expr.Unary(operator, operand, _):", "unary_result_may_be_owned_view: bool = operator != TokenKind.Not"),
    ("Expr.Unary(operator, operand, _):", "flow.last_value_may_be_owned_view <- operand_may_be_owned_view and unary_result_may_be_owned_view"),
)

BINARY_VIEW_WALK_EDGES = (
    ("Expr.Binary(left, binary_operator, right, _):", "left_may_be_owned_view: bool = flow.last_value_may_be_owned_view"),
    ("Expr.Binary(left, binary_operator, right, _):", "right_may_be_owned_view: mutable bool = false"),
    ("Expr.Binary(left, binary_operator, right, _):", "binary_result_is_bool: bool = chv_binary_operator_returns_bool(binary_operator, right)"),
    ("Expr.Binary(left, binary_operator, right, _):", "flow.last_value_may_be_owned_view <- (left_may_be_owned_view or right_may_be_owned_view) if not binary_result_is_bool else false"),
)

BINARY_BOOLEAN_RESULT_EDGES = (
    ("Expr.Binary(left, binary_operator, right, _):", BINARY_VIEW_WALK_EDGES[2][1]),
    ("can Memory.Allocate, Abort.Panic:", "boolean_operator: bool = operator == TokenKind.EqEq or operator == TokenKind.BangEq or operator == TokenKind.Lt or operator == TokenKind.Gt or operator == TokenKind.LtEq or operator == TokenKind.GtEq or operator == TokenKind.In or operator == TokenKind.Is or operator == TokenKind.And or operator == TokenKind.Or"),
    ("can Memory.Allocate, Abort.Panic:", "return boolean_operator or (operator == TokenKind.As and not chv_is_reinterpret_target_marker(right))"),
    ("Expr.Binary(left, binary_operator, right, _):", BINARY_VIEW_WALK_EDGES[3][1]),
)

REINTERPRET_TARGET_MARKER_EDGES = (
    ("match target:", "Expr.Ident(name, _):"),
    ("match target:", "_:"),
    ("Expr.Ident(name, _):", "return name == \"&\" or name == \"!\""),
    ("_:", "return false"),
)

UNARY_VIEW_RESULT_EDGES = (
    ("Expr.Unary(operator, operand, _):", "return chv_is_owned_view(operand, flow, depth + 1)"),
    ("Expr.Unary(operator, operand, _):", "return false if operator == TokenKind.Not"),
)

REF_ALIAS_ADDRESS_EDGES = (
    ("Expr.Unary(operator, operand, _):", "return chv_expression_may_alias_ref(operand, ref_params, flow, table, depth + 1)"),
    ("Expr.Unary(operator, operand, _):", "return false if operator == TokenKind.Not"),
)

SUMMARY_CALL_EDGES = (
    ("while target < call_arguments.count |target, table, source_cache_ready, source_checked, source_is_owned_view| -> table:", "if sts_is_writable(summary, callee_name, target):"),
    ("if sts_is_writable(summary, callee_name, target):", "if chv_alias_reference_at(call_arguments, argument_may_alias_refs, target, ref_params, flow, table):"),
    ("while source < call_arguments.count |source, table, source_is_owned_view, source_checked| -> table:", "if source != target and sts_has_pair(summary, callee_name, target, source):"),
    ("if source != target and sts_has_pair(summary, callee_name, target, source):", "if not source_checked[source]:"),
    ("if not source_checked[source]:", "source_is_owned_view[source] <- chv_owned_view_at(call_arguments, argument_owned_views, source, flow)"),
)

OVERLOAD_SUMMARY_EDGES = (
    ("for function in functions |summary, summarised, summarised_unreadable, function_owners, table|:", "match function:"),
    ("match function:", "Decl.Func(name: function_name, params: function_parameters, body: function_body, pos: function_pos, _):"),
    ("if writable_found and function_parameters.count > 1:", "summarised.push(function)"),
    ("for function_index in 0..<summarised.count |function_index, more_rows, summary, summarised, summarised_unreadable, function_owners, reference_sites, table|:", "match summarised[function_index]:"),
    ("match summarised[function_index]:", "Decl.Func(name: function_name, params: function_parameters, body: function_body, _):"),
    ("Decl.Func(name: function_name, params: function_parameters, body: function_body, _):", "more_rows <- true if (sts_summarise_function(function_name, function_parameters, function_body, summarised_unreadable[function_index], function_owners[function_index], reference_sites, table, summary) can Global{Read,Write})"),
)

CALLEE_DISPATCH_EDGES = (
    ("Expr.Ident(callee_name, _):", "table <- chv_check_named_call(callee_name, call_arguments, argument_names, argument_owned_views, argument_may_alias_refs, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.Scope(_, scoped_name, _):", "table <- chv_check_named_call(scoped_name, call_arguments, argument_names, argument_owned_views, argument_may_alias_refs, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.Index(head, _, _):", "table <- chv_check_named_callee(head, call_arguments, argument_names, argument_owned_views, argument_may_alias_refs, method_receiver_owned_view, method_receiver_may_alias_ref, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.IndexN(head, _, _):", "table <- chv_check_named_callee(head, call_arguments, argument_names, argument_owned_views, argument_may_alias_refs, method_receiver_owned_view, method_receiver_may_alias_ref, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.Paren(inner, _):", "table <- chv_check_named_callee(inner, call_arguments, argument_names, argument_owned_views, argument_may_alias_refs, method_receiver_owned_view, method_receiver_may_alias_ref, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("_:", "table <- chv_check_unknown_call(call_arguments, argument_owned_views, argument_may_alias_refs, ref_params, binders, owned, view_names, view_values, flow, table)"),
)

FIELD_UNKNOWN_CALL_EDGES = (
    ("Expr.Field(receiver, _, _):", "method_arguments: mutable darray[Ast::Expr] = [receiver]"),
    ("Expr.Field(receiver, _, _):", "method_arguments.extend(call_arguments)"),
    ("Expr.Field(receiver, _, _):", "method_owned_views: mutable darray[bool] = [method_receiver_owned_view]"),
    ("Expr.Field(receiver, _, _):", "method_owned_views.extend(argument_owned_views)"),
    ("Expr.Field(receiver, _, _):", "method_may_alias_refs: mutable darray[bool] = [method_receiver_may_alias_ref]"),
    ("Expr.Field(receiver, _, _):", "method_may_alias_refs.extend(argument_may_alias_refs)"),
    ("Expr.Field(receiver, _, _):", "table <- chv_check_unknown_call(method_arguments, method_owned_views, method_may_alias_refs, ref_params, binders, owned, view_names, view_values, flow, table)"),
)

NAMED_CALL_EDGES = (
    ("if not chv_call_has_named_arguments(argument_names) and sts_is_declared(summary, callee_name) and not (any binder in binders where binder == callee_name):", "table <- chv_check_call_target(callee_name, call_arguments, argument_owned_views, argument_may_alias_refs, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("else:", "table <- chv_check_unknown_call(call_arguments, argument_owned_views, argument_may_alias_refs, ref_params, binders, owned, view_names, view_values, flow, table)"),
)

NAMED_ARGUMENT_UNIFIER_EDGES = (
    ("Expr.Call(callee, arguments, argument_names, _):", "sts_unify_calls(callee, summary, has_unreadable_binder, function_owner, reference_sites, table, classes)"),
    ("Expr.Call(callee, arguments, argument_names, _):", "for argument in arguments |classes, reference_sites|:"),
    ("Expr.Ident(callee_name, callee_position):", 'shadowed: bool = borrow_reference_site_is_local(reference_sites, function_owner, callee_position, table) or has_unreadable_binder'),
    ("Expr.Ident(callee_name, callee_position):", 'if sts_is_declared(summary, callee_name) and not shadowed and not (any argument_name in argument_names where argument_name != ""):') ,
    ('if sts_is_declared(summary, callee_name) and not shadowed and not (any argument_name in argument_names where argument_name != ""):', "pair_row: mutable u32 = sts_pair_first(summary, callee_name)"),
    ('if sts_is_declared(summary, callee_name) and not shadowed and not (any argument_name in argument_names where argument_name != ""):', "return"),
    ("_:", "sts_collect_names(expression, hidden_names)", 2),
    ("_:", "sts_unify_all(classes, hidden_names)", 2),
)

NAMED_ARGUMENT_STATIC_EFFECT_EDGES = (
    ("for candidate in candidates |table, flow, candidate_capture_offset| -> table:", "chv_check_call_target(candidate.callee, candidate_arguments, candidate_owned_views, candidate_may_alias_refs, ref_params, binders, owned, view_names, view_values, flow, summary, table) if not chv_call_has_named_arguments(argument_names)"),
    ("for candidate in candidates |table, flow, candidate_capture_offset| -> table:", "chv_check_unknown_call(candidate_arguments, candidate_owned_views, candidate_may_alias_refs, ref_params, binders, owned, view_names, view_values, flow, table) if chv_call_has_named_arguments(argument_names)"),
)

UNKNOWN_CALL_EDGES = (
    ("for target in 0..<call_arguments.count |table| -> table:", "if chv_alias_reference_at(call_arguments, argument_may_alias_refs, target, ref_params, flow, table):"),
    ("if chv_alias_reference_at(call_arguments, argument_may_alias_refs, target, ref_params, flow, table):", "for source in 0..<call_arguments.count |table| -> table:"),
    ("for source in 0..<call_arguments.count |table| -> table:", "if source != target and chv_owned_view_at(call_arguments, argument_owned_views, source, flow):"),
    ("if source != target and chv_owned_view_at(call_arguments, argument_owned_views, source, flow):", "table.diagnostics <- table.diagnostics.push(Diagnostic{kind: DiagnosticKind.AutoRegionStoreEscape, name: \"\", pos: at, line: at.line, expected: \"\", actual: \"\", state_code: (target + CHV_DIAGNOSTIC_ARGUMENT_NUMBER_BASE).u32()})"),
)

UNIFIER_FALLBACK_EDGES = (
    ("_:", "sts_collect_names(expression, hidden_names)", 2),
    ("_:", "sts_unify_all(classes, hidden_names)", 2),
)


def validate_edge_set(source: str, edges: tuple[tuple, ...], label: str) -> None:
    for edge in edges:
        parent, child, occurrence = edge_parts(edge)
        if not direct_child(source, parent, child, occurrence):
            raise SystemExit(f"{label} misses child route {parent} -> {child}")
        mutated = wrap_direct_child_block(source, parent, child, occurrence)
        if mutated == source or direct_child(mutated, parent, child, occurrence):
            raise SystemExit(f"{label} route mutation failed for {parent} -> {child}")
        try:
            validate_edge_set_without_mutation(mutated, edges, label)
        except SystemExit:
            pass
        else:
            raise SystemExit(f"{label} accepted an unreachable child route {parent} -> {child}")


def validate_edge_set_without_mutation(source: str, edges: tuple[tuple, ...], label: str) -> None:
    for edge in edges:
        parent, child, occurrence = edge_parts(edge)
        if not direct_child(source, parent, child, occurrence):
            raise SystemExit(f"{label} misses child route {parent} -> {child}")


def validate_or_theorem(text: str, name: str, routes: dict[str, tuple], source: str,
                        edges: tuple[tuple, ...]) -> None:
    match = re.search(rf"(?ms)^def {re.escape(name)}\((.*?)\)\s*-> bool:\n(.*?)(?=^def |\Z)", text)
    if not match:
        raise SystemExit(f"missing store-through theorem {name}")
    parameters = tuple(re.findall(r"([A-Za-z_][A-Za-z0-9_]*): bool", match.group(1)))
    if parameters != tuple(routes):
        raise SystemExit(f"{name} proof inputs no longer match source routes")
    expression = " or ".join(parameters)
    expected_forms = {
        compact_code(f"ensure result == {ensure_expression}\nreturn {return_expression}")
        for ensure_expression in (expression, f"({expression})")
        for return_expression in (expression, f"({expression})")
    }
    if compact_code(match.group(2)) not in expected_forms:
        raise SystemExit(f"{name} no longer proves that each route preserves name presence")
    edge_set = {edge_parts(edge) for edge in edges}
    for parameter, route_edges in routes.items():
        for edge in route_edges:
            parent, child, occurrence = edge_parts(edge)
            if (parent, child, occurrence) not in edge_set or not direct_child(source, parent, child, occurrence):
                raise SystemExit(f"{name} route {parameter} is no longer source-bound")


def validate_exact_boolean_theorem(text: str, name: str, routes: dict[str, tuple],
                                   expression: str, source: str,
                                   edges: tuple[tuple, ...]) -> None:
    match = re.search(rf"(?ms)^def {re.escape(name)}\((.*?)\)\s*-> bool:\n(.*?)(?=^def |\Z)", text)
    if not match:
        raise SystemExit(f"missing source-bound theorem {name}")
    parameters = tuple(re.findall(r"([A-Za-z_][A-Za-z0-9_]*): bool", match.group(1)))
    if parameters != tuple(routes):
        raise SystemExit(f"{name} proof inputs no longer match source routes")
    expected = compact_code(f"ensure result == ({expression})\nreturn {expression}")
    if compact_code(match.group(2)) != expected:
        raise SystemExit(f"{name} no longer proves its stated Boolean relationship")
    edge_set = {edge_parts(edge) for edge in edges}
    for parameter, route_edges in routes.items():
        for edge in route_edges:
            parent, child, occurrence = edge_parts(edge)
            if (parent, child, occurrence) not in edge_set or not direct_child(source, parent, child, occurrence):
                raise SystemExit(f"{name} route {parameter} is no longer source-bound")


def validate_exact_boolean_theorem_source_routes(
        text: str, name: str, parameters_expected: tuple[str, ...],
        expression: str, sources: dict[str, str],
        routes: dict[str, tuple[tuple[str, tuple], ...]]) -> None:
    """Bind a theorem's input routes across separate source functions in order."""
    match = re.search(rf"(?ms)^def {re.escape(name)}\((.*?)\)\s*-> bool:\n(.*?)(?=^def |\Z)", text)
    if not match:
        raise SystemExit(f"missing source-bound theorem {name}")
    parameters = tuple(re.findall(r"([A-Za-z_][A-Za-z0-9_]*): bool", match.group(1)))
    if parameters != parameters_expected or tuple(routes) != parameters:
        raise SystemExit(f"{name} proof inputs no longer match source routes")
    expected = compact_code(f"ensure result == ({expression})\nreturn {expression}")
    if compact_code(match.group(2)) != expected:
        raise SystemExit(f"{name} no longer proves its stated Boolean relationship")
    for parameter, route_steps in routes.items():
        if not route_steps:
            raise SystemExit(f"{name} route {parameter} has no source-bound steps")
        for source_name, edge in route_steps:
            if source_name not in sources:
                raise SystemExit(f"{name} route {parameter} names an unknown source section")
            parent, child, occurrence = edge_parts(edge)
            if not direct_child(sources[source_name], parent, child, occurrence):
                raise SystemExit(f"{name} route {parameter} is no longer source-bound")


summary_text = SUMMARY.read_text()
ast_text = AST_NODES.read_text()
side_text = AST_SIDE_TABLES.read_text()
effect_text = EFFECT_SHAPE.read_text()
holder_text = HOLDER_SOURCE.read_text()
positive_text = POSITIVE.read_text()
negative_text = NEGATIVE.read_text()

if enum_variant_names(ast_text, "Expr", "Stmt") != EXPECTED_EXPR_NAMES:
    raise SystemExit("Expr AST changed without revising the store-through collection proof")
if enum_variant_names(ast_text, "Stmt", "Decl") != EXPECTED_STMT_NAMES:
    raise SystemExit("Stmt AST changed without revising the store-through collection proof")
for record, expected in EXPECTED_SIDE_TABLE_FIELDS.items():
    if struct_fields(side_text, record) != expected:
        raise SystemExit(f"AST side-table record {record} changed without revising the store-through proof")

collect_source = function_section(summary_text, "sts_collect_names")
statement_collect_source = function_section(summary_text, "sts_collect_statement_names")
unifier_source = function_section(summary_text, "sts_unify_calls")
statements_source = function_section(summary_text, "sts_statements")
bound_unifier_source = function_section(summary_text, "sts_unify_bound")
holder_scan_statements = function_section(holder_text, "chv_scan_locals")
holder_scan_expressions = function_section(holder_text, "chv_scan_expression_locals")
holder_walk_expressions = function_section(holder_text, "chv_walk_expression")
holder_walk_statements = function_section(holder_text, "chv_walk_statements")
scope_name_body = match_arm_body(collect_source, "match expression:", "Expr.Scope(_, _, _):")
if scope_name_body is None or compact_code(scope_name_body) != "pass":
    raise SystemExit("store-through name collector must not treat a namespace/type path as a runtime value")
if tuple(sorted(explicit_match_arm_names(collect_source, "match expression:", "Expr."))) != tuple(sorted(EXPECTED_EXPR_NAMES)):
    raise SystemExit("store-through name collector is not exhaustive over Expr")
if tuple(sorted(explicit_match_arm_names(statement_collect_source, "match statement:", "Stmt."))) != tuple(sorted(EXPECTED_STMT_NAMES)):
    raise SystemExit("store-through nested-statement collector is not exhaustive over Stmt")
statement_unifier_arms = explicit_match_arm_names(statements_source, "match statement:", "Stmt.")
statement_unifier_expected = set(EXPECTED_STMT_NAMES) - {"Invalid", "Break", "Continue"}
if tuple(sorted(statement_unifier_arms)) != tuple(sorted(statement_unifier_expected)):
    raise SystemExit("store-through statement walker omits an expression-bearing statement variant")
if len(re.findall(r"(?m)^\s*_:\s*$", statements_source)) != 1:
    raise SystemExit("store-through statement walker must retain a single explicit leaf fallback")

expr_unifier_arms = explicit_match_arm_names(unifier_source, "match expression:", "Expr.")
if tuple(sorted(expr_unifier_arms)) != tuple(sorted(("Call Field Index Binary Unary Move Paren If").split())):
    raise SystemExit("store-through unifier changed its explicit recursive cases")
if len(re.findall(r"(?m)^\s*_:\s*$", unifier_source)) != 3:
    raise SystemExit("store-through unifier must retain exactly one conservative fallback")
expected_fallback = compact_code("""hidden_names: mutable darray[sview] = []
sts_collect_names(expression, hidden_names)
sts_unify_all(classes, hidden_names)""")
fallback_block = match_arm_body(unifier_source, "match expression:", "_:")
if fallback_block is None or compact_code(fallback_block) != expected_fallback:
    raise SystemExit("store-through unifier fallback no longer unifies every collected hidden name")

validate_edge_set(collect_source, EXPRESSION_EDGES, "expression name collector")
validate_edge_set(statement_collect_source, STATEMENT_COLLECTOR_EDGES, "nested statement name collector")
validate_edge_set(unifier_source, EXPRESSION_UNIFIER_EDGES, "expression call unifier")
validate_edge_set(statements_source, STATEMENT_UNIFIER_EDGES, "statement call unifier")
expected_bound_unifier = compact_code("""can Memory.Allocate, Abort.Panic, Global{Read,Write}:
declared_type_id: u32 = annotation_type_id(declared_type, table) can Global{Read,Write}
bound_type_is_reference_free: mutable bool = false
can Memory.Allocate, Abort.Panic, Global{Read,Write}:
    bound_type_is_reference_free <- bam_type_is_proven_reference_free_cached(declared_type_id, reference_sites, table) if declared_type_id != 0
bound_type_id: u32 = declared_type_id
bound_type_is_host_handle: bool = sts_type_is_llvm_handle(bound_type_id, table)
if not bound_type_is_reference_free and not bound_type_is_host_handle:
    bound_names: mutable darray[sview] = []
    bound_names.push(name) if name != ""
    sts_collect_names(value, bound_names)
    sts_unify_all(classes, bound_names)
sts_unify_calls(value, summary, has_unreadable_binder, function_owner, reference_sites, table, classes)""")
if compact_code(bound_unifier_source) != expected_bound_unifier:
    raise SystemExit("store-through binding union must be skipped only for proven reference-free types while preserving call summaries")
for fallback_child in ("sts_collect_names(expression, hidden_names)", "sts_unify_all(classes, hidden_names)"):
    if not direct_child(unifier_source, "_:", fallback_child, 2):
        raise SystemExit(f"store-through wildcard fallback is missing {fallback_child}")
    mutated = wrap_direct_child_block(unifier_source, "_:", fallback_child, 2)
    if mutated == unifier_source or direct_child(mutated, "_:", fallback_child, 2):
        raise SystemExit("store-through fallback child mutation did not disable its source route")

helper_body = compact_code(function_section(effect_text, "effect_runtime_children"))
expected_helper = compact_code("""children: mutable darray[Expr] = []
for candidate in candidates |children|:
    children.extend(candidate.captures)
children.extend(arguments)
return children""")
if helper_body != expected_helper:
    raise SystemExit("static-effect child projection no longer includes captures and arguments")

theorem_routes = {
    "proof_sts_match_names_reach_fallback": {
        "scrutinee": (("Expr.Match(scrutinee, arms, _):", "sts_collect_names(scrutinee, out)"),),
        "guard": (("for arm in arms |out|:", "sts_collect_names(arm.guard, out)", 0),),
        "body": (("for arm in arms |out|:", "sts_collect_statement_names(arm.body, out)", 0),),
    },
    "proof_sts_catch_names_reach_fallback": {
        "guarded": (("Expr.Catch(guarded, arms, _):", "sts_collect_names(guarded, out)"),),
        "guard": (("for arm in arms |out|:", "sts_collect_names(arm.guard, out)", 1),),
        "body": (("for arm in arms |out|:", "sts_collect_statement_names(arm.body, out)", 1),),
    },
    "proof_sts_block_names_reach_fallback": {
        "capture": (("for capture in captures |out|:", "out.push(capture) if capture != \"\""),),
        "statement": (("Expr.Block(statements, value, captures, _):", "sts_collect_statement_names(statements, out)"),),
        "value": (("Expr.Block(statements, value, captures, _):", "sts_collect_names(value, out)"),),
    },
    "proof_sts_dict_names_reach_fallback": {
        "key": (("for entry in entries |out|:", "sts_collect_names(entry.key, out)"),),
        "value": (("for entry in entries |out|:", "sts_collect_names(entry.value, out)"),),
    },
    "proof_sts_effect_names_reach_fallback": {
        "capture": (),
        "argument": (),
    },
    "proof_sts_match_statement_names_reach_fallback": {
        "scrutinee": (("Stmt.Match(scrutinee, arms, _):", "sts_collect_names(scrutinee, out)"),),
        "guard": (("for arm in arms |out|:", "sts_collect_names(arm.guard, out)"),),
        "body": (("for arm in arms |out|:", "sts_collect_statement_names(arm.body, out)"),),
    },
    "proof_sts_contract_expression_reaches_fallback": {
        "expression": (("Stmt.Contract(_, expression, _):", "sts_collect_names(expression, out)"),),
    },
    "proof_sts_hidden_names_are_unified": {
        "names_found": (("_:", "sts_unify_all(classes, hidden_names)", 2),),
    },
    "proof_sts_nested_callee_calls_reach_unifier": {
        "callee_call": (("Expr.Call(callee, arguments, argument_names, _):", "sts_unify_calls(callee, summary, has_unreadable_binder, function_owner, reference_sites, table, classes)"),),
    },
    "proof_chv_static_effect_candidates_check_captures_and_arguments": {
        "captures_checked": (("for candidate in candidates |table, flow, candidate_capture_offset| -> table:", "candidate_arguments.extend(candidate.captures)"),),
        "arguments_checked": (("for candidate in candidates |table, flow, candidate_capture_offset| -> table:", "candidate_arguments.extend(arguments)"),),
    },
    "proof_chv_comprehension_scope_masks_shadowed_reference": {
        "reference_parameter": (("Expr.Comprehension(variable, iterable, condition, body, _, _):", "for outer_ref in ref_params |comprehension_ref_params|:"),),
        "binder_shadows_reference": (("for outer_ref in ref_params |comprehension_ref_params|:", "comprehension_ref_params.push(outer_ref) if outer_ref != variable"),),
    },
    "proof_chv_view_alias_join_preserves_owned_fact": {
        "left_branch_may_own": VIEW_FLOW_MERGE_EDGES,
        "right_branch_may_own": VIEW_FLOW_MERGE_EDGES,
    },
    "proof_chv_aggregate_construct_keeps_field_view_taint": {
        "field_walked": (CONSTRUCT_VIEW_TAINT_EDGES[0], CONSTRUCT_VIEW_TAINT_EDGES[1]),
        "field_taint_joined": (CONSTRUCT_VIEW_TAINT_EDGES[2],),
        "aggregate_taint_set": (CONSTRUCT_VIEW_TAINT_EDGES[3],),
    },
    "proof_chv_record_update_keeps_base_and_field_view_taint": {
        "base_taint_kept": (RECORD_UPDATE_VIEW_TAINT_EDGES[0], RECORD_UPDATE_VIEW_TAINT_EDGES[1]),
        "field_walked": (RECORD_UPDATE_VIEW_TAINT_EDGES[2], RECORD_UPDATE_VIEW_TAINT_EDGES[3]),
        "field_taint_joined": (RECORD_UPDATE_VIEW_TAINT_EDGES[4],),
        "aggregate_taint_set": (RECORD_UPDATE_VIEW_TAINT_EDGES[5],),
    },
    "proof_chv_projection_assignment_preserves_aggregate_taint": {
        "rhs_may_be_view": (ASSIGN_VIEW_TAINT_EDGES[5], ASSIGN_VIEW_TAINT_EDGES[6], ASSIGN_VIEW_TAINT_EDGES[7]),
        "previous_root_may_be_view": (ASSIGN_VIEW_TAINT_EDGES[3],),
        "compound_assignment": (ASSIGN_VIEW_TAINT_EDGES[9],),
        "target_is_projection": (ASSIGN_VIEW_TAINT_EDGES[1],),
    },
    "proof_chv_comprehension_result_tracks_yielded_view": {
        "body_may_be_owned_view": COMPREHENSION_VIEW_TAINT_EDGES,
    },
    "proof_chv_comprehension_element_view_reaches_yielded_result": {
        "collection_taint_reaches_iterable_binding": ARRAY_VIEW_TAINT_EDGES[:4] + (HOLDER_WALK_STATEMENT_EDGES[-1],) + IDENTIFIER_VIEW_TAINT_EDGES,
        "iterable_taint_reaches_binder": COMPREHENSION_BINDER_VIEW_TAINT_EDGES[:3],
        "binder_taint_reaches_result": IDENTIFIER_VIEW_TAINT_EDGES + COMPREHENSION_BINDER_VIEW_TAINT_EDGES[3:],
    },
    "proof_chv_for_iterator_inherits_iterable_view_taint": {
        "iterable_may_be_owned_view": FOR_ITERATOR_VIEW_TAINT_EDGES,
    },
    "proof_chv_for_iterator_inherits_iterable_reference_alias": {
        "yielded_element_alias": (FOR_ITERATOR_REF_ALIAS_EDGES[1], FOR_ITERATOR_REF_ALIAS_EDGES[2]),
        "mutable_slot_alias": (FOR_ITERATOR_REF_ALIAS_EDGES[0], FOR_ITERATOR_REF_ALIAS_EDGES[3]),
        "binder_bound": (FOR_ITERATOR_REF_ALIAS_EDGES[4], FOR_ITERATOR_REF_ALIAS_EDGES[5]),
    },
    "proof_chv_method_result_tracks_receiver_or_arguments": {
        "receiver_may_be_owned": (METHOD_CALL_VIEW_RESULT_EDGES[2],),
        "arguments_may_be_owned": (METHOD_CALL_VIEW_RESULT_EDGES[3],),
    },
    "proof_chv_callable_result_tracks_argument_view": {
        "argument_may_be_owned": CALLABLE_VIEW_RESULT_EDGES,
    },
    "proof_chv_call_result_tracks_argument_view": {
        "direct_result_may_be_owned": (CALL_RESULT_VIEW_TAINT_EDGES[0],),
        "argument_may_be_owned": (CALL_RESULT_VIEW_TAINT_EDGES[1],),
    },
    "proof_chv_static_effect_result_tracks_runtime_views": {
        "runtime_child_may_be_owned": STATIC_EFFECT_RESULT_VIEW_TAINT_EDGES,
    },
    "proof_chv_aggregate_field_projection_requires_tainted_root": {
        "root_is_known": FIELD_PROJECTION_VIEW_TAINT_EDGES[:2],
        "aggregate_may_contain_view": (FIELD_PROJECTION_VIEW_TAINT_EDGES[2],),
    },
    "proof_chv_reference_alias_join_preserves_either_path": {
        "left_path_may_alias": REF_ALIAS_FLOW_MERGE_EDGES,
        "right_path_may_alias": REF_ALIAS_FLOW_MERGE_EDGES,
    },
    "proof_chv_reference_targets_cover_alias_routes": {
        "direct_parameter": (REF_ALIAS_HELPER_EDGES[2],),
        "local_alias": REF_ALIAS_HELPER_EDGES[:2],
        "call_result": (REF_ALIAS_HELPER_EDGES[3],),
        "projection_fallback": (REF_ALIAS_HELPER_EDGES[5],),
        "aggregate_alias": REF_ALIAS_HELPER_EDGES[8:],
    },
    "proof_chv_comprehension_result_tracks_yielded_alias": {
        "yielded_element_alias_checked": (),
        "binder_alias_bound": (),
        "body_alias_checked": (),
    },
    "proof_chv_getelse_recovery_termination_excludes_recovery_state": {
        "guarded_path_joined": (),
        "recovery_terminates": (),
        "recovery_path_joined": (),
        "recovery_path_excluded": (),
        "recovery_value_joined": (),
    },
    "proof_chv_scalar_sview_rebinding_prefers_latest_fact": {
        "flow_row_found": (),
        "flow_scalar": (),
        "initializer_scalar": (),
    },
    "proof_chv_binary_operator_checks_both_operands": {
        "receiver_checked": (HOLDER_WALK_EXPRESSION_EDGES[21],),
        "operand_checked": (BINARY_NON_RUNTIME_TARGET_EDGES[0], BINARY_NON_RUNTIME_TARGET_EDGES[1], HOLDER_WALK_EXPRESSION_EDGES[23], BINARY_AND_RIGHT_WALK_EDGE),
        "fallback_checked": (BINARY_NON_RUNTIME_TARGET_EDGES[0], BINARY_NON_RUNTIME_TARGET_EDGES[1]) + BINARY_OPERATOR_FALLBACK_EDGES,
    },
    "proof_chv_binary_target_operators_skip_runtime_value_path": {
        "target_operator": (BINARY_NON_RUNTIME_TARGET_EDGES[0],),
        "target_classified": (BINARY_NON_RUNTIME_TARGET_EDGES[1],),
        "right_walk_guarded": (HOLDER_WALK_EXPRESSION_EDGES[22], HOLDER_WALK_EXPRESSION_EDGES[23], BINARY_AND_RIGHT_WALK_EDGE),
        "fallback_guarded": (HOLDER_WALK_EXPRESSION_EDGES[22],) + BINARY_OPERATOR_FALLBACK_EDGES,
    },
    "proof_chv_binary_operator_result_tracks_reference_operands": {
        "boolean_result": (REF_ALIAS_HELPER_EDGES[6], BINARY_BOOLEAN_RESULT_EDGES[1], BINARY_BOOLEAN_RESULT_EDGES[2]) + REINTERPRET_TARGET_MARKER_EDGES,
        "left_alias": (REF_ALIAS_HELPER_EDGES[4],),
        "right_alias": (REF_ALIAS_HELPER_EDGES[4],),
    },
    "proof_chv_binary_operator_result_tracks_view_operands": {
        "boolean_result": BINARY_BOOLEAN_RESULT_EDGES + REINTERPRET_TARGET_MARKER_EDGES,
        "left_may_be_view": (BINARY_VIEW_WALK_EDGES[0], BINARY_VIEW_WALK_EDGES[3]),
        "right_may_be_view": (HOLDER_WALK_EXPRESSION_EDGES[22], BINARY_AND_RIGHT_WALK_EDGE,
                               BINARY_RIGHT_VIEW_EDGES[0], HOLDER_WALK_EXPRESSION_EDGES[23],
                               BINARY_RIGHT_VIEW_EDGES[1], BINARY_VIEW_WALK_EDGES[3]),
    },
    "proof_chv_binary_boolean_result_clears_view_taint": {
        "boolean_result_classified": BINARY_BOOLEAN_RESULT_EDGES[:3] + REINTERPRET_TARGET_MARKER_EDGES,
        "result_taint_cleared": (BINARY_BOOLEAN_RESULT_EDGES[3],),
    },
    "proof_chv_index_overloads_check_receiver_and_keys": {
        "receiver_checked": (INDEX_OPERATOR_EDGES[0], INDEX_OPERATOR_EDGES[7]),
        "key_checked": (INDEX_OPERATOR_EDGES[2],),
        "call_checked": INDEX_OPERATOR_EDGES[3:7],
        "type_application_skipped": (INDEX_OPERATOR_EDGES[1], INDEX_OPERATOR_EDGES[8], INDEX_OPERATOR_EDGES[9]),
    },
    "proof_chv_index_result_tracks_receiver_view": {
        "receiver_may_be_view": (INDEX_VIEW_RESULT_EDGES[3],),
        "index_key_may_be_view": (INDEX_VIEW_RESULT_EDGES[2],),
        "runtime_index_guarded": (INDEX_VIEW_RESULT_EDGES[1],),
    },
    "proof_chv_indexn_result_tracks_receiver_only": {
        "receiver_may_be_view": INDEXN_VIEW_RESULT_EDGES,
    },
    "proof_chv_address_of_uses_operand_reference_provenance": {
        "boolean_not": (REF_ALIAS_ADDRESS_EDGES[1],),
        "operand_alias_checked": (REF_ALIAS_ADDRESS_EDGES[0],),
    },
    "proof_chv_unary_negation_tracks_reference_operand": {
        "boolean_not": (REF_ALIAS_ADDRESS_EDGES[1],),
        "operand_alias_checked": (REF_ALIAS_ADDRESS_EDGES[0],),
    },
    "proof_chv_unary_negation_visits_operand": {
        "operand_checked": (UNARY_NEGATION_EDGES[0],),
    },
    "proof_chv_unary_negation_tracks_view_operand": {
        "boolean_not": (UNARY_VIEW_RESULT_EDGES[1],),
        "operand_may_be_view": (UNARY_VIEW_RESULT_EDGES[0],),
    },
    "proof_chv_projection_fallback_requires_caller_reference": {
        "caller_reference_exists": (REF_ALIAS_HELPER_EDGES[5],),
    },
    "proof_chv_overload_bodies_contribute_store_rows": {
        "overload_body_checked": OVERLOAD_SUMMARY_EDGES,
    },
    "proof_chv_method_calls_check_receiver_and_arguments": {
        "receiver_checked": (("Expr.Field(receiver, _, _):", "method_arguments: mutable darray[Ast::Expr] = [receiver]"),),
        "arguments_checked": (("Expr.Field(receiver, _, _):", "method_arguments.extend(call_arguments)"),),
    },
    "proof_chv_indirect_calls_fail_closed": {
        "reference_target_checked": (("for target in 0..<call_arguments.count |table| -> table:", "if chv_alias_reference_at(call_arguments, argument_may_alias_refs, target, ref_params, flow, table):"),),
        "owned_view_checked": (("for source in 0..<call_arguments.count |table| -> table:", "if source != target and chv_owned_view_at(call_arguments, argument_owned_views, source, flow):"),),
    },
    "proof_chv_summary_calls_check_reference_aliases": {
        "reference_alias_checked": SUMMARY_CALL_EDGES[:2],
        "owned_view_checked": SUMMARY_CALL_EDGES[2:],
    },
    "proof_chv_named_callees_cover_dispatch_routes": {
        "direct_call_checked": (
            ("Expr.Scope(_, scoped_name, _):", "table <- chv_check_named_call(scoped_name, call_arguments, argument_names, argument_owned_views, argument_may_alias_refs, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
            ("Expr.Index(head, _, _):", "table <- chv_check_named_callee(head, call_arguments, argument_names, argument_owned_views, argument_may_alias_refs, method_receiver_owned_view, method_receiver_may_alias_ref, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
        ),
    },
    "proof_chv_named_arguments_use_unknown_call_fallback": {
        "named_arguments_present": NAMED_CALL_EDGES,
    },
    "proof_sts_named_argument_calls_use_conservative_fallback": {
        "named_arguments_present": NAMED_ARGUMENT_UNIFIER_EDGES,
    },
    "proof_chv_field_calls_use_unknown_fallback": {
        "field_call_present": FIELD_UNKNOWN_CALL_EDGES,
    },
}
positive_names = set(theorem_routes)
negative_names = {"match_guard_name_is_dropped", "dictionary_key_name_is_dropped", "contract_call_is_dropped", "nested_callee_call_is_ignored", "static_effect_candidate_is_ignored", "ambiguous_owned_view_is_assumed_safe", "overload_store_row_is_ignored", "method_receiver_is_ignored", "indirect_call_is_assumed_safe", "named_arguments_are_treated_as_positional", "callable_field_is_assumed_ufcs", "scalar_target_is_assumed_reference"}
for path, expected in ((POSITIVE, positive_names), (NEGATIVE, negative_names)):
    names = set(re.findall(r"(?m)^def ([A-Za-z_][A-Za-z0-9_]*)\(", path.read_text()))
    if names != expected:
        raise SystemExit(f"{path.name} theorem inventory changed")
for name, routes in theorem_routes.items():
    source_route_sources = None
    source_route_edges = None
    if name == "proof_sts_effect_names_reach_fallback":
        proof_source, proof_edges = effect_text, ()
    elif name == "proof_chv_static_effect_candidates_check_captures_and_arguments":
        proof_source = function_section(holder_text, "chv_check_static_effect_call")
        proof_edges = EFFECT_CANDIDATE_EDGES
    elif name == "proof_chv_comprehension_scope_masks_shadowed_reference":
        proof_source, proof_edges = holder_walk_expressions, HOLDER_WALK_EXPRESSION_EDGES
    elif name == "proof_chv_binary_operator_checks_both_operands":
        source_route_sources = {
            "walker": holder_walk_expressions,
            "target": function_section(holder_text, "chv_binary_operator_has_non_runtime_target"),
        }
        source_route_edges = {
            "receiver_checked": (("walker", HOLDER_WALK_EXPRESSION_EDGES[21]),),
            "operand_checked": (("target", BINARY_NON_RUNTIME_TARGET_EDGES[0]),
                                ("walker", BINARY_NON_RUNTIME_TARGET_EDGES[1]),
                                ("walker", HOLDER_WALK_EXPRESSION_EDGES[23]),
                                ("walker", BINARY_AND_RIGHT_WALK_EDGE)),
            "fallback_checked": (("target", BINARY_NON_RUNTIME_TARGET_EDGES[0]),
                                 ("walker", BINARY_NON_RUNTIME_TARGET_EDGES[1])) + tuple(
                                     ("walker", edge) for edge in BINARY_OPERATOR_FALLBACK_EDGES),
        }
        proof_source, proof_edges = "", ()
    elif name == "proof_chv_binary_operator_result_tracks_reference_operands":
        source_route_sources = {
            "alias": function_section(holder_text, "chv_expression_may_alias_ref"),
            "operator": function_section(holder_text, "chv_binary_operator_returns_bool"),
            "marker": function_section(holder_text, "chv_is_reinterpret_target_marker"),
        }
        source_route_edges = {
            "boolean_result": (("alias", REF_ALIAS_HELPER_EDGES[6]),
                               ("operator", BINARY_BOOLEAN_RESULT_EDGES[1]),
                               ("operator", BINARY_BOOLEAN_RESULT_EDGES[2])) +
                              tuple(("marker", edge) for edge in REINTERPRET_TARGET_MARKER_EDGES),
            "left_alias": (("alias", REF_ALIAS_HELPER_EDGES[4]),),
            "right_alias": (("alias", REF_ALIAS_HELPER_EDGES[4]),),
        }
        proof_source, proof_edges = "", ()
    elif name == "proof_chv_binary_operator_result_tracks_view_operands":
        source_route_sources = {
            "walker": holder_walk_expressions,
            "operator": function_section(holder_text, "chv_binary_operator_returns_bool"),
            "marker": function_section(holder_text, "chv_is_reinterpret_target_marker"),
        }
        boolean_result_route = (("walker", BINARY_BOOLEAN_RESULT_EDGES[0]),
                                ("operator", BINARY_BOOLEAN_RESULT_EDGES[1]),
                                ("operator", BINARY_BOOLEAN_RESULT_EDGES[2])) + tuple(
                                    ("marker", edge) for edge in REINTERPRET_TARGET_MARKER_EDGES)
        source_route_edges = {
            "boolean_result": boolean_result_route,
            "left_may_be_view": (("walker", BINARY_VIEW_WALK_EDGES[0]),
                                 ("walker", BINARY_VIEW_WALK_EDGES[3])),
            "right_may_be_view": (("walker", HOLDER_WALK_EXPRESSION_EDGES[22]),
                                  ("walker", BINARY_AND_RIGHT_WALK_EDGE),
                                  ("walker", BINARY_RIGHT_VIEW_EDGES[0]),
                                  ("walker", HOLDER_WALK_EXPRESSION_EDGES[23]),
                                  ("walker", BINARY_RIGHT_VIEW_EDGES[1]),
                                  ("walker", BINARY_VIEW_WALK_EDGES[3])),
        }
        proof_source, proof_edges = "", ()
    elif name == "proof_chv_binary_target_operators_skip_runtime_value_path":
        source_route_sources = {
            "walker": holder_walk_expressions,
            "target": function_section(holder_text, "chv_binary_operator_has_non_runtime_target"),
        }
        source_route_edges = {
            "target_operator": (("target", BINARY_NON_RUNTIME_TARGET_EDGES[0]),),
            "target_classified": (("walker", BINARY_NON_RUNTIME_TARGET_EDGES[1]),),
            "right_walk_guarded": (("walker", HOLDER_WALK_EXPRESSION_EDGES[22]),
                                   ("walker", HOLDER_WALK_EXPRESSION_EDGES[23]),
                                   ("walker", BINARY_AND_RIGHT_WALK_EDGE)),
            "fallback_guarded": (("walker", HOLDER_WALK_EXPRESSION_EDGES[22]),) + tuple(
                ("walker", edge) for edge in BINARY_OPERATOR_FALLBACK_EDGES),
        }
        proof_source, proof_edges = "", ()
    elif name == "proof_chv_binary_boolean_result_clears_view_taint":
        source_route_sources = {
            "walker": holder_walk_expressions,
            "operator": function_section(holder_text, "chv_binary_operator_returns_bool"),
            "marker": function_section(holder_text, "chv_is_reinterpret_target_marker"),
        }
        source_route_edges = {
            "boolean_result_classified": (("walker", BINARY_BOOLEAN_RESULT_EDGES[0]),
                                          ("operator", BINARY_BOOLEAN_RESULT_EDGES[1]),
                                          ("operator", BINARY_BOOLEAN_RESULT_EDGES[2])) +
                                         tuple(("marker", edge) for edge in REINTERPRET_TARGET_MARKER_EDGES),
            "result_taint_cleared": (("walker", BINARY_BOOLEAN_RESULT_EDGES[3]),),
        }
        proof_source, proof_edges = "", ()
    elif name == "proof_chv_index_overloads_check_receiver_and_keys":
        proof_source, proof_edges = holder_walk_expressions, INDEX_OPERATOR_EDGES
    elif name == "proof_chv_index_result_tracks_receiver_view":
        proof_source = function_section(holder_text, "chv_is_owned_view")
        proof_edges = INDEX_VIEW_RESULT_EDGES
    elif name == "proof_chv_indexn_result_tracks_receiver_only":
        proof_source = function_section(holder_text, "chv_is_owned_view")
        proof_edges = INDEXN_VIEW_RESULT_EDGES
    elif name == "proof_chv_view_alias_join_preserves_owned_fact":
        proof_source = function_section(holder_text, "chv_flow_set_merge")
        proof_edges = VIEW_FLOW_MERGE_EDGES
    elif name == "proof_chv_aggregate_construct_keeps_field_view_taint":
        proof_source, proof_edges = holder_walk_expressions, CONSTRUCT_VIEW_TAINT_EDGES
    elif name == "proof_chv_record_update_keeps_base_and_field_view_taint":
        proof_source, proof_edges = holder_walk_expressions, RECORD_UPDATE_VIEW_TAINT_EDGES
    elif name == "proof_chv_projection_assignment_preserves_aggregate_taint":
        proof_source, proof_edges = holder_walk_statements, ASSIGN_VIEW_TAINT_EDGES
    elif name == "proof_chv_comprehension_result_tracks_yielded_view":
        proof_source, proof_edges = holder_walk_expressions, COMPREHENSION_VIEW_TAINT_EDGES
    elif name == "proof_chv_for_iterator_inherits_iterable_view_taint":
        proof_source, proof_edges = holder_walk_statements, FOR_ITERATOR_VIEW_TAINT_EDGES
    elif name == "proof_chv_for_iterator_inherits_iterable_reference_alias":
        source_route_sources = {
            "walker": holder_walk_statements,
            "iterable_alias": function_section(holder_text, "chv_iterable_element_may_alias_reference"),
            "iterable_contain": function_section(holder_text, "chv_iterable_element_may_contain_alias_ref"),
            "binding_facts": function_section(holder_text, "chv_iterable_binding_facts"),
            "container": function_section(holder_text, "chv_expression_may_contain_alias_ref"),
        }
        source_route_edges = {
            "yielded_element_alias": (("walker", FOR_ITERATOR_REF_ALIAS_EDGES[1]),) +
                                     tuple(("iterable_alias", edge) for edge in ITERABLE_REF_ALIAS_EDGES) +
                                     tuple(("iterable_contain", edge) for edge in ITERABLE_CONTAIN_ALIAS_EDGES) +
                                     tuple(("container", edge) for edge in COMPREHENSION_CONTAIN_ALIAS_EDGES),
            "mutable_slot_alias": (("walker", FOR_ITERATOR_REF_ALIAS_EDGES[0]),
                                   ("walker", FOR_ITERATOR_REF_ALIAS_EDGES[3])),
            "binder_bound": (("walker", FOR_ITERATOR_REF_ALIAS_EDGES[4]),
                             ("binding_facts", ITERABLE_BINDING_FACTS_ALIAS_EDGES[0]),
                             ("binding_facts", ITERABLE_BINDING_FACTS_ALIAS_EDGES[1]),
                             ("binding_facts", ITERABLE_BINDING_FACTS_ALIAS_EDGES[2]),
                             ("binding_facts", ITERABLE_BINDING_FACTS_ALIAS_EDGES[3]),
                             ("binding_facts", ITERABLE_BINDING_FACTS_ALIAS_EDGES[4]),
                             ("walker", FOR_ITERATOR_REF_ALIAS_EDGES[5]),
                             ("walker", FOR_ITERATOR_REF_ALIAS_EDGES[6]),
                             ("walker", FOR_ITERATOR_REF_ALIAS_EDGES[7]),
                             ("walker", FOR_ITERATOR_REF_ALIAS_EDGES[8])),
        }
        proof_source, proof_edges = "", ()
    elif name == "proof_chv_comprehension_result_tracks_yielded_alias":
        source_route_sources = {
            "comprehension": function_section(holder_text, "chv_expression_may_alias_ref"),
            "iterable_alias": function_section(holder_text, "chv_iterable_element_may_alias_reference"),
            "iterable_contain": function_section(holder_text, "chv_iterable_element_may_contain_alias_ref"),
            "container": function_section(holder_text, "chv_expression_may_contain_alias_ref"),
            "walker": holder_walk_expressions,
        }
        source_route_edges = {
            "yielded_element_alias_checked": (("comprehension", COMPREHENSION_REF_ALIAS_EDGES[0]),) +
                                             tuple(("iterable_alias", edge) for edge in ITERABLE_REF_ALIAS_EDGES) +
                                             tuple(("iterable_contain", edge) for edge in ITERABLE_CONTAIN_ALIAS_EDGES) +
                                             tuple(("container", edge) for edge in COMPREHENSION_CONTAIN_ALIAS_EDGES),
            "binder_alias_bound": (("comprehension", COMPREHENSION_REF_ALIAS_EDGES[1]),
                                   ("walker", HOLDER_WALK_EXPRESSION_EDGES[10])),
            "body_alias_checked": (("comprehension", COMPREHENSION_REF_ALIAS_EDGES[2]),
                                   ("comprehension", COMPREHENSION_REF_ALIAS_EDGES[3]),
                                   ("walker", HOLDER_WALK_EXPRESSION_EDGES[11])),
        }
        proof_source, proof_edges = "", ()
    elif name == "proof_chv_getelse_recovery_termination_excludes_recovery_state":
        # Keep the enclosing Expr.GetElse row in the source slice: the route
        # edges below are intentionally bound from that arm to its branch
        # merge operations.
        source_route_sources = {"getelse": holder_walk_expressions}
        source_route_edges = {
            "guarded_path_joined": (("getelse", GETELSE_RECOVERY_TERMINATION_EDGES[2]),
                                    ("getelse", GETELSE_RECOVERY_TERMINATION_EDGES[3])),
            "recovery_terminates": (("getelse", GETELSE_RECOVERY_TERMINATION_EDGES[0]),),
            "recovery_path_joined": (("getelse", GETELSE_RECOVERY_TERMINATION_EDGES[2]),),
            "recovery_path_excluded": (("getelse", GETELSE_RECOVERY_TERMINATION_EDGES[3]),),
            "recovery_value_joined": (("getelse", GETELSE_RECOVERY_TERMINATION_EDGES[1]),),
        }
        proof_source, proof_edges = "", ()
    elif name == "proof_chv_scalar_sview_rebinding_prefers_latest_fact":
        source_route_sources = {"flow": function_section(holder_text, "chv_expression_is_scalar_sview")}
        source_route_edges = {
            "flow_row_found": (("flow", SCALAR_SVIEW_FLOW_EDGES[0]), ("flow", SCALAR_SVIEW_FLOW_EDGES[1])),
            "flow_scalar": (("flow", SCALAR_SVIEW_FLOW_EDGES[2]),),
            "initializer_scalar": (("flow", SCALAR_SVIEW_FLOW_EDGES[3]),),
        }
        proof_source, proof_edges = "", ()
    elif name == "proof_chv_comprehension_element_view_reaches_yielded_result":
        proof_source = "\n".join((
            holder_walk_expressions,
            holder_walk_statements,
            function_section(holder_text, "chv_is_owned_view"),
        ))
        proof_edges = ARRAY_VIEW_TAINT_EDGES[:4] + (HOLDER_WALK_STATEMENT_EDGES[-1],) + IDENTIFIER_VIEW_TAINT_EDGES + COMPREHENSION_BINDER_VIEW_TAINT_EDGES
    elif name == "proof_chv_method_result_tracks_receiver_or_arguments":
        proof_source = function_section(holder_text, "chv_is_owned_view")
        proof_edges = METHOD_CALL_VIEW_RESULT_EDGES
    elif name == "proof_chv_callable_result_tracks_argument_view":
        proof_source = function_section(holder_text, "chv_is_owned_view")
        proof_edges = CALLABLE_VIEW_RESULT_EDGES
    elif name == "proof_chv_call_result_tracks_argument_view":
        source_route_sources = {
            "walker": holder_walk_expressions,
            "callee": function_section(holder_text, "chv_walk_call_callee"),
        }
        source_route_edges = {
            "direct_result_may_be_owned": (("walker", HOLDER_WALK_EXPRESSION_EDGES[0]),) +
                                          tuple(("callee", edge) for edge in CALL_CALLEE_INDEXED_VIEW_EDGES) +
                                          (("walker", CALL_RESULT_CALLEE_JOIN_EDGE),
                                           ("walker", CALL_RESULT_VIEW_TAINT_EDGES[2])),
            "argument_may_be_owned": (("walker", CALL_RESULT_VIEW_TAINT_EDGES[1]),
                                      ("walker", CALL_RESULT_VIEW_TAINT_EDGES[2])),
        }
        proof_source, proof_edges = "", ()
    elif name == "proof_chv_static_effect_result_tracks_runtime_views":
        proof_source, proof_edges = holder_walk_expressions, STATIC_EFFECT_RESULT_VIEW_TAINT_EDGES
    elif name == "proof_chv_aggregate_field_projection_requires_tainted_root":
        proof_source = function_section(holder_text, "chv_is_owned_view")
        proof_edges = FIELD_PROJECTION_VIEW_TAINT_EDGES
    elif name == "proof_chv_reference_alias_join_preserves_either_path":
        proof_source = function_section(holder_text, "chv_flow_set_merge")
        proof_edges = REF_ALIAS_FLOW_MERGE_EDGES
    elif name == "proof_chv_reference_targets_cover_alias_routes":
        proof_source = function_section(holder_text, "chv_expression_may_alias_ref")
        proof_edges = REF_ALIAS_HELPER_EDGES
    elif name == "proof_chv_address_of_uses_operand_reference_provenance":
        proof_source = function_section(holder_text, "chv_expression_may_alias_ref")
        proof_edges = REF_ALIAS_ADDRESS_EDGES
    elif name == "proof_chv_unary_negation_tracks_reference_operand":
        proof_source = function_section(holder_text, "chv_expression_may_alias_ref")
        proof_edges = REF_ALIAS_ADDRESS_EDGES
    elif name == "proof_chv_unary_negation_visits_operand":
        proof_source, proof_edges = holder_walk_expressions, UNARY_NEGATION_EDGES
    elif name == "proof_chv_unary_negation_tracks_view_operand":
        proof_source = function_section(holder_text, "chv_is_owned_view")
        proof_edges = UNARY_VIEW_RESULT_EDGES
    elif name == "proof_chv_projection_fallback_requires_caller_reference":
        proof_source = function_section(holder_text, "chv_expression_may_alias_ref")
        proof_edges = REF_ALIAS_HELPER_EDGES
    elif name == "proof_chv_overload_bodies_contribute_store_rows":
        proof_source = function_section(holder_text, "chv_build_summary")
        proof_edges = OVERLOAD_SUMMARY_EDGES
    elif name == "proof_chv_method_calls_check_receiver_and_arguments":
        proof_source = function_section(holder_text, "chv_check_named_callee")
        proof_edges = FIELD_UNKNOWN_CALL_EDGES
    elif name == "proof_chv_named_callees_cover_dispatch_routes":
        proof_source = function_section(holder_text, "chv_check_named_callee")
        proof_edges = CALLEE_DISPATCH_EDGES
    elif name == "proof_chv_indirect_calls_fail_closed":
        proof_source = function_section(holder_text, "chv_check_unknown_call")
        proof_edges = UNKNOWN_CALL_EDGES
    elif name == "proof_chv_summary_calls_check_reference_aliases":
        proof_source = function_section(holder_text, "chv_check_call_target")
        proof_edges = SUMMARY_CALL_EDGES
    elif name == "proof_chv_named_arguments_use_unknown_call_fallback":
        proof_source = function_section(holder_text, "chv_check_named_call")
        proof_edges = NAMED_CALL_EDGES
    elif name == "proof_sts_named_argument_calls_use_conservative_fallback":
        proof_source, proof_edges = unifier_source, NAMED_ARGUMENT_UNIFIER_EDGES
    elif name == "proof_chv_named_arguments_use_unknown_call_fallback":
        proof_source = function_section(holder_text, "chv_check_named_call")
        proof_edges = NAMED_CALL_EDGES
    elif name == "proof_sts_named_argument_calls_use_conservative_fallback":
        proof_source, proof_edges = unifier_source, NAMED_ARGUMENT_UNIFIER_EDGES
    elif name == "proof_chv_field_calls_use_unknown_fallback":
        proof_source = function_section(holder_text, "chv_check_named_callee")
        proof_edges = FIELD_UNKNOWN_CALL_EDGES
    elif name in ("proof_sts_match_statement_names_reach_fallback", "proof_sts_contract_expression_reaches_fallback"):
        proof_source, proof_edges = statement_collect_source, STATEMENT_COLLECTOR_EDGES
    elif name == "proof_sts_hidden_names_are_unified":
        proof_source, proof_edges = unifier_source, UNIFIER_FALLBACK_EDGES
    elif name == "proof_sts_nested_callee_calls_reach_unifier":
        proof_source, proof_edges = unifier_source, EXPRESSION_UNIFIER_EDGES
    else:
        proof_source, proof_edges = collect_source, EXPRESSION_EDGES
    if source_route_edges is not None:
        boolean_expressions = {
            "proof_chv_binary_operator_checks_both_operands": "receiver_checked and operand_checked and fallback_checked",
            "proof_chv_binary_operator_result_tracks_reference_operands": "not boolean_result and (left_alias or right_alias)",
            "proof_chv_binary_operator_result_tracks_view_operands": "not boolean_result and (left_may_be_view or right_may_be_view)",
            "proof_chv_binary_boolean_result_clears_view_taint": "boolean_result_classified and result_taint_cleared",
            "proof_chv_call_result_tracks_argument_view": "direct_result_may_be_owned or argument_may_be_owned",
            "proof_chv_binary_target_operators_skip_runtime_value_path": "target_operator and target_classified and right_walk_guarded and fallback_guarded",
            "proof_chv_comprehension_result_tracks_yielded_alias": "yielded_element_alias_checked and binder_alias_bound and body_alias_checked",
            "proof_chv_for_iterator_inherits_iterable_reference_alias": "binder_bound and (yielded_element_alias or mutable_slot_alias)",
            "proof_chv_getelse_recovery_termination_excludes_recovery_state": "guarded_path_joined and ((recovery_terminates and recovery_path_excluded and not recovery_path_joined and not recovery_value_joined) or (not recovery_terminates and recovery_path_joined and recovery_value_joined))",
            "proof_chv_scalar_sview_rebinding_prefers_latest_fact": "(flow_row_found and flow_scalar) or (not flow_row_found and initializer_scalar)",
        }
        validate_exact_boolean_theorem_source_routes(
            positive_text, name, tuple(routes), boolean_expressions[name],
            source_route_sources, source_route_edges)
    elif name == "proof_chv_static_effect_candidates_check_captures_and_arguments":
        validate_exact_boolean_theorem(positive_text, name, routes, "captures_checked and arguments_checked", proof_source, proof_edges)
    elif name == "proof_chv_comprehension_scope_masks_shadowed_reference":
        validate_exact_boolean_theorem(positive_text, name, routes, "reference_parameter and not binder_shadows_reference", proof_source, proof_edges)
    elif name == "proof_chv_method_calls_check_receiver_and_arguments":
        validate_exact_boolean_theorem(positive_text, name, routes, "receiver_checked and arguments_checked", proof_source, proof_edges)
    elif name == "proof_chv_indirect_calls_fail_closed":
        validate_exact_boolean_theorem(positive_text, name, routes, "reference_target_checked and owned_view_checked", proof_source, proof_edges)
    elif name == "proof_chv_view_alias_join_preserves_owned_fact":
        validate_exact_boolean_theorem(positive_text, name, routes, "left_branch_may_own or right_branch_may_own", proof_source, proof_edges)
    elif name == "proof_chv_aggregate_construct_keeps_field_view_taint":
        validate_exact_boolean_theorem(positive_text, name, routes, "field_walked and field_taint_joined and aggregate_taint_set", proof_source, proof_edges)
    elif name == "proof_chv_record_update_keeps_base_and_field_view_taint":
        validate_exact_boolean_theorem(positive_text, name, routes, "base_taint_kept and field_walked and field_taint_joined and aggregate_taint_set", proof_source, proof_edges)
    elif name == "proof_chv_projection_assignment_preserves_aggregate_taint":
        validate_exact_boolean_theorem(positive_text, name, routes, "rhs_may_be_view or ((compound_assignment or target_is_projection) and previous_root_may_be_view)", proof_source, proof_edges)
    elif name == "proof_chv_comprehension_result_tracks_yielded_view":
        validate_exact_boolean_theorem(positive_text, name, routes, "body_may_be_owned_view", proof_source, proof_edges)
    elif name == "proof_chv_comprehension_element_view_reaches_yielded_result":
        validate_exact_boolean_theorem(positive_text, name, routes, "collection_taint_reaches_iterable_binding and iterable_taint_reaches_binder and binder_taint_reaches_result", proof_source, proof_edges)
    elif name == "proof_chv_for_iterator_inherits_iterable_view_taint":
        validate_exact_boolean_theorem(positive_text, name, routes, "iterable_may_be_owned_view", proof_source, proof_edges)
    elif name == "proof_chv_for_iterator_inherits_iterable_reference_alias":
        validate_exact_boolean_theorem(positive_text, name, routes, "binder_bound and (yielded_element_alias or mutable_slot_alias)", proof_source, proof_edges)
    elif name == "proof_chv_comprehension_result_tracks_yielded_alias":
        validate_exact_boolean_theorem_source_routes(
            positive_text, name, tuple(routes),
            "yielded_element_alias_checked and binder_alias_bound and body_alias_checked",
            source_route_sources, source_route_edges)
    elif name == "proof_chv_method_result_tracks_receiver_or_arguments":
        validate_exact_boolean_theorem(positive_text, name, routes, "receiver_may_be_owned or arguments_may_be_owned", proof_source, proof_edges)
    elif name == "proof_chv_callable_result_tracks_argument_view":
        validate_exact_boolean_theorem(positive_text, name, routes, "argument_may_be_owned", proof_source, proof_edges)
    elif name == "proof_chv_call_result_tracks_argument_view":
        validate_exact_boolean_theorem(positive_text, name, routes, "direct_result_may_be_owned or argument_may_be_owned", proof_source, proof_edges)
    elif name == "proof_chv_static_effect_result_tracks_runtime_views":
        validate_exact_boolean_theorem(positive_text, name, routes, "runtime_child_may_be_owned", proof_source, proof_edges)
    elif name == "proof_chv_aggregate_field_projection_requires_tainted_root":
        validate_exact_boolean_theorem(positive_text, name, routes, "root_is_known and aggregate_may_contain_view", proof_source, proof_edges)
    elif name == "proof_chv_reference_alias_join_preserves_either_path":
        validate_exact_boolean_theorem(positive_text, name, routes, "left_path_may_alias or right_path_may_alias", proof_source, proof_edges)
    elif name == "proof_chv_reference_targets_cover_alias_routes":
        validate_exact_boolean_theorem(positive_text, name, routes, "direct_parameter and local_alias and call_result and projection_fallback and aggregate_alias", proof_source, proof_edges)
    elif name == "proof_chv_binary_operator_checks_both_operands":
        validate_exact_boolean_theorem(positive_text, name, routes, "receiver_checked and operand_checked and fallback_checked", proof_source, proof_edges)
    elif name == "proof_chv_index_overloads_check_receiver_and_keys":
        validate_exact_boolean_theorem(positive_text, name, routes, "receiver_checked and key_checked and call_checked and type_application_skipped", proof_source, proof_edges)
    elif name == "proof_chv_index_result_tracks_receiver_view":
        validate_exact_boolean_theorem(positive_text, name, routes, "receiver_may_be_view or (runtime_index_guarded and index_key_may_be_view)", proof_source, proof_edges)
    elif name == "proof_chv_indexn_result_tracks_receiver_only":
        validate_exact_boolean_theorem(positive_text, name, routes, "receiver_may_be_view", proof_source, proof_edges)
    elif name == "proof_chv_address_of_uses_operand_reference_provenance":
        validate_exact_boolean_theorem(positive_text, name, routes, "not boolean_not and operand_alias_checked", proof_source, proof_edges)
    elif name == "proof_chv_unary_negation_tracks_reference_operand":
        validate_exact_boolean_theorem(positive_text, name, routes, "not boolean_not and operand_alias_checked", proof_source, proof_edges)
    elif name == "proof_chv_unary_negation_visits_operand":
        validate_exact_boolean_theorem(positive_text, name, routes, "operand_checked", proof_source, proof_edges)
    elif name == "proof_chv_unary_negation_tracks_view_operand":
        validate_exact_boolean_theorem(positive_text, name, routes, "not boolean_not and operand_may_be_view", proof_source, proof_edges)
    elif name == "proof_chv_projection_fallback_requires_caller_reference":
        validate_exact_boolean_theorem(positive_text, name, routes, "caller_reference_exists", proof_source, proof_edges)
    elif name == "proof_chv_summary_calls_check_reference_aliases":
        validate_exact_boolean_theorem(positive_text, name, routes, "reference_alias_checked and owned_view_checked", proof_source, proof_edges)
    elif name in ("proof_chv_named_arguments_use_unknown_call_fallback", "proof_sts_named_argument_calls_use_conservative_fallback", "proof_chv_field_calls_use_unknown_fallback"):
        validate_or_theorem(positive_text, name, routes, proof_source, proof_edges)
    else:
        validate_or_theorem(positive_text, name, routes, proof_source, proof_edges)
if "children.extend(candidate.captures)" not in helper_body or "children.extend(arguments)" not in helper_body:
    raise SystemExit("static-effect proof inputs are not tied to helper children")

if tuple(sorted(explicit_match_arm_names(holder_scan_statements, "match statement:", "Stmt."))) != tuple(sorted(EXPECTED_STMT_NAMES)):
    raise SystemExit("holder-view local scanner is not exhaustive over Stmt")
if tuple(sorted(explicit_match_arm_names(holder_scan_expressions, "match expression:", "Expr."))) != tuple(sorted(EXPECTED_EXPR_NAMES)):
    raise SystemExit("holder-view local scanner is not exhaustive over Expr")
if tuple(sorted(explicit_match_arm_names(holder_walk_expressions, "match expression:", "Expr."))) != tuple(sorted(EXPECTED_EXPR_NAMES)):
    raise SystemExit("holder-view diagnostic walk is not exhaustive over Expr")
if tuple(sorted(explicit_match_arm_names(holder_walk_statements, "match statement:", "Stmt."))) != tuple(sorted(EXPECTED_STMT_NAMES)):
    raise SystemExit("holder-view diagnostic walk is not exhaustive over Stmt")
for source, edges, label in (
    (holder_scan_statements, HOLDER_SCAN_STATEMENT_EDGES, "holder-view local statement scan"),
    (holder_scan_expressions, HOLDER_SCAN_EXPRESSION_EDGES, "holder-view local expression scan"),
    (holder_walk_statements, HOLDER_WALK_STATEMENT_EDGES, "holder-view statement walk"),
    (holder_walk_expressions, HOLDER_WALK_EXPRESSION_EDGES, "holder-view expression walk"),
):
    validate_edge_set(source, edges, label)
validate_edge_set(holder_walk_expressions, CATCH_ARM_PROVENANCE_EDGES, "holder-view catch-arm provenance")
validate_edge_set(function_section(holder_text, "chv_expression_binding_facts"), EXPRESSION_BINDING_FACTS_OR_EDGES, "holder-view disjunction binder provenance")
validate_edge_set(holder_walk_statements, PARALLEL_ASSIGNMENT_FLOW_EDGES, "holder-view parallel-assignment provenance")
validate_edge_set(holder_walk_statements, FOR_ITERATOR_VIEW_TAINT_EDGES, "holder-view for-iterator view taint")
validate_edge_set(holder_walk_statements, FOR_ITERATOR_REF_ALIAS_EDGES, "holder-view for-iterator reference alias")
assignment_arm = match_arm_body(holder_walk_statements, "match statement:", "Stmt.Assign(target, operator, assigned_value, assign_pos):")
if assignment_arm is None:
    raise SystemExit("holder-view assignment arm is missing")
validate_ordered_source_lines(assignment_arm, (
    "if parallel_shape:",
    "for parallel_value in parallel_values |table, parallel_owned_views, parallel_alias_refs, parallel_contained_alias_refs, parallel_scalar_sviews, parallel_yield_scalar_sviews, flow, assigned_value_may_be_owned_view, assigned_value_may_alias_reference, assigned_value_may_contain_alias_reference| -> table:",
    "table <- chv_walk_expression(parallel_value, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)",
    "value_may_be_owned_view: bool = flow.last_value_may_be_owned_view",
    "parallel_owned_views.push(value_may_be_owned_view)",
    "assigned_value_may_be_owned_view <- assigned_value_may_be_owned_view or value_may_be_owned_view",
    "else:",
    "table <- chv_walk_expression(assigned_value, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)",
    "assigned_value_may_be_owned_view <- flow.last_value_may_be_owned_view",
    "chv_flow_bind_expression_binders(assigned_value, ref_params, flow, table)",
    "table <- chv_walk_expression(target, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)",
    "assigned_alias: bool = assigned_value_may_be_owned_view or ((operator != TokenKind.Assign or projection_assignment) and previous_may_owned_view)",
), "holder-view assignment taint order")
for_arm = match_arm_body(holder_walk_statements, "match statement:", "Stmt.For(bind, loop_variables, iterable, loop_body, _):")
if for_arm is None:
    raise SystemExit("holder-view for arm is missing")
validate_ordered_source_lines(for_arm, (
    "table <- chv_walk_expression(iterable, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)",
    "iterable_may_be_owned_view: bool = chv_iterable_element_may_be_owned_view(iterable, flow, view_names, view_values, flow.last_value_may_be_owned_view, 0)",
    "iterable_may_alias_reference: bool = chv_expression_may_alias_ref(iterable, ref_params, flow, table, 0)",
    "loop_element_may_alias_reference: bool = chv_iterable_element_may_alias_reference(iterable, ref_params, flow, table, 0)",
    "loop_element_may_contain_alias_reference: bool = chv_iterable_element_may_contain_alias_ref(iterable, ref_params, flow, table, 0)",
    "loop_variable_may_alias_reference: bool = loop_element_may_alias_reference or (bind == \"mutable\" and iterable_may_alias_reference)",
    "loop_flow: mutable CHVViewFlow = chv_flow_clone(flow)",
    "for loop_variable_index in 0..<loop_variables.count |loop_flow, loop_variables|:",
    "element_facts: (known: bool, may_owned_view: bool, may_alias_reference: bool, may_contain_alias_reference: bool, may_be_scalar_sview: bool, may_yield_scalar_sview: bool) = chv_iterable_binding_facts(iterable, loop_variable_index, loop_variables.count > 1, ref_params, flow, table, view_names, view_values)",
    "loop_variable: sview = loop_variables[loop_variable_index]",
    "loop_variable_may_be_owned_view: bool = element_facts.may_owned_view if element_facts.known else iterable_may_be_owned_view",
    "loop_variable_may_alias_reference: mutable bool = element_facts.may_alias_reference if element_facts.known else loop_element_may_alias_reference",
    "loop_variable_may_alias_reference <- loop_variable_may_alias_reference or (bind == \"mutable\" and iterable_may_alias_reference)",
    "loop_variable_may_contain_alias_reference: bool = element_facts.may_contain_alias_reference if element_facts.known else loop_element_may_contain_alias_reference",
    "chv_flow_bind(loop_flow, loop_variable, false, loop_variable_may_be_owned_view, loop_variable_may_alias_reference)",
    "loop_flow.may_contain_alias_reference[loop_index] <- loop_variable_may_contain_alias_reference if loop_index < loop_flow.names.count",
    "table <- chv_walk_statements(loop_body, in_region, ref_params, binders, owned, view_names, view_values, loop_flow, summary, table)",
    "chv_flow_merge(flow, loop_flow, branch_mark)",
), "holder-view for-iterator taint order")
validate_edge_set(holder_walk_expressions, BINARY_OPERATOR_FALLBACK_EDGES, "holder-view binary operator fallback")
validate_edge_set(function_section(holder_text, "chv_binary_operator_has_non_runtime_target"), (BINARY_NON_RUNTIME_TARGET_EDGES[0],), "holder-view non-runtime binary target classification")
validate_edge_set(holder_walk_expressions, ARRAY_VIEW_TAINT_EDGES, "holder-view array and tuple taint")
validate_edge_set(holder_walk_expressions, DICT_VIEW_TAINT_EDGES, "holder-view dictionary taint")
validate_edge_set(holder_walk_expressions, COMPREHENSION_VIEW_TAINT_EDGES, "holder-view comprehension result taint")
validate_edge_set(holder_walk_expressions, COMPREHENSION_BINDER_VIEW_TAINT_EDGES, "holder-view comprehension binder taint")
validate_edge_set(function_section(holder_text, "chv_is_owned_view"), IDENTIFIER_VIEW_TAINT_EDGES, "holder-view identifier taint lookup")
validate_edge_set(holder_walk_expressions, CONSTRUCT_VIEW_TAINT_EDGES, "holder-view constructed aggregate taint")
validate_edge_set(holder_walk_expressions, RECORD_UPDATE_VIEW_TAINT_EDGES, "holder-view record-update taint")
validate_edge_set(holder_walk_statements, ASSIGN_VIEW_TAINT_EDGES, "holder-view assigned aggregate taint")
validate_edge_set(function_section(holder_text, "chv_is_owned_view"), METHOD_CALL_VIEW_RESULT_EDGES, "holder-view method-call result taint")
validate_edge_set(function_section(holder_text, "chv_is_owned_view"), CALLABLE_VIEW_RESULT_EDGES, "holder-view callable result taint")
validate_edge_set(holder_walk_expressions, CALL_RESULT_VIEW_TAINT_EDGES, "holder-view call result taint")
validate_edge_set(holder_walk_expressions, STATIC_EFFECT_RESULT_VIEW_TAINT_EDGES, "holder-view static-effect result taint")
validate_edge_set(function_section(holder_text, "chv_place_root"), PLACE_ROOT_PROJECTION_EDGES, "holder-view projected assignment roots")
if compact("chv_flow_bind(flow, assigned_root, false, assigned_alias, assigned_alias_ref)") not in compact_code(holder_walk_statements):
    raise SystemExit("new projected assignment roots must join the view/reference flow")

effect_call_source = function_section(holder_text, "chv_check_static_effect_call")
validate_edge_set(effect_call_source, EFFECT_CANDIDATE_EDGES, "static-effect holder-call check")
validate_edge_set(effect_call_source, NAMED_ARGUMENT_STATIC_EFFECT_EDGES, "named-argument static-effect fallback")
validate_edge_set(unifier_source, NAMED_ARGUMENT_UNIFIER_EDGES, "named-argument store-through fallback")
reference_alias_source = function_section(holder_text, "chv_expression_may_alias_ref")
validate_edge_set(reference_alias_source, REF_ALIAS_HELPER_EDGES, "reference-alias expression classification")
validate_edge_set(function_section(holder_text, "chv_is_owned_view"), VIEW_ALIAS_BINARY_EDGES, "holder-view binary result classification")
validate_edge_set(function_section(holder_text, "chv_flow_set_merge"), REF_ALIAS_FLOW_MERGE_EDGES, "reference-alias branch join")
validate_edge_set(function_section(holder_text, "chv_check_call_target"), SUMMARY_CALL_EDGES, "summary-call reference target check")
scalar_reference_fallback = match_arm_body(reference_alias_source, "match argument:", "_:")
expected_scalar_reference_fallback = compact_code("""root: sview = chv_place_root(exclusivity_strip_address(argument).place)
if root == "":
    return false
index: usize = chv_flow_latest(flow, root)
if index < flow.names.count:
    return flow.may_alias_reference[index] or flow.may_contain_alias_reference[index]
return any reference_parameter in ref_params where reference_parameter == root""")
if scalar_reference_fallback is None or compact_code(scalar_reference_fallback) != expected_scalar_reference_fallback:
    raise SystemExit("scalar/non-place targets must not be treated as caller-reference aliases")
if "inner(id_holder(out), owned_view)" not in positive_text or "local_holder.slot" not in positive_text:
    raise SystemExit("reference alias proof must document call-result and projection cases")
if "&local_holder" not in positive_text:
    raise SystemExit("reference alias proof must document the local address-of control")
unary_alias_arm = match_arm_body(reference_alias_source, "match argument:", "Expr.Unary(operator, operand, _):")
if unary_alias_arm is None or compact_code(unary_alias_arm) != compact_code("return false if operator == TokenKind.Not\nreturn chv_expression_may_alias_ref(operand, ref_params, flow, table, depth + 1)"):
    raise SystemExit("logical Not must clear reference provenance while other unary operators retain it")
named_argument_detector = function_section(holder_text, "chv_call_has_named_arguments")
if compact_code(named_argument_detector) != compact_code("can Abort.Panic:\n    return any argument_name in argument_names where argument_name != \"\""):
    raise SystemExit("holder-view named-argument detection must recognize every nonempty label")
if compact("not chv_call_has_named_arguments(argument_names)") not in compact_code(function_section(holder_text, "chv_check_named_call")):
    raise SystemExit("holder-view named calls must bypass positional summary lookup")
if "chv_call_has_named_arguments(argument_names)" not in compact_code(effect_call_source):
    raise SystemExit("static-effect named calls must use the conservative unknown-call fallback")
callee_dispatch_source = function_section(holder_text, "chv_check_named_callee")
validate_edge_set(callee_dispatch_source, CALLEE_DISPATCH_EDGES, "holder-view callee dispatch")
validate_edge_set(function_section(holder_text, "chv_check_named_call"), NAMED_CALL_EDGES, "holder-view named-call resolution")
validate_edge_set(function_section(holder_text, "chv_check_unknown_call"), UNKNOWN_CALL_EDGES, "holder-view indirect-call fallback")
validate_edge_set(holder_walk_expressions, INDEX_OPERATOR_EDGES, "holder-view overloaded index fallback")
validate_edge_set(holder_walk_expressions, UNARY_NEGATION_EDGES, "holder-view unary negation fallback")
validate_edge_set(holder_walk_expressions, BINARY_VIEW_WALK_EDGES, "holder-view binary result provenance")
validate_edge_set(holder_walk_expressions, BINARY_RIGHT_VIEW_EDGES, "holder-view binary RHS provenance")
validate_edge_set(holder_walk_expressions, (BINARY_BOOLEAN_RESULT_EDGES[0], BINARY_BOOLEAN_RESULT_EDGES[3]), "holder-view boolean-result taint flow")
validate_edge_set(function_section(holder_text, "chv_binary_operator_returns_bool"), BINARY_BOOLEAN_RESULT_EDGES[1:3], "holder-view boolean operator classification")
validate_edge_set(function_section(holder_text, "chv_is_reinterpret_target_marker"), REINTERPRET_TARGET_MARKER_EDGES, "reinterpret target marker classification")
validate_edge_set(function_section(holder_text, "chv_is_owned_view"), INDEX_VIEW_RESULT_EDGES, "holder-view index result provenance")
owned_view_source = function_section(holder_text, "chv_is_owned_view")
validate_edge_set(owned_view_source, INDEXN_VIEW_RESULT_EDGES, "holder-view multi-index result provenance")
indexn_view_result_arm = match_arm_body(owned_view_source, "match argument:", "Expr.IndexN(object, arguments, _):")
expected_indexn_view_result_arm = compact_code("""# IndexN represents multi-index selection or generic application. Unlike
# single-key Index, it does not lower through the __index__ protocol, so
# selector/type arguments cannot become the returned view's storage.
return chv_is_owned_view(object, flow, depth + 1)""")
if indexn_view_result_arm is None or compact_code(indexn_view_result_arm) != expected_indexn_view_result_arm:
    raise SystemExit("IndexN result provenance must exclude selector and type argument taint")
validate_edge_set(holder_walk_expressions, INDEXN_VIEW_WALK_EDGES, "holder-view multi-index walk result provenance")
indexn_walk_arm = match_arm_body(holder_walk_expressions, "match expression:", "Expr.IndexN(object, arguments, _):")
expected_indexn_walk_arm = compact_code("""table <- chv_walk_expression(object, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)
object_may_be_owned_view: bool = flow.last_value_may_be_owned_view
if not index_receiver_is_type_application(object):
    for argument in arguments |table|:
        table <- chv_walk_expression(argument, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)
flow.last_value_may_be_owned_view <- object_may_be_owned_view or chv_is_owned_view(expression, flow, 0)""")
if indexn_walk_arm is None or compact_code(indexn_walk_arm) != expected_indexn_walk_arm:
    raise SystemExit("IndexN selectors must be visited without unknown-call dispatch or selector result taint")
call_callee_source = function_section(holder_text, "chv_walk_call_callee")
indexn_call_callee_arm = match_arm_body(call_callee_source, "match callee:", "Expr.IndexN(head, arguments, _):")
expected_indexn_call_callee_arm = compact_code("""table <- chv_walk_call_callee(head, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, receiver_owned_view, receiver_may_alias_reference, callee_may_be_owned_view, table)
head_may_be_owned_view: bool = callee_may_be_owned_view or chv_is_owned_view(head, flow, 0)
callee_may_be_owned_view <- head_may_be_owned_view
flow.last_value_may_be_owned_view <- callee_may_be_owned_view""")
if indexn_call_callee_arm is None or compact_code(indexn_call_callee_arm) != expected_indexn_call_callee_arm:
    raise SystemExit("IndexN call-callee type arguments must not be walked or treated as runtime result provenance")
validate_edge_set(function_section(holder_text, "chv_is_owned_view"), UNARY_VIEW_RESULT_EDGES, "holder-view unary result provenance")

if "if owned.count > 0" in compact_code(function_section(holder_text, "chv_walk_declarations")):
    raise SystemExit("holder-view walk must visit reference functions to reach nested lambda scopes")
holder_entry_source = function_section(holder_text, "check_call_holder_view_store")
if "returnifsummary.writable_function.count==0" in compact_code(holder_entry_source):
    raise SystemExit("unknown-call holder checks must run even when no named callee summary rows exist")
holder_summary_setup = compact("summary: StoreThroughSummary = chv_build_summary(file.top_decls, holders, reference_sites, table) can Global{Read,Write}")
holder_walk_setup = compact("table <- chv_walk_declarations(file.top_decls, summary, file.enum_annotations, table)")
if holder_summary_setup not in compact_code(holder_entry_source) or holder_walk_setup not in compact_code(holder_entry_source) or compact_code(holder_entry_source).find(holder_walk_setup) < compact_code(holder_entry_source).find(holder_summary_setup):
    raise SystemExit("holder-view call walk is no longer reached after summary construction")
holder_summary_source = function_section(holder_text, "chv_build_summary")
if "sts_declared_once" in compact_code(holder_summary_source):
    raise SystemExit("holder-view summaries must union every same-name overload body")
validate_edge_set(holder_summary_source, OVERLOAD_SUMMARY_EDGES, "holder-view overload summary")
validate_edge_set(function_section(holder_text, "chv_check_named_callee"), FIELD_UNKNOWN_CALL_EDGES, "callable field conservative fallback")
field_dispatch = function_section(holder_text, "chv_check_named_callee")
field_arm = match_arm_body(field_dispatch, "match callee:", "Expr.Field(receiver, _, _):")
if field_arm is None or "chv_check_named_call" in compact_code(field_arm):
    raise SystemExit("field calls must not dispatch by name without resolved-call identity")
if compact("comprehension_ref_params.push(outer_ref) if outer_ref != variable") not in compact_code(holder_walk_expressions):
    raise SystemExit("comprehension scope no longer masks a same-named outer reference parameter")
if compact("comprehension_binders.push(variable)") not in compact_code(holder_walk_expressions):
    raise SystemExit("comprehension scope no longer records its lexical binder")
owned_view_source = function_section(holder_text, "chv_is_owned_view")
validate_edge_set(owned_view_source, FIELD_PROJECTION_VIEW_TAINT_EDGES, "holder-view aggregate field projection")
field_projection_arm = match_arm_body(owned_view_source, "match argument:", "Expr.Field(_, _, _):")
expected_field_projection_arm = compact_code("""root_name: sview = chv_place_root(argument)
index: usize = chv_flow_latest(flow, root_name) if root_name != \"\" else flow.names.count
return index < flow.names.count and flow.may_owned_view[index]""")
if field_projection_arm is None or compact_code(field_projection_arm) != expected_field_projection_arm:
    raise SystemExit("aggregate field projections must inherit view taint from their root binding")
if "constCHV_DIAGNOSTIC_ARGUMENT_NUMBER_BASE:usize=1" not in compact_code(holder_text):
    raise SystemExit("holder-view diagnostic argument numbering must use a named constant")
if "ifdepth>" in compact_code(owned_view_source) or "ifdepth>" in compact_code(function_section(holder_text, "chv_expression_may_alias_ref")):
    raise SystemExit("AST nesting alone must not manufacture owned-view or reference provenance")
if "ifdepth>" in compact_code(function_section(holder_text, "chv_call_method_info")):
    raise SystemExit("transparent callee nesting must preserve view-producing method identity")
if "flow.may_owned_view[index]" not in compact_code(owned_view_source):
    raise SystemExit("holder-view alias lookup must read the latest flow binding")
if "flow.owned[index]orflow.may_owned_view[index]" not in compact_code(owned_view_source):
    raise SystemExit("view conversions and slices must inherit view provenance from alias roots")

negative_parameters = {
    "match_guard_name_is_dropped": "guard_has_name",
    "dictionary_key_name_is_dropped": "key_has_name",
    "contract_call_is_dropped": "call_is_present",
    "nested_callee_call_is_ignored": "callee_call_is_present",
    "static_effect_candidate_is_ignored": "candidate_call_is_present",
    "ambiguous_owned_view_is_assumed_safe": "view_binding_may_be_owned",
    "overload_store_row_is_ignored": "overload_body_has_store",
    "method_receiver_is_ignored": "receiver_store_is_present",
    "indirect_call_is_assumed_safe": "reference_and_view_are_present",
    "named_arguments_are_treated_as_positional": "named_argument_is_present",
    "callable_field_is_assumed_ufcs": "ufcs_candidate_is_missing",
    "scalar_target_is_assumed_reference": "scalar_target_is_present",
}
for name, parameter in negative_parameters.items():
    body = compact_code(function_section(negative_text, name))
    expected = compact_code(f"requires {parameter}\nensure result == false\nreturn {parameter}")
    if body != expected:
        raise SystemExit(f"{name} no longer expresses its rejected dropped-child claim")

if not __debug__:
    raise SystemExit("run without Python -O")

try:
    product = require_current_product(BIN, PROVER)
except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
    raise SystemExit(f"proof product provenance check failed: {error}") from error
if product.get("compile_mode") != "strict":
    raise SystemExit("store-through AST proof requires a strict proof build")

stage1_product = Path(product["compiler"]["product"]["path"]).resolve(strict=True)
stage1_provenance = Path(str(stage1_product) + ".provenance.json").resolve(strict=True)
source_closure = source_include_closure([POSITIVE, NEGATIVE])
inputs = list(dict.fromkeys([
    BIN, MANIFEST, MANIFEST_CHECKSUM, PROVER / "ELISA_COMPILER_REV",
    stage1_product, stage1_provenance, Path(__file__), HERE / "proof_product_gate.py",
    SUMMARY, HOLDER_SOURCE, AST_NODES, AST_SIDE_TABLES, EFFECT_SHAPE, POSITIVE, NEGATIVE, *source_closure,
]))
hashes_before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}


def run(path: Path) -> tuple[int, dict]:
    process = subprocess.run([str(BIN), "--json", str(path)], capture_output=True,
                             text=True, timeout=PROOF_TIMEOUT_SECONDS)
    report = json.loads(process.stdout)
    assert report["summary"]["semantic_errors"] == 0, report.get("semantic_diagnostics")
    assert not report["trust"]["trusted_assumptions"]
    assert report["replay"]["gaps"] == 0
    assert report["replay"]["certificates"] == report["replay"]["replayed"] == report["summary"]["proven"]
    return process.returncode, report


code, positive = run(POSITIVE)
assert code == 0 and positive["status"] == positive["verification_state"] == "proved"
assert positive["summary"]["obligations"] == positive["summary"]["proven"] == len(positive_names)
assert not positive["findings"]
assert positive_names <= {row["name"] for row in positive["declaration_details"] if row.get("verified")}
assert positive == run(POSITIVE)[1], "store-through proof report changed across identical runs"

code, negative = run(NEGATIVE)
assert code == 1 and negative["status"] == "failed"
assert negative["summary"]["obligations"] == negative["summary"]["proven"] + negative["summary"]["failed"]
assert negative["summary"]["failed"] == len(negative_names)
assert negative["summary"]["proven"] == 0
assert negative["replay"]["certificates"] == negative["replay"]["replayed"] == negative["summary"]["failed"]
assert negative["replay"]["gaps"] == 0
assert not negative["trust"]["trusted_assumptions"]
assert not negative["findings"]
assert negative_names <= {row["name"] for row in negative["declaration_details"] if row.get("verified")}
assert negative == run(NEGATIVE)[1], "store-through negative report changed across identical runs"

hashes_after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
assert hashes_before == hashes_after, "proof or source inputs changed during replay"
