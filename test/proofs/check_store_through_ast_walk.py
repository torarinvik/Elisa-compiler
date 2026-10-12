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
    "MatchArm": tuple("pattern:Pattern body:darray[Stmt] guard:Expr pos:Pos".split()),
    "DictEntry": tuple("key:Expr value:Expr".split()),
    "FieldInit": tuple("name:sview value:Expr is_copy_base:bool".split()),
    "StaticEffectCandidate": tuple("effect_type:Expr callee:sview captures:darray[Expr] effect_identity_id:u32 handler_identity_id:u32 callee_owner:sview".split()),
}


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
        if value.startswith(prefix) and value.endswith(":"):
            match = re.match(r"[A-Za-z_][A-Za-z0-9_]*", value[len(prefix):])
            if match:
                names.append(match.group(0))
    return tuple(names)


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
                if (lines[index].strip() == child or lines[index].strip().startswith(child))
                and len(lines[index]) - len(lines[index].lstrip(" \t")) == parent_indent + 4]
    return len(children) == 1


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
                if (lines[index].strip() == child or lines[index].strip().startswith(child))
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
    ("Expr.StaticEffectCall(_, _, candidates, arguments, _, _):", "for child in Ast::effect_runtime_children(candidates, arguments) |out|:"),
    ("for child in Ast::effect_runtime_children(candidates, arguments) |out|:", "sts_collect_names(child, out)"),
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
    ("Expr.Comprehension(_, iterable, condition, body, _):", "sts_collect_names(iterable, out)"),
    ("Expr.Comprehension(_, iterable, condition, body, _):", "sts_collect_names(condition, out)"),
    ("Expr.Comprehension(_, iterable, condition, body, _):", "sts_collect_names(body, out)"),
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
    ("Stmt.Block(_, _, _, body, _):", "sts_collect_statement_names(body, out)"),
    ("Stmt.VarDecl(_, _, value, _):", "sts_collect_names(value, out)"),
    ("Stmt.Assign(target, _, value, _):", "sts_collect_names(target, out)"),
    ("Stmt.Assign(target, _, value, _):", "sts_collect_names(value, out)"),
    ("Stmt.If(condition, then_body, else_body, _):", "sts_collect_names(condition, out)"),
    ("Stmt.If(condition, then_body, else_body, _):", "sts_collect_statement_names(then_body, out)"),
    ("Stmt.If(condition, then_body, else_body, _):", "sts_collect_statement_names(else_body, out)"),
    ("Stmt.While(condition, body, _):", "sts_collect_names(condition, out)"),
    ("Stmt.While(condition, body, _):", "sts_collect_statement_names(body, out)"),
    ("Stmt.For(_, _, iterable, body, _):", "sts_collect_names(iterable, out)"),
    ("Stmt.For(_, _, iterable, body, _):", "sts_collect_statement_names(body, out)"),
    ("Stmt.Return(value, _):", "sts_collect_names(return_value, out)"),
    ("Stmt.Match(scrutinee, arms, _):", "sts_collect_names(scrutinee, out)"),
    ("Stmt.Match(scrutinee, arms, _):", "for arm in arms |out|:"),
    ("for arm in arms |out|:", "sts_collect_names(arm.guard, out)"),
    ("for arm in arms |out|:", "sts_collect_statement_names(arm.body, out)"),
    ("Stmt.Contract(_, expression, _):", "sts_collect_names(expression, out)"),
)

STATEMENT_UNIFIER_EDGES = (
    ("Stmt.VarDecl(declared_name, _, declared_value, _):", "sts_unify_bound(declared_name, declared_value, summary, has_unreadable_binder, function_owner, reference_sites, table, names, classes)"),
    ("Stmt.Assign(assign_target, _, assign_value, _):", "sts_collect_names(assign_target, assign_names)"),
    ("Stmt.Assign(assign_target, _, assign_value, _):", "sts_collect_names(assign_value, assign_names)"),
    ("Stmt.Assign(assign_target, _, assign_value, _):", "sts_unify_all(names, classes, assign_names)"),
    ("Stmt.Assign(assign_target, _, assign_value, _):", "sts_unify_calls(assign_target, summary, has_unreadable_binder, function_owner, reference_sites, table, names, classes)"),
    ("Stmt.Assign(assign_target, _, assign_value, _):", "sts_unify_calls(assign_value, summary, has_unreadable_binder, function_owner, reference_sites, table, names, classes)"),
    ("Stmt.Expr(statement_value, _):", "sts_unify_calls(statement_value, summary, has_unreadable_binder, function_owner, reference_sites, table, names, classes)"),
    ("Stmt.Return(returned, _):", "if returned is returned_value:"),
    ("if returned is returned_value:", "sts_unify_calls(returned_value, summary, has_unreadable_binder, function_owner, reference_sites, table, names, classes)"),
    ("Stmt.If(condition, then_body, else_body, _):", "sts_unify_calls(condition, summary, has_unreadable_binder, function_owner, reference_sites, table, names, classes)"),
    ("Stmt.If(condition, then_body, else_body, _):", "sts_statements(then_body, summary, has_unreadable_binder, function_owner, reference_sites, table, names, classes)"),
    ("Stmt.If(condition, then_body, else_body, _):", "sts_statements(else_body, summary, has_unreadable_binder, function_owner, reference_sites, table, names, classes)"),
    ("Stmt.While(condition, loop_body, _):", "sts_unify_calls(condition, summary, has_unreadable_binder, function_owner, reference_sites, table, names, classes)"),
    ("Stmt.While(condition, loop_body, _):", "sts_statements(loop_body, summary, has_unreadable_binder, function_owner, reference_sites, table, names, classes)"),
    ("Stmt.For(_, loop_variables, iterable, loop_body, _):", "for loop_variable in loop_variables |names, classes, reference_sites|:"),
    ("for loop_variable in loop_variables |names, classes, reference_sites|:", "sts_unify_bound(loop_variable, iterable, summary, has_unreadable_binder, function_owner, reference_sites, table, names, classes)"),
    ("Stmt.For(_, loop_variables, iterable, loop_body, _):", "sts_unify_calls(iterable, summary, has_unreadable_binder, function_owner, reference_sites, table, names, classes)"),
    ("Stmt.For(_, loop_variables, iterable, loop_body, _):", "sts_statements(loop_body, summary, has_unreadable_binder, function_owner, reference_sites, table, names, classes)"),
    ("Stmt.Block(_, _, _, block_body, _):", "sts_statements(block_body, summary, has_unreadable_binder, function_owner, reference_sites, table, names, classes)"),
    ("Stmt.Match(scrutinee, arms, _):", "sts_unify_calls(scrutinee, summary, has_unreadable_binder, function_owner, reference_sites, table, names, classes)"),
    ("Stmt.Match(scrutinee, arms, _):", "for arm in arms |names, classes, reference_sites|:"),
    ("for arm in arms |names, classes, reference_sites|:", "sts_unify_calls(arm.guard, summary, has_unreadable_binder, function_owner, reference_sites, table, names, classes)"),
    ("for arm in arms |names, classes, reference_sites|:", "sts_statements(arm.body, summary, has_unreadable_binder, function_owner, reference_sites, table, names, classes)"),
    ("Stmt.Contract(_, expression, _):", "sts_unify_calls(expression, summary, has_unreadable_binder, function_owner, reference_sites, table, names, classes)"),
)

EXPRESSION_UNIFIER_EDGES = (
    ("Expr.Call(callee, arguments, argument_names, _):", "sts_unify_calls(callee, summary, has_unreadable_binder, function_owner, reference_sites, table, names, classes)"),
    ("Expr.Call(callee, arguments, argument_names, _):", "for argument in arguments |names, classes, reference_sites|:"),
    ("for argument in arguments |names, classes, reference_sites|:", "sts_unify_calls(argument, summary, has_unreadable_binder, function_owner, reference_sites, table, names, classes)"),
    ("Expr.Ident(callee_name, callee_position):", "shadowed: bool = borrow_reference_site_is_local(reference_sites, function_owner, callee_position, table) or has_unreadable_binder"),
    ("Expr.Ident(callee_name, callee_position):", "if sts_is_declared(summary, callee_name) and not shadowed and not (any argument_name in argument_names where argument_name != \"\"):", 0),
    ("Expr.Field(object, _, _):", "sts_unify_calls(object, summary, has_unreadable_binder, function_owner, reference_sites, table, names, classes)"),
    ("Expr.Index(object, index, _):", "sts_unify_calls(object, summary, has_unreadable_binder, function_owner, reference_sites, table, names, classes)"),
    ("Expr.Index(object, index, _):", "sts_unify_calls(index, summary, has_unreadable_binder, function_owner, reference_sites, table, names, classes)"),
    ("Expr.Binary(left, _, right, _):", "sts_unify_calls(left, summary, has_unreadable_binder, function_owner, reference_sites, table, names, classes)"),
    ("Expr.Binary(left, _, right, _):", "sts_unify_calls(right, summary, has_unreadable_binder, function_owner, reference_sites, table, names, classes)"),
    ("Expr.Unary(_, operand, _):", "sts_unify_calls(operand, summary, has_unreadable_binder, function_owner, reference_sites, table, names, classes)"),
    ("Expr.Move(operand, _):", "sts_unify_calls(operand, summary, has_unreadable_binder, function_owner, reference_sites, table, names, classes)"),
    ("Expr.Paren(inner, _):", "sts_unify_calls(inner, summary, has_unreadable_binder, function_owner, reference_sites, table, names, classes)"),
    ("Expr.If(condition, then_value, else_value, _):", "sts_unify_calls(condition, summary, has_unreadable_binder, function_owner, reference_sites, table, names, classes)"),
    ("Expr.If(condition, then_value, else_value, _):", "sts_unify_calls(then_value, summary, has_unreadable_binder, function_owner, reference_sites, table, names, classes)"),
    ("Expr.If(condition, then_value, else_value, _):", "sts_unify_calls(else_value, summary, has_unreadable_binder, function_owner, reference_sites, table, names, classes)"),
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
    ("Expr.StaticEffectCall(_, _, candidates, arguments, _, _):", "for child in Ast::effect_runtime_children(candidates, arguments) |binders, owned, view_names, view_values|:"),
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
    ("Expr.Comprehension(variable, iterable, condition, body, _):", "chv_scan_expression_locals(iterable, in_region, binders, owned, view_names, view_values)"),
    ("Expr.Comprehension(variable, iterable, condition, body, _):", "comprehension_binders.push(variable)"),
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
    ("Stmt.Assign(target, operator, assigned_value, _):", "table <- chv_walk_expression(target, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Stmt.Assign(target, operator, assigned_value, _):", "table <- chv_walk_expression(assigned_value, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Stmt.Return(value, _):", "table <- chv_walk_expression(return_value, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table) if value is return_value"),
    ("Stmt.If(condition, then_body, else_body, _):", "table <- chv_walk_expression(condition, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Stmt.If(condition, then_body, else_body, _):", "table <- chv_walk_statements(then_body, in_region, ref_params, binders, owned, view_names, view_values, then_flow, summary, table)"),
    ("Stmt.If(condition, then_body, else_body, _):", "table <- chv_walk_statements(else_body, in_region, ref_params, binders, owned, view_names, view_values, else_flow, summary, table)"),
    ("Stmt.While(condition, loop_body, _):", "table <- chv_walk_expression(condition, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Stmt.While(condition, loop_body, _):", "table <- chv_walk_statements(loop_body, in_region, ref_params, binders, owned, view_names, view_values, loop_flow, summary, table)"),
    ("Stmt.For(_, loop_variables, iterable, loop_body, _):", "table <- chv_walk_expression(iterable, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Stmt.For(_, loop_variables, iterable, loop_body, _):", "table <- chv_walk_statements(loop_body, in_region, ref_params, binders, owned, view_names, view_values, loop_flow, summary, table)"),
    ("Stmt.Block(kind, _, binding, block_body, _):", "table <- chv_walk_statements(block_body, in_region or kind == \"region\" or kind == \"in\", ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Stmt.Match(scrutinee, arms, _):", "table <- chv_walk_expression(scrutinee, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Stmt.Match(scrutinee, arms, _):", "for arm in arms |table| -> table:"),
    ("for arm in arms |table| -> table:", "table <- chv_walk_expression(arm.guard, in_region, ref_params, binders, owned, view_names, view_values, arm_flow, summary, table)"),
    ("for arm in arms |table| -> table:", "table <- chv_walk_statements(arm.body, in_region, ref_params, binders, owned, view_names, view_values, arm_flow, summary, table)"),
    ("Stmt.Contract(_, expression, _):", "table <- chv_walk_expression(expression, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
)

HOLDER_WALK_EXPRESSION_EDGES = (
    ("Expr.Call(callee, arguments, _, _):", "table <- chv_walk_call_callee(callee, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, receiver_may_be_owned_view, receiver_may_alias_reference, table)"),
    ("Expr.Call(callee, arguments, _, _):", "for argument in arguments |table| -> table:"),
    ("for argument in arguments |table| -> table:", "argument_owned_views.push(flow.last_value_may_be_owned_view)", 0),
    ("for argument in arguments |table| -> table:", "argument_may_alias_refs.push(chv_expression_may_alias_ref(argument, ref_params, flow, 0))", 0),
    ("Expr.Call(callee, arguments, _, _):", "table <- chv_check_call(expression, argument_owned_views, argument_may_alias_refs, receiver_may_be_owned_view, receiver_may_alias_reference, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.StaticEffectCall(_, _, candidates, arguments, argument_names, _):", "runtime_children: darray[Ast::Expr] = Ast::effect_runtime_children(candidates, arguments)"),
    ("Expr.StaticEffectCall(_, _, candidates, arguments, argument_names, _):", "for child in runtime_children |table, runtime_owned_views, runtime_may_alias_refs|:"),
    ("for child in runtime_children |table, runtime_owned_views, runtime_may_alias_refs|:", "runtime_owned_views.push(flow.last_value_may_be_owned_view)"),
    ("for child in runtime_children |table, runtime_owned_views, runtime_may_alias_refs|:", "runtime_may_alias_refs.push(chv_expression_may_alias_ref(child, ref_params, flow, 0))"),
    ("Expr.StaticEffectCall(_, _, candidates, arguments, argument_names, _):", "chv_check_static_effect_call(candidates, arguments, argument_names, runtime_owned_views, runtime_may_alias_refs, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.Field(object, _, _):", "table <- chv_walk_expression(object, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.Scope(base, _, _):", "table <- chv_walk_expression(base, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.Index(object, index, _):", "table <- chv_walk_expression(object, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.Index(object, index, _):", "table <- chv_walk_expression(index, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table) if not index_receiver_is_type_application(object)"),
    ("Expr.Slice(object, low, high, _):", "table <- chv_walk_expression(low, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.Slice(object, low, high, _):", "table <- chv_walk_expression(high, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.IndexN(object, arguments, _):", "for argument in arguments |table| -> table:"),
    ("Expr.Binary(left, _, right, _):", "table <- chv_walk_expression(left, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.Binary(left, _, right, _):", "table <- chv_walk_expression(right, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.Binary(left, _, right, _):", "binary_arguments: darray[Ast::Expr] = [left, right]"),
    ("Expr.Binary(left, _, right, _):", "binary_owned_views: darray[bool] = [left_may_be_owned_view, right_may_be_owned_view]"),
    ("Expr.Binary(left, _, right, _):", "binary_alias_refs: darray[bool] = [left_may_alias_ref, right_may_alias_ref]"),
    ("Expr.Binary(left, _, right, _):", "chv_check_unknown_call(binary_arguments, binary_owned_views, binary_alias_refs, ref_params, binders, owned, view_names, view_values, flow, table)"),
    ("Expr.Unary(_, operand, _):", "table <- chv_walk_expression(operand, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.Move(operand, _):", "table <- chv_walk_expression(operand, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.RegionNew(operand, _, _):", "table <- chv_walk_expression(operand, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.Paren(inner, _):", "table <- chv_walk_expression(inner, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.Array(elements, _):", "for element in elements |table| -> table:"),
    ("Expr.Tuple(elements, _):", "for element in elements |table| -> table:"),
    ("Expr.SetLit(elements, _):", "for element in elements |table| -> table:"),
    ("Expr.DictLit(entries, _):", "for entry in entries |table| -> table:"),
    ("for entry in entries |table| -> table:", "table <- chv_walk_expression(entry.key, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("for entry in entries |table| -> table:", "table <- chv_walk_expression(entry.value, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.Construct(_, fields, _):", "for field in fields |table| -> table:"),
    ("Expr.RecordUpdate(base, fields, _):", "table <- chv_walk_expression(base, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.If(condition, then_value, else_value, _):", "table <- chv_walk_expression(condition, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.If(condition, then_value, else_value, _):", "table <- chv_walk_expression(then_value, in_region, ref_params, binders, owned, view_names, view_values, then_flow, summary, table)"),
    ("Expr.If(condition, then_value, else_value, _):", "table <- chv_walk_expression(else_value, in_region, ref_params, binders, owned, view_names, view_values, else_flow, summary, table)"),
    ("Expr.Match(scrutinee, arms, _):", "for arm in arms |table| -> table:"),
    ("Expr.Catch(guarded, arms, _):", "table <- chv_walk_expression(guarded, in_region, ref_params, binders, owned, view_names, view_values, guarded_flow, summary, table)"),
    ("Expr.Catch(guarded, arms, _):", "for arm in arms |table| -> table:"),
    ("for arm in arms |table| -> table:", "table <- chv_walk_expression(arm.guard, in_region, ref_params, binders, owned, view_names, view_values, arm_flow, summary, table)", 0),
    ("for arm in arms |table| -> table:", "table <- chv_walk_expression(arm.guard, in_region, ref_params, binders, owned, view_names, view_values, arm_flow, summary, table)", 1),
    ("for arm in arms |table| -> table:", "table <- chv_walk_statements(arm.body, in_region, ref_params, binders, owned, view_names, view_values, arm_flow, summary, table)", 0),
    ("for arm in arms |table| -> table:", "table <- chv_walk_statements(arm.body, in_region, ref_params, binders, owned, view_names, view_values, arm_flow, summary, table)", 1),
    ("Expr.Comprehension(variable, iterable, condition, body, _):", "table <- chv_walk_expression(iterable, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.Comprehension(variable, iterable, condition, body, _):", "for outer_ref in ref_params |comprehension_ref_params|:"),
    ("for outer_ref in ref_params |comprehension_ref_params|:", "comprehension_ref_params.push(outer_ref) if outer_ref != variable"),
    ("Expr.Comprehension(variable, iterable, condition, body, _):", "comprehension_binders.push(variable)"),
    ("Expr.Comprehension(variable, iterable, condition, body, _):", "table <- chv_walk_expression(condition, in_region, comprehension_ref_params, comprehension_binders, comprehension_owned, comprehension_view_names, comprehension_view_values, comprehension_flow, summary, table)"),
    ("Expr.Comprehension(variable, iterable, condition, body, _):", "table <- chv_walk_expression(body, in_region, comprehension_ref_params, comprehension_binders, comprehension_owned, comprehension_view_names, comprehension_view_values, comprehension_flow, summary, table)"),
    ("Expr.Refinement(base, predicate, _):", "table <- chv_walk_expression(base, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.Refinement(base, predicate, _):", "table <- chv_walk_expression(predicate, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.GetElse(guarded, recovery, _):", "table <- chv_walk_expression(guarded, in_region, ref_params, binders, owned, view_names, view_values, guarded_flow, summary, table)"),
    ("Expr.GetElse(guarded, recovery, _):", "table <- chv_walk_statements(recovery, in_region, ref_params, binders, owned, view_names, view_values, recovery_flow, summary, table)"),
    ("Expr.Lambda(parameters, body, _):", "for outer_ref in ref_params |lambda_ref_params, parameters|:"),
    ("Expr.Lambda(parameters, body, _):", "table <- chv_walk_statements(body, in_region, lambda_ref_params, lambda_binders, lambda_owned, lambda_view_names, lambda_view_values, lambda_flow, summary, table)"),
    ("Expr.Block(block_statements, block_value, _, _):", "table <- chv_walk_statements(block_statements, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.Block(block_statements, block_value, _, _):", "table <- chv_walk_expression(block_value, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
)

EFFECT_CANDIDATE_EDGES = (
    ("for candidate in candidates |table| -> table:", "candidate_arguments.extend(candidate.captures)"),
    ("for candidate in candidates |table| -> table:", "candidate_arguments.extend(arguments)"),
    ("for candidate in candidates |table| -> table:", "chv_check_call_target(candidate.callee, candidate_arguments, candidate_owned_views, candidate_may_alias_refs, ref_params, binders, owned, view_names, view_values, flow, summary, table) if not chv_call_has_named_arguments(argument_names)"),
)

VIEW_FLOW_MERGE_EDGES = (
    ("while index < visible_count and index < target.names.count and index < left.names.count and index < right.names.count |index, target, left, right|:", "target.may_owned_view[index] <- left.may_owned_view[index] or right.may_owned_view[index]"),
)

REF_ALIAS_FLOW_MERGE_EDGES = (
    ("while index < visible_count and index < target.names.count and index < left.names.count and index < right.names.count |index, target, left, right|:", "target.may_alias_reference[index] <- left.may_alias_reference[index] or right.may_alias_reference[index]"),
)

REF_ALIAS_HELPER_EDGES = (
    ("_:", "return true if any reference_parameter in ref_params where reference_parameter == root"),
    ("_:", "return index < flow.names.count and flow.may_alias_reference[index]"),
    ("Expr.Call(_, _, _, _):", "return ref_params.count > 0"),
    ("Expr.Binary(left, _, right, _):", "return chv_expression_may_alias_ref(left, ref_params, flow, depth + 1) or chv_expression_may_alias_ref(right, ref_params, flow, depth + 1)"),
    ("Expr.Field(_, _, _) | Expr.Index(_, _, _) | Expr.IndexN(_, _, _) | Expr.Slice(_, _, _, _) | Expr.Block(_, _, _, _) | Expr.GetElse(_, _, _) | Expr.Match(_, _, _) | Expr.Catch(_, _, _) | Expr.StaticEffectCall(_, _, _, _, _, _):", "return ref_params.count > 0"),
)

VIEW_ALIAS_BINARY_EDGES = (
    ("Expr.Binary(left, _, right, _):", "return chv_is_owned_view(left, flow, depth + 1) or chv_is_owned_view(right, flow, depth + 1)"),
)

INDEX_OPERATOR_EDGES = (
    ("Expr.Index(object, index, _):", "table <- chv_walk_expression(object, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.Index(object, index, _):", "if not index_receiver_is_type_application(object):"),
    ("if not index_receiver_is_type_application(object):", "table <- chv_walk_expression(index, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)", 0),
    ("if not index_receiver_is_type_application(object):", "chv_check_unknown_call([object, index], [object_may_be_owned_view, index_may_be_owned_view], [object_may_alias_ref, index_may_alias_ref], ref_params, binders, owned, view_names, view_values, flow, table)", 0),
    ("Expr.IndexN(object, arguments, _):", "table <- chv_walk_expression(object, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.IndexN(object, arguments, _):", "indexed_arguments: mutable darray[Ast::Expr] = [object]"),
    ("Expr.IndexN(object, arguments, _):", "if not index_receiver_is_type_application(object):"),
    ("if not index_receiver_is_type_application(object):", "for argument in arguments |table, indexed_arguments, indexed_owned_views, indexed_alias_refs|:", 1),
    ("for argument in arguments |table, indexed_arguments, indexed_owned_views, indexed_alias_refs|:", "table <- chv_walk_expression(argument, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("for argument in arguments |table, indexed_arguments, indexed_owned_views, indexed_alias_refs|:", "indexed_arguments.push(argument)"),
    ("for argument in arguments |table, indexed_arguments, indexed_owned_views, indexed_alias_refs|:", "indexed_owned_views.push(flow.last_value_may_be_owned_view)"),
    ("for argument in arguments |table, indexed_arguments, indexed_owned_views, indexed_alias_refs|:", "indexed_alias_refs.push(chv_expression_may_alias_ref(argument, ref_params, flow, 0))"),
    ("if not index_receiver_is_type_application(object):", "chv_check_unknown_call(indexed_arguments, indexed_owned_views, indexed_alias_refs, ref_params, binders, owned, view_names, view_values, flow, table)", 1),
)

INDEX_VIEW_RESULT_EDGES = (
    ("Expr.Index(object, _, _):", "return chv_is_owned_view(object, flow, depth + 1)"),
    ("Expr.IndexN(object, _, _):", "return chv_is_owned_view(object, flow, depth + 1)"),
)

UNARY_NEGATION_EDGES = (
    ("Expr.Unary(operator, operand, _):", "table <- chv_walk_expression(operand, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.Unary(operator, operand, _):", "operand_may_be_owned_view: bool = flow.last_value_may_be_owned_view"),
    ("Expr.Unary(operator, operand, _):", "operand_may_alias_ref: bool = chv_expression_may_alias_ref(operand, ref_params, flow, 0)"),
    ("Expr.Unary(operator, operand, _):", "if operator == TokenKind.Minus:"),
    ("if operator == TokenKind.Minus:", "chv_check_unknown_call([operand], [operand_may_be_owned_view], [operand_may_alias_ref], ref_params, binders, owned, view_names, view_values, flow, table)"),
    ("Expr.Unary(operator, operand, _):", "flow.last_value_may_be_owned_view <- chv_is_owned_view(expression, flow, 0)"),
)

UNARY_VIEW_RESULT_EDGES = (
    ("Expr.Unary(_, operand, _):", "return chv_is_owned_view(operand, flow, depth + 1)"),
)

REF_ALIAS_ADDRESS_EDGES = (
    ("Expr.Unary(_, operand, _):", "return chv_expression_may_alias_ref(operand, ref_params, flow, depth + 1)"),
)

SUMMARY_CALL_EDGES = (
    ("while target < call_arguments.count |target, table| -> table:", "if sts_is_writable(summary, callee_name, target):"),
    ("if sts_is_writable(summary, callee_name, target):", "if chv_alias_reference_at(call_arguments, argument_may_alias_refs, target, ref_params, flow):"),
    ("while source < call_arguments.count |source, table| -> table:", "if source != target and sts_has_pair(summary, callee_name, target, source):"),
    ("if source != target and sts_has_pair(summary, callee_name, target, source):", "if not source_checked[source]:"),
    ("if not source_checked[source]:", "source_is_owned_view[source] <- chv_owned_view_at(call_arguments, argument_owned_views, source, flow)"),
)

OVERLOAD_SUMMARY_EDGES = (
    ("for function in functions |summary, summarised|:", "match function:"),
    ("Decl.Func(function_name, function_parameters, _, _, _, _, _):", "for parameter in function_parameters |position, writable_found, summary|:"),
    ("Decl.Func(function_name, function_parameters, _, _, _, _, _):", "summarised.push(function) if writable_found and function_parameters.count > 1"),
    ("for function in summarised |more_rows, summary|:", "match function:"),
    ("Decl.Func(function_name, function_parameters, _, function_body, _, _, _):", "more_rows <- true if (sts_summarise_function(function_name, function_parameters, function_body, summary) can Global{Read,Write})"),
)

CALLEE_DISPATCH_EDGES = (
    ("Expr.Ident(callee_name, _):", "chv_check_named_call(callee_name, call_arguments, argument_names, argument_owned_views, argument_may_alias_refs, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.Scope(_, scoped_name, _):", "chv_check_named_call(scoped_name, call_arguments, argument_names, argument_owned_views, argument_may_alias_refs, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.Index(head, _, _):", "chv_check_named_callee(head, call_arguments, argument_names, argument_owned_views, argument_may_alias_refs, method_receiver_owned_view, method_receiver_may_alias_ref, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.IndexN(head, _, _):", "chv_check_named_callee(head, call_arguments, argument_names, argument_owned_views, argument_may_alias_refs, method_receiver_owned_view, method_receiver_may_alias_ref, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("Expr.Paren(inner, _):", "chv_check_named_callee(inner, call_arguments, argument_names, argument_owned_views, argument_may_alias_refs, method_receiver_owned_view, method_receiver_may_alias_ref, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("_:", "chv_check_unknown_call(call_arguments, argument_owned_views, argument_may_alias_refs, ref_params, binders, owned, view_names, view_values, flow, table)"),
)

FIELD_UNKNOWN_CALL_EDGES = (
    ("Expr.Field(receiver, _, _):", "method_arguments: mutable darray[Ast::Expr] = [receiver]"),
    ("Expr.Field(receiver, _, _):", "method_arguments.extend(call_arguments)"),
    ("Expr.Field(receiver, _, _):", "method_owned_views: mutable darray[bool] = [method_receiver_owned_view]"),
    ("Expr.Field(receiver, _, _):", "method_owned_views.extend(argument_owned_views)"),
    ("Expr.Field(receiver, _, _):", "method_may_alias_refs: mutable darray[bool] = [method_receiver_may_alias_ref]"),
    ("Expr.Field(receiver, _, _):", "method_may_alias_refs.extend(argument_may_alias_refs)"),
    ("Expr.Field(receiver, _, _):", "chv_check_unknown_call(method_arguments, method_owned_views, method_may_alias_refs, ref_params, binders, owned, view_names, view_values, flow, table)"),
)

NAMED_CALL_EDGES = (
    ("if not chv_call_has_named_arguments(argument_names) and sts_is_declared(summary, callee_name) and not (any binder in binders where binder == callee_name):", "chv_check_call_target(callee_name, call_arguments, argument_owned_views, argument_may_alias_refs, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
    ("else:", "chv_check_unknown_call(call_arguments, argument_owned_views, argument_may_alias_refs, ref_params, binders, owned, view_names, view_values, flow, table)"),
)

NAMED_ARGUMENT_UNIFIER_EDGES = (
    ("Expr.Call(callee, arguments, argument_names, _):", "sts_unify_calls(callee, summary, has_unreadable_binder, function_owner, reference_sites, table, names, classes)"),
    ("Expr.Call(callee, arguments, argument_names, _):", "for argument in arguments |names, classes, reference_sites|:"),
    ("Expr.Ident(callee_name, callee_position):", 'shadowed: bool = borrow_reference_site_is_local(reference_sites, function_owner, callee_position, table) or has_unreadable_binder'),
    ("Expr.Ident(callee_name, callee_position):", 'if sts_is_declared(summary, callee_name) and not shadowed and not (any argument_name in argument_names where argument_name != ""):') ,
    ('if sts_is_declared(summary, callee_name) and not shadowed and not (any argument_name in argument_names where argument_name != ""):', "pair_row: mutable u32 = sts_pair_first(summary, callee_name)"),
    ('if sts_is_declared(summary, callee_name) and not shadowed and not (any argument_name in argument_names where argument_name != ""):', "return"),
    ("_:", "sts_collect_names(expression, hidden_names)", 2),
    ("_:", "sts_unify_all(names, classes, hidden_names)", 2),
)

NAMED_ARGUMENT_STATIC_EFFECT_EDGES = (
    ("for candidate in candidates |table| -> table:", "chv_check_call_target(candidate.callee, candidate_arguments, candidate_owned_views, candidate_may_alias_refs, ref_params, binders, owned, view_names, view_values, flow, summary, table) if not chv_call_has_named_arguments(argument_names)"),
    ("for candidate in candidates |table| -> table:", "chv_check_unknown_call(candidate_arguments, candidate_owned_views, candidate_may_alias_refs, ref_params, binders, owned, view_names, view_values, flow, table) if chv_call_has_named_arguments(argument_names)"),
)

UNKNOWN_CALL_EDGES = (
    ("for target in 0..<call_arguments.count |table| -> table:", "if chv_alias_reference_at(call_arguments, argument_may_alias_refs, target, ref_params, flow):"),
    ("if chv_alias_reference_at(call_arguments, argument_may_alias_refs, target, ref_params, flow):", "for source in 0..<call_arguments.count |table| -> table:"),
    ("for source in 0..<call_arguments.count |table| -> table:", "if source != target and chv_owned_view_at(call_arguments, argument_owned_views, source, flow):"),
    ("if source != target and chv_owned_view_at(call_arguments, argument_owned_views, source, flow):", "table.diagnostics <- table.diagnostics.push(Diagnostic{kind: DiagnosticKind.AutoRegionStoreEscape, name: \"\", pos: at, line: at.line, expected: \"\", actual: \"\", state_code: (target + CHV_DIAGNOSTIC_ARGUMENT_NUMBER_BASE).u32()})"),
)

UNIFIER_FALLBACK_EDGES = (
    ("_:", "sts_collect_names(expression, hidden_names)", 2),
    ("_:", "sts_unify_all(names, classes, hidden_names)", 2),
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
sts_unify_all(names, classes, hidden_names)""")
fallback_block = match_arm_body(unifier_source, "match expression:", "_:")
if fallback_block is None or compact_code(fallback_block) != expected_fallback:
    raise SystemExit("store-through unifier fallback no longer unifies every collected hidden name")

validate_edge_set(collect_source, EXPRESSION_EDGES, "expression name collector")
validate_edge_set(statement_collect_source, STATEMENT_COLLECTOR_EDGES, "nested statement name collector")
validate_edge_set(unifier_source, EXPRESSION_UNIFIER_EDGES, "expression call unifier")
validate_edge_set(statements_source, STATEMENT_UNIFIER_EDGES, "statement call unifier")
for fallback_child in ("sts_collect_names(expression, hidden_names)", "sts_unify_all(names, classes, hidden_names)"):
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
        "names_found": (("_:", "sts_unify_all(names, classes, hidden_names)", 2),),
    },
    "proof_sts_nested_callee_calls_reach_unifier": {
        "callee_call": (("Expr.Call(callee, arguments, argument_names, _):", "sts_unify_calls(callee, summary, has_unreadable_binder, function_owner, reference_sites, table, names, classes)"),),
    },
    "proof_chv_static_effect_candidates_check_captures_and_arguments": {
        "captures_checked": (("for candidate in candidates |table| -> table:", "candidate_arguments.extend(candidate.captures)"),),
        "arguments_checked": (("for candidate in candidates |table| -> table:", "candidate_arguments.extend(arguments)"),),
    },
    "proof_chv_comprehension_scope_masks_shadowed_reference": {
        "reference_parameter": (("Expr.Comprehension(variable, iterable, condition, body, _):", "for outer_ref in ref_params |comprehension_ref_params|:"),),
        "binder_shadows_reference": (("for outer_ref in ref_params |comprehension_ref_params|:", "comprehension_ref_params.push(outer_ref) if outer_ref != variable"),),
    },
    "proof_chv_view_alias_join_preserves_owned_fact": {
        "left_branch_may_own": VIEW_FLOW_MERGE_EDGES,
        "right_branch_may_own": VIEW_FLOW_MERGE_EDGES,
    },
    "proof_chv_reference_alias_join_preserves_either_path": {
        "left_path_may_alias": REF_ALIAS_FLOW_MERGE_EDGES,
        "right_path_may_alias": REF_ALIAS_FLOW_MERGE_EDGES,
    },
    "proof_chv_reference_targets_cover_alias_routes": {
        "direct_parameter": (REF_ALIAS_HELPER_EDGES[0],),
        "local_alias": (REF_ALIAS_HELPER_EDGES[1],),
        "call_result": (REF_ALIAS_HELPER_EDGES[2],),
        "projection_fallback": (REF_ALIAS_HELPER_EDGES[4],),
    },
    "proof_chv_binary_operator_checks_both_operands": {
        "receiver_checked": (HOLDER_WALK_EXPRESSION_EDGES[15],),
        "operand_checked": (HOLDER_WALK_EXPRESSION_EDGES[16],),
        "fallback_checked": (HOLDER_WALK_EXPRESSION_EDGES[20],),
    },
    "proof_chv_binary_operator_result_tracks_reference_operands": {
        "left_alias": (REF_ALIAS_HELPER_EDGES[3],),
        "right_alias": (REF_ALIAS_HELPER_EDGES[3],),
    },
    "proof_chv_binary_operator_result_tracks_view_operands": {
        "left_may_be_view": VIEW_ALIAS_BINARY_EDGES,
        "right_may_be_view": VIEW_ALIAS_BINARY_EDGES,
    },
    "proof_chv_index_overloads_check_receiver_and_keys": {
        "receiver_checked": (INDEX_OPERATOR_EDGES[0], INDEX_OPERATOR_EDGES[4]),
        "key_checked": (INDEX_OPERATOR_EDGES[2], INDEX_OPERATOR_EDGES[8]),
        "call_checked": (INDEX_OPERATOR_EDGES[3], INDEX_OPERATOR_EDGES[12]),
        "type_application_skipped": (INDEX_OPERATOR_EDGES[1], INDEX_OPERATOR_EDGES[6], INDEX_OPERATOR_EDGES[7]),
    },
    "proof_chv_index_result_tracks_receiver_view": {
        "receiver_may_be_view": INDEX_VIEW_RESULT_EDGES,
    },
    "proof_chv_address_of_uses_operand_reference_provenance": {
        "operand_alias_checked": REF_ALIAS_ADDRESS_EDGES,
    },
    "proof_chv_unary_negation_tracks_reference_operand": {
        "operand_alias_checked": REF_ALIAS_ADDRESS_EDGES,
    },
    "proof_chv_unary_negation_checks_operator_operand": {
        "operand_checked": (UNARY_NEGATION_EDGES[0],),
        "fallback_checked": (UNARY_NEGATION_EDGES[3], UNARY_NEGATION_EDGES[4]),
    },
    "proof_chv_unary_negation_tracks_view_operand": {
        "operand_may_be_view": UNARY_VIEW_RESULT_EDGES,
    },
    "proof_chv_projection_fallback_requires_caller_reference": {
        "caller_reference_exists": (REF_ALIAS_HELPER_EDGES[4],),
    },
    "proof_chv_overload_bodies_contribute_store_rows": {
        "overload_body_checked": OVERLOAD_SUMMARY_EDGES,
    },
    "proof_chv_method_calls_check_receiver_and_arguments": {
        "receiver_checked": (("Expr.Field(receiver, _, _):", "method_arguments: mutable darray[Ast::Expr] = [receiver]"),),
        "arguments_checked": (("Expr.Field(receiver, _, _):", "method_arguments.extend(call_arguments)"),),
    },
    "proof_chv_indirect_calls_fail_closed": {
        "reference_target_checked": (("for target in 0..<call_arguments.count |table| -> table:", "if chv_alias_reference_at(call_arguments, argument_may_alias_refs, target, ref_params, flow):"),),
        "owned_view_checked": (("for source in 0..<call_arguments.count |table| -> table:", "if source != target and chv_owned_view_at(call_arguments, argument_owned_views, source, flow):"),),
    },
    "proof_chv_summary_calls_check_reference_aliases": {
        "reference_alias_checked": SUMMARY_CALL_EDGES[:2],
        "owned_view_checked": SUMMARY_CALL_EDGES[2:],
    },
    "proof_chv_named_callees_cover_dispatch_routes": {
        "direct_call_checked": (
            ("Expr.Scope(_, scoped_name, _):", "chv_check_named_call(scoped_name, call_arguments, argument_names, argument_owned_views, argument_may_alias_refs, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
            ("Expr.Index(head, _, _):", "chv_check_named_callee(head, call_arguments, argument_names, argument_owned_views, argument_may_alias_refs, method_receiver_owned_view, method_receiver_may_alias_ref, ref_params, binders, owned, view_names, view_values, flow, summary, table)"),
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
    if name == "proof_sts_effect_names_reach_fallback":
        proof_source, proof_edges = effect_text, ()
    elif name == "proof_chv_static_effect_candidates_check_captures_and_arguments":
        proof_source = function_section(holder_text, "chv_check_static_effect_call")
        proof_edges = EFFECT_CANDIDATE_EDGES
    elif name == "proof_chv_comprehension_scope_masks_shadowed_reference":
        proof_source, proof_edges = holder_walk_expressions, HOLDER_WALK_EXPRESSION_EDGES
    elif name == "proof_chv_view_alias_join_preserves_owned_fact":
        proof_source = function_section(holder_text, "chv_flow_set_merge")
        proof_edges = VIEW_FLOW_MERGE_EDGES
    elif name == "proof_chv_reference_alias_join_preserves_either_path":
        proof_source = function_section(holder_text, "chv_flow_set_merge")
        proof_edges = REF_ALIAS_FLOW_MERGE_EDGES
    elif name == "proof_chv_reference_targets_cover_alias_routes":
        proof_source = function_section(holder_text, "chv_expression_may_alias_ref")
        proof_edges = REF_ALIAS_HELPER_EDGES
    elif name == "proof_chv_address_of_uses_operand_reference_provenance":
        proof_source = function_section(holder_text, "chv_expression_may_alias_ref")
        proof_edges = REF_ALIAS_ADDRESS_EDGES
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
    if name == "proof_chv_static_effect_candidates_check_captures_and_arguments":
        validate_exact_boolean_theorem(positive_text, name, routes, "captures_checked and arguments_checked", proof_source, proof_edges)
    elif name == "proof_chv_comprehension_scope_masks_shadowed_reference":
        validate_exact_boolean_theorem(positive_text, name, routes, "reference_parameter and not binder_shadows_reference", proof_source, proof_edges)
    elif name == "proof_chv_method_calls_check_receiver_and_arguments":
        validate_exact_boolean_theorem(positive_text, name, routes, "receiver_checked and arguments_checked", proof_source, proof_edges)
    elif name == "proof_chv_indirect_calls_fail_closed":
        validate_exact_boolean_theorem(positive_text, name, routes, "reference_target_checked and owned_view_checked", proof_source, proof_edges)
    elif name == "proof_chv_view_alias_join_preserves_owned_fact":
        validate_exact_boolean_theorem(positive_text, name, routes, "left_branch_may_own or right_branch_may_own", proof_source, proof_edges)
    elif name == "proof_chv_reference_alias_join_preserves_either_path":
        validate_exact_boolean_theorem(positive_text, name, routes, "left_path_may_alias or right_path_may_alias", proof_source, proof_edges)
    elif name == "proof_chv_reference_targets_cover_alias_routes":
        validate_exact_boolean_theorem(positive_text, name, routes, "direct_parameter and local_alias and call_result and projection_fallback", proof_source, proof_edges)
    elif name == "proof_chv_address_of_uses_operand_reference_provenance":
        validate_exact_boolean_theorem(positive_text, name, routes, "operand_alias_checked", proof_source, proof_edges)
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

effect_call_source = function_section(holder_text, "chv_check_static_effect_call")
validate_edge_set(effect_call_source, EFFECT_CANDIDATE_EDGES, "static-effect holder-call check")
validate_edge_set(effect_call_source, NAMED_ARGUMENT_STATIC_EFFECT_EDGES, "named-argument static-effect fallback")
validate_edge_set(unifier_source, NAMED_ARGUMENT_UNIFIER_EDGES, "named-argument store-through fallback")
reference_alias_source = function_section(holder_text, "chv_expression_may_alias_ref")
validate_edge_set(reference_alias_source, REF_ALIAS_HELPER_EDGES, "reference-alias expression classification")
validate_edge_set(function_section(holder_text, "chv_flow_set_merge"), REF_ALIAS_FLOW_MERGE_EDGES, "reference-alias branch join")
validate_edge_set(function_section(holder_text, "chv_check_call_target"), SUMMARY_CALL_EDGES, "summary-call reference target check")
scalar_reference_fallback = match_arm_body(reference_alias_source, "match argument:", "_:")
expected_scalar_reference_fallback = compact_code("""root: sview = chv_place_root(exclusivity_strip_address(argument).place)
if root == "":
    return false
return true if any reference_parameter in ref_params where reference_parameter == root
index: usize = chv_flow_latest(flow, root)
return index < flow.names.count and flow.may_alias_reference[index]""")
if scalar_reference_fallback is None or compact_code(scalar_reference_fallback) != expected_scalar_reference_fallback:
    raise SystemExit("scalar/non-place targets must not be treated as caller-reference aliases")
if "inner(id_holder(out), owned_view)" not in positive_text or "local_holder.slot" not in positive_text:
    raise SystemExit("reference alias proof must document call-result and projection cases")
if "&local_holder" not in positive_text:
    raise SystemExit("reference alias proof must document the local address-of control")
unary_alias_arm = match_arm_body(reference_alias_source, "match argument:", "Expr.Unary(operator, operand, _):")
if unary_alias_arm is None or compact_code(unary_alias_arm) != compact_code("if operator == TokenKind.Ampersand:\n    return chv_expression_may_alias_ref(operand, ref_params, flow, depth + 1)\nreturn ref_params.count > 0"):
    raise SystemExit("address-of operands must retain their own reference provenance")
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

if "if owned.count > 0" in compact_code(function_section(holder_text, "chv_walk_declarations")):
    raise SystemExit("holder-view walk must visit reference functions to reach nested lambda scopes")
holder_entry_source = function_section(holder_text, "check_call_holder_view_store")
if "returnifsummary.writable_function.count==0" in compact_code(holder_entry_source):
    raise SystemExit("unknown-call holder checks must run even when no named callee summary rows exist")
holder_summary_setup = compact("summary: StoreThroughSummary = chv_build_summary(file.top_decls, holders) can Global{Read,Write}")
holder_walk_setup = compact("table <- chv_walk_declarations(file.top_decls, summary, table)")
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
if "constCHV_VIEW_ALIAS_MAX_DEPTH:u32=8" not in compact_code(holder_text):
    raise SystemExit("holder-view alias recursion limit must remain named")
if "constCHV_DIAGNOSTIC_ARGUMENT_NUMBER_BASE:usize=1" not in compact_code(holder_text):
    raise SystemExit("holder-view diagnostic argument numbering must use a named constant")
if "constCHV_REF_ALIAS_MAX_DEPTH:u32=8" not in compact_code(holder_text):
    raise SystemExit("reference alias recursion limit must remain named")
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
