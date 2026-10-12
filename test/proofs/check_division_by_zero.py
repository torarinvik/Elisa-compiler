"""Admit the constant integer division-by-zero guard against its semantic pass."""
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
SOURCE = ROOT / "src/semantic/check_division_by_zero.elisa"
SEMANTIC = ROOT / "src/semantic/semantic.elisa"
SEMANTIC_API = ROOT / "src/semantic/semantic_api.elisa"
PARALLEL_PASSES = ROOT / "src/semantic/semantic_parallel_passes.elisa"
AST_NODES = ROOT / "src/parser/ast_nodes.elisa"
AST_SIDE_TABLES = ROOT / "src/parser/ast_side_tables.elisa"
EFFECT_TYPE_SHAPE = ROOT / "src/parser/effect_type_shape.elisa"
POSITIVE = HERE / "division_by_zero.elisa"
NEGATIVE = HERE / "division_by_zero_rejected.elisa"

if not __debug__:
    raise SystemExit("run without Python -O")


def compact(text: str) -> str:
    return "".join(text.split())


def ordered_fragments(text: str, fragments: tuple[str, ...]) -> bool:
    normalized = compact(text)
    positions = [normalized.find(compact(fragment)) for fragment in fragments]
    return all(position >= 0 for position in positions) and positions == sorted(positions)


def direct_child(source: str, parent: str, child: str, occurrence: int = 0) -> bool:
    """Require one source line to be a direct body statement of its parent."""
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
                if lines[index].strip() == child or lines[index].strip().startswith(child)]
    if len(children) != 1:
        return False
    child_indent = len(lines[children[0]]) - len(lines[children[0]].lstrip(" \t"))
    return child_indent == parent_indent + 4


def wrap_indented_block(source: str, marker: str, occurrence: int = 0) -> str:
    """Place the block beginning at marker under an unreachable `if false`."""
    lines = source.splitlines()
    starts = [index for index, line in enumerate(lines)
              if line.strip() == marker or line.strip().startswith(marker)]
    if occurrence >= len(starts):
        return source
    start = starts[occurrence]
    indent = len(lines[start]) - len(lines[start].lstrip(" \t"))
    end = start + 1
    while end < len(lines):
        line = lines[end]
        if line.strip() and len(line) - len(line.lstrip(" \t")) <= indent:
            break
        end += 1
    lines.insert(start, " " * indent + "if false:")
    for index in range(start + 1, end + 1):
        lines[index] = "    " + lines[index]
    return "\n".join(lines) + ("\n" if source.endswith("\n") else "")


def wrap_direct_child_block(source: str, parent: str, child: str, parent_occurrence: int = 0) -> str:
    """Make one declared recursive edge unreachable without changing its text."""
    lines = source.splitlines()
    parents = [index for index, line in enumerate(lines) if line.strip() == parent]
    eligible: list[tuple[int, int, int]] = []
    for parent_index in parents:
        parent_indent = len(lines[parent_index]) - len(lines[parent_index].lstrip(" \t"))
        end = parent_index + 1
        while end < len(lines):
            line = lines[end]
            if line.strip() and len(line) - len(line.lstrip(" \t")) <= parent_indent:
                break
            end += 1
        children = [index for index in range(parent_index + 1, end)
                    if lines[index].strip().startswith(child)
                    and len(lines[index]) - len(lines[index].lstrip(" \t")) == parent_indent + 4]
        if len(children) == 1:
            eligible.append((parent_index, children[0], end))
    if parent_occurrence >= len(eligible):
        return source
    _, child_index, end = eligible[parent_occurrence]
    child_indent = len(lines[child_index]) - len(lines[child_index].lstrip(" \t"))
    child_end = child_index + 1
    while child_end < end:
        line = lines[child_end]
        if line.strip() and len(line) - len(line.lstrip(" \t")) <= child_indent:
            break
        child_end += 1
    lines.insert(child_index, " " * child_indent + "if false:")
    for index in range(child_index + 1, child_end + 1):
        lines[index] = "    " + lines[index]
    return "\n".join(lines) + ("\n" if source.endswith("\n") else "")


def function_section(source: str, name: str) -> str:
    matches = list(re.finditer(rf"^[ \t]*def {re.escape(name)}\(", source, re.MULTILINE))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one function named {name}")
    start = matches[0].start()
    following = re.search(r"^[ \t]*def [A-Za-z_][A-Za-z0-9_]*\(", source[matches[0].end():], re.MULTILINE)
    end = matches[0].end() + following.start() if following else len(source)
    return source[start:end]


def enum_variant_declarations(source: str, name: str, next_name: str) -> tuple[str, ...]:
    match = re.search(
        rf"(?ms)^    enum {re.escape(name)} is Node:\n(.*?)(?=^    enum {re.escape(next_name)} is Node:)",
        source,
    )
    if not match:
        raise SystemExit(f"AST enum {name} is missing")
    variants = []
    for line in match.group(1).splitlines():
        value = line.strip()
        if re.fullmatch(r"[A-Z][A-Za-z0-9_]*(?:\([^\n]*\))?", value):
            variants.append(value)
    return tuple(variants)


def struct_field_declarations(source: str, name: str) -> tuple[str, ...]:
    match = re.search(rf"(?ms)^    struct {re.escape(name)}:\n(.*?)(?=^    (?:struct|enum|def)\b|\Z)", source)
    if not match:
        raise SystemExit(f"AST side-table struct {name} is missing")
    fields = []
    for line in match.group(1).splitlines():
        field = re.fullmatch(r"        ([A-Za-z_][A-Za-z0-9_]*): ([^=]+?)(?: = .+)?", line)
        if field:
            fields.append(f"{field.group(1)}:{field.group(2).strip()}")
    return tuple(fields)


def ast_bearing_side_table_structs(source: str) -> set[str]:
    """Return side-table records whose fields contain AST nodes or such records."""
    names = re.findall(r"(?m)^    struct ([A-Za-z_][A-Za-z0-9_]*):$", source)
    fields_by_name = {name: struct_field_declarations(source, name) for name in names}
    node_types = {"Expr", "Stmt", "Decl", "Pattern"}
    bearing: set[str] = set()
    changed = True
    while changed:
        changed = False
        for name, fields in fields_by_name.items():
            if name in bearing:
                continue
            for field in fields:
                type_name = field.split(":", 1)[1].strip()
                if type_name.startswith("mutable "):
                    type_name = type_name[len("mutable "):]
                if type_name.endswith("?"):
                    type_name = type_name[:-1]
                while type_name.startswith("darray[") and type_name.endswith("]"):
                    type_name = type_name[len("darray["):-1]
                if type_name in node_types or type_name in bearing:
                    bearing.add(name)
                    changed = True
                    break
    return bearing


EXPECTED_EXPR_VARIANTS = tuple("""
Invalid
Absent
IntLit(value: i64, pos: Pos)
FloatLit(text: sview, pos: Pos)
StringLit(text: sview, pos: Pos)
CharLit(text: sview, pos: Pos)
BoolLit(value: bool, pos: Pos)
Ident(name: sview, pos: Pos)
Call(callee: Expr, arguments: darray[Expr], argument_names: darray[sview], pos: Pos)
StaticEffectCall(effect_type: Expr, operation: sview, candidates: darray[StaticEffectCandidate], arguments: darray[Expr], argument_names: darray[sview], pos: Pos)
Field(object: Expr, field: sview, pos: Pos)
Scope(base: Expr, name: sview, pos: Pos)
ShorthandMember(parts: darray[sview], pos: Pos)
Index(object: Expr, index: Expr, pos: Pos)
Slice(object: Expr, low: Expr, high: Expr, pos: Pos)
IndexN(object: Expr, arguments: darray[Expr], pos: Pos)
Binary(left: Expr, operator: TokenKind, right: Expr, pos: Pos)
Unary(operator: TokenKind, operand: Expr, pos: Pos)
Move(operand: Expr, pos: Pos)
RegionNew(operand: Expr, region: sview, pos: Pos)
Paren(inner: Expr, pos: Pos)
Array(elements: darray[Expr], pos: Pos)
Tuple(elements: darray[Expr], pos: Pos)
SetLit(elements: darray[Expr], pos: Pos)
DictLit(entries: darray[DictEntry], pos: Pos)
Construct(type: Expr, fields: darray[FieldInit], pos: Pos)
RecordUpdate(base: Expr, fields: darray[FieldInit], pos: Pos)
If(condition: Expr, then_expr: Expr, else_expr: Expr, pos: Pos)
Match(scrutinee: Expr, arms: darray[MatchArm], pos: Pos)
Catch(guarded: Expr, arms: darray[MatchArm], pos: Pos)
Comprehension(var: sview, iterable: Expr, condition: Expr, body: Expr, pos: Pos)
Refinement(base: Expr, predicate: Expr, pos: Pos)
GetElse(guarded: Expr, recovery: darray[Stmt], pos: Pos)
Lambda(params: darray[sview], body: darray[Stmt], pos: Pos)
Block(stmts: darray[Stmt], value: Expr, captures: darray[sview], pos: Pos)
""".strip().splitlines())
EXPECTED_STMT_VARIANTS = tuple("""
Invalid
Expr(expression: Expr, pos: Pos)
Block(kind: sview, clause: darray[sview], binding: sview, body: darray[Stmt], pos: Pos)
VarDecl(name: sview, type_expression: Expr, value: Expr, pos: Pos)
Assign(target: Expr, operator: TokenKind, value: Expr, pos: Pos)
If(condition: Expr, then_body: darray[Stmt], else_body: darray[Stmt], pos: Pos)
While(condition: Expr, body: darray[Stmt], pos: Pos)
For(bind: sview, variables: darray[sview], iterable: Expr, body: darray[Stmt], pos: Pos)
Return(value: Expr?, pos: Pos)
Break(label: sview, pos: Pos)
Continue(label: sview, pos: Pos)
Match(scrutinee: Expr, arms: darray[MatchArm], pos: Pos)
Contract(kind: sview, expression: Expr, pos: Pos)
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
    "ParamDecl": tuple("name:sview name_pos:Pos type_expression:Expr is_mutable:bool has_default:bool default_value:Expr is_affine:bool value_thread:bool".split()),
    "LocalRegionAnnotation": ("name:sview", "type_expression:Expr", "region:sview", "line:u32", "end_line:mutable u32"),
    "BitGroupMember": tuple("name:sview type_expression:Expr pos:Pos".split()),
    "StructMember": tuple("is_private:bool name:sview type_expression:Expr omittable:bool is_ghost:bool has_default:bool default_value:Expr region:sview bit_group_kind:sview bit_group_members:darray[BitGroupMember]".split()),
    "EnumVariant": tuple("name:sview fields:darray[Expr] field_names:darray[sview] value_expr:Expr".split()),
    "MatchArm": tuple("pattern:Pattern body:darray[Stmt] guard:Expr pos:Pos".split()),
    "FieldInit": tuple("name:sview value:Expr is_copy_base:bool".split()),
    "StructCopyBase": tuple("type_expression:Expr base:Expr pos:Pos".split()),
    "DictEntry": tuple("key:Expr value:Expr".split()),
    "DerivedStateRule": tuple("owner:sview state:sview condition:Expr module_name:sview declaration_line:u32 declaration_offset:u32 pos:Pos".split()),
    "StaticEffectCandidate": tuple("effect_type:Expr callee:sview captures:darray[Expr] effect_identity_id:u32 handler_identity_id:u32 callee_owner:sview".split()),
    "EffectTypeReference": tuple("spelling:sview type_expression:Expr position:Pos lexical_owner:sview identity_id:u32".split()),
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
production_zero_constant = "const DIVISION_ZERO_LITERAL: i64 = 0"
division_guard_path = (
    "Expr.Binary(left, operator, right, line):",
    "if operator == TokenKind.Slash:",
    "match right:",
    "Expr.IntLit(divisor, _):",
    "DiagnosticKind.DivisionByZero",
    "if divisor == DIVISION_ZERO_LITERAL",
    "table <- walk_expression_for_division_by_zero(left, table)",
    "table <- walk_expression_for_division_by_zero(right, table) if operator != TokenKind.Is and operator != TokenKind.As",
)
expression_walk_path = (
    "Expr.Call(callee, arguments, argument_names, line): table <- walk_expression_for_division_by_zero(callee, table) for argument in arguments |table| -> table: table <- walk_expression_for_division_by_zero(argument, table)",
    "Expr.StaticEffectCall(effect_type, operation, candidates, arguments, argument_names, line): for child in Ast::effect_runtime_children(candidates, arguments) |table|: table <- walk_expression_for_division_by_zero(child, table)",
    "Expr.Field(object, field, line): table <- walk_expression_for_division_by_zero(object, table)",
    "Expr.Scope(base, name, line): table <- walk_expression_for_division_by_zero(base, table)",
    "Expr.Index(object, index, line): table <- walk_expression_for_division_by_zero(object, table) table <- walk_expression_for_division_by_zero(index, table) if not index_receiver_is_type_application(object)",
    "Expr.Unary(operator, operand, line): table <- walk_expression_for_division_by_zero(operand, table)",
    "Expr.Move(operand, line): table <- walk_expression_for_division_by_zero(operand, table)",
    "Expr.RegionNew(operand, region, line): table <- walk_expression_for_division_by_zero(operand, table)",
    "Expr.Paren(inner, line): table <- walk_expression_for_division_by_zero(inner, table)",
    "Expr.Array(elements, line): for element in elements |table| -> table: table <- walk_expression_for_division_by_zero(element, table)",
    "Expr.Tuple(elements, line): for element in elements |table| -> table: table <- walk_expression_for_division_by_zero(element, table)",
    "Expr.Slice(object, low, high, line): table <- walk_expression_for_division_by_zero(object, table) table <- walk_expression_for_division_by_zero(low, table) table <- walk_expression_for_division_by_zero(high, table)",
    "Expr.IndexN(object, arguments, line): table <- walk_expression_for_division_by_zero(object, table) for argument in arguments |table| -> table: table <- walk_expression_for_division_by_zero(argument, table) if not index_receiver_is_type_application(object)",
    "Expr.SetLit(elements, line): for element in elements |table| -> table: table <- walk_expression_for_division_by_zero(element, table)",
    "Expr.DictLit(entries, line): for entry in entries |table| -> table: table <- walk_expression_for_division_by_zero(entry.key, table) table <- walk_expression_for_division_by_zero(entry.value, table)",
    "Expr.Construct(type_expression, fields, line): table <- walk_expression_for_division_by_zero(type_expression, table) for field in fields |table| -> table: table <- walk_expression_for_division_by_zero(field.value, table)",
    "Expr.RecordUpdate(base, fields, line): table <- walk_expression_for_division_by_zero(base, table) for field in fields |table| -> table: table <- walk_expression_for_division_by_zero(field.value, table)",
    "Expr.If(condition, then_expr, else_expr, line): table <- walk_expression_for_division_by_zero(condition, table) table <- walk_expression_for_division_by_zero(then_expr, table) table <- walk_expression_for_division_by_zero(else_expr, table)",
    "Expr.Comprehension(loop_variable, iterable, condition, body, line): table <- walk_expression_for_division_by_zero(iterable, table) table <- walk_expression_for_division_by_zero(condition, table) table <- walk_expression_for_division_by_zero(body, table)",
    "Expr.Lambda(parameters, body, line): table <- walk_statements_for_division_by_zero(body, table)",
    "Expr.Block(statements, value, captures, line): table <- walk_statements_for_division_by_zero(statements, table) table <- walk_expression_for_division_by_zero(value, table)",
    "Expr.Match(scrutinee, arms, line): table <- walk_expression_for_division_by_zero(scrutinee, table) for arm in arms |table| -> table: table <- walk_expression_for_division_by_zero(arm.guard, table) table <- walk_statements_for_division_by_zero(arm.body, table)",
    "Expr.Catch(guarded, arms, line): table <- walk_expression_for_division_by_zero(guarded, table) for arm in arms |table| -> table: table <- walk_expression_for_division_by_zero(arm.guard, table) table <- walk_statements_for_division_by_zero(arm.body, table)",
    "Expr.Refinement(base, predicate, line): table <- walk_expression_for_division_by_zero(base, table) table <- walk_expression_for_division_by_zero(predicate, table)",
    "Expr.GetElse(guarded, recovery, line): table <- walk_expression_for_division_by_zero(guarded, table) table <- walk_statements_for_division_by_zero(recovery, table)",
)
expression_edges = (
    ("def walk_expression_for_division_by_zero(expression: Ast::Expr, table: lmut SymbolTable) -> void:", "can Memory.Allocate, Abort.Panic:"),
    ("can Memory.Allocate, Abort.Panic:", "match expression:"),
    ("match expression:", "Expr.Binary(left, operator, right, line):"),
    ("match expression:", "Expr.Call(callee, arguments, argument_names, line):"),
    ("match expression:", "Expr.StaticEffectCall(effect_type, operation, candidates, arguments, argument_names, line):"),
    ("match expression:", "Expr.Field(object, field, line):"),
    ("match expression:", "Expr.Scope(base, name, line):"),
    ("match expression:", "Expr.Index(object, index, line):"),
    ("match expression:", "Expr.Unary(operator, operand, line):"),
    ("match expression:", "Expr.Move(operand, line):"),
    ("match expression:", "Expr.RegionNew(operand, region, line):"),
    ("match expression:", "Expr.Paren(inner, line):"),
    ("match expression:", "Expr.Array(elements, line):"),
    ("match expression:", "Expr.Tuple(elements, line):"),
    ("match expression:", "Expr.Slice(object, low, high, line):"),
    ("match expression:", "Expr.IndexN(object, arguments, line):"),
    ("match expression:", "Expr.SetLit(elements, line):"),
    ("match expression:", "Expr.DictLit(entries, line):"),
    ("match expression:", "Expr.Construct(type_expression, fields, line):"),
    ("match expression:", "Expr.RecordUpdate(base, fields, line):"),
    ("match expression:", "Expr.If(condition, then_expr, else_expr, line):"),
    ("match expression:", "Expr.Comprehension(loop_variable, iterable, condition, body, line):"),
    ("match expression:", "Expr.Lambda(parameters, body, line):"),
    ("match expression:", "Expr.Block(statements, value, captures, line):"),
    ("match expression:", "Expr.Match(scrutinee, arms, line):"),
    ("match expression:", "Expr.Catch(guarded, arms, line):"),
    ("match expression:", "Expr.Refinement(base, predicate, line):"),
    ("match expression:", "Expr.GetElse(guarded, recovery, line):"),
    ("Expr.Binary(left, operator, right, line):", "if operator == TokenKind.Slash:"),
    ("Expr.Binary(left, operator, right, line):", "table <- walk_expression_for_division_by_zero(left, table)"),
    ("Expr.Binary(left, operator, right, line):", "table <- walk_expression_for_division_by_zero(right, table)"),
    ("if operator == TokenKind.Slash:", "match right:"),
    ("match right:", "Expr.IntLit(divisor, _):"),
    ("Expr.IntLit(divisor, _):", "table.diagnostics <- table.diagnostics.push(Diagnostic{kind: DiagnosticKind.DivisionByZero"),
    ("Expr.Call(callee, arguments, argument_names, line):", "table <- walk_expression_for_division_by_zero(callee, table)"),
    ("Expr.Call(callee, arguments, argument_names, line):", "for argument in arguments |table| -> table:"),
    ("for argument in arguments |table| -> table:", "table <- walk_expression_for_division_by_zero(argument, table)"),
    ("Expr.StaticEffectCall(effect_type, operation, candidates, arguments, argument_names, line):", "for child in Ast::effect_runtime_children(candidates, arguments) |table|:"),
    ("for child in Ast::effect_runtime_children(candidates, arguments) |table|:", "table <- walk_expression_for_division_by_zero(child, table)"),
    ("Expr.Field(object, field, line):", "table <- walk_expression_for_division_by_zero(object, table)"),
    ("Expr.Scope(base, name, line):", "table <- walk_expression_for_division_by_zero(base, table)"),
    ("Expr.Index(object, index, line):", "table <- walk_expression_for_division_by_zero(object, table)"),
    ("Expr.Index(object, index, line):", "table <- walk_expression_for_division_by_zero(index, table)"),
    ("Expr.Unary(operator, operand, line):", "table <- walk_expression_for_division_by_zero(operand, table)"),
    ("Expr.Move(operand, line):", "table <- walk_expression_for_division_by_zero(operand, table)"),
    ("Expr.RegionNew(operand, region, line):", "table <- walk_expression_for_division_by_zero(operand, table)"),
    ("Expr.Paren(inner, line):", "table <- walk_expression_for_division_by_zero(inner, table)"),
    ("Expr.Array(elements, line):", "for element in elements |table| -> table:"),
    ("for element in elements |table| -> table:", "table <- walk_expression_for_division_by_zero(element, table)"),
    ("Expr.Tuple(elements, line):", "for element in elements |table| -> table:"),
    ("for element in elements |table| -> table:", "table <- walk_expression_for_division_by_zero(element, table)", 1),
    ("Expr.Slice(object, low, high, line):", "table <- walk_expression_for_division_by_zero(object, table)"),
    ("Expr.Slice(object, low, high, line):", "table <- walk_expression_for_division_by_zero(low, table)"),
    ("Expr.Slice(object, low, high, line):", "table <- walk_expression_for_division_by_zero(high, table)"),
    ("Expr.IndexN(object, arguments, line):", "table <- walk_expression_for_division_by_zero(object, table)"),
    ("Expr.IndexN(object, arguments, line):", "for argument in arguments |table| -> table:"),
    ("for argument in arguments |table| -> table:", "table <- walk_expression_for_division_by_zero(argument, table)", 1),
    ("Expr.SetLit(elements, line):", "for element in elements |table| -> table:"),
    ("for element in elements |table| -> table:", "table <- walk_expression_for_division_by_zero(element, table)", 2),
    ("Expr.DictLit(entries, line):", "for entry in entries |table| -> table:"),
    ("for entry in entries |table| -> table:", "table <- walk_expression_for_division_by_zero(entry.key, table)"),
    ("for entry in entries |table| -> table:", "table <- walk_expression_for_division_by_zero(entry.value, table)"),
    ("Expr.Construct(type_expression, fields, line):", "table <- walk_expression_for_division_by_zero(type_expression, table)"),
    ("Expr.Construct(type_expression, fields, line):", "for field in fields |table| -> table:"),
    ("for field in fields |table| -> table:", "table <- walk_expression_for_division_by_zero(field.value, table)"),
    ("Expr.RecordUpdate(base, fields, line):", "table <- walk_expression_for_division_by_zero(base, table)"),
    ("Expr.RecordUpdate(base, fields, line):", "for field in fields |table| -> table:"),
    ("for field in fields |table| -> table:", "table <- walk_expression_for_division_by_zero(field.value, table)", 1),
    ("Expr.If(condition, then_expr, else_expr, line):", "table <- walk_expression_for_division_by_zero(condition, table)"),
    ("Expr.If(condition, then_expr, else_expr, line):", "table <- walk_expression_for_division_by_zero(then_expr, table)"),
    ("Expr.If(condition, then_expr, else_expr, line):", "table <- walk_expression_for_division_by_zero(else_expr, table)"),
    ("Expr.Comprehension(loop_variable, iterable, condition, body, line):", "table <- walk_expression_for_division_by_zero(iterable, table)"),
    ("Expr.Comprehension(loop_variable, iterable, condition, body, line):", "table <- walk_expression_for_division_by_zero(condition, table)"),
    ("Expr.Comprehension(loop_variable, iterable, condition, body, line):", "table <- walk_expression_for_division_by_zero(body, table)"),
    ("Expr.Lambda(parameters, body, line):", "table <- walk_statements_for_division_by_zero(body, table)"),
    ("Expr.Block(statements, value, captures, line):", "table <- walk_statements_for_division_by_zero(statements, table)"),
    ("Expr.Block(statements, value, captures, line):", "table <- walk_expression_for_division_by_zero(value, table)"),
    ("Expr.Match(scrutinee, arms, line):", "table <- walk_expression_for_division_by_zero(scrutinee, table)"),
    ("Expr.Match(scrutinee, arms, line):", "for arm in arms |table| -> table:"),
    ("for arm in arms |table| -> table:", "table <- walk_expression_for_division_by_zero(arm.guard, table)"),
    ("for arm in arms |table| -> table:", "table <- walk_statements_for_division_by_zero(arm.body, table)"),
    ("Expr.Catch(guarded, arms, line):", "table <- walk_expression_for_division_by_zero(guarded, table)"),
    ("Expr.Catch(guarded, arms, line):", "for arm in arms |table| -> table:"),
    ("for arm in arms |table| -> table:", "table <- walk_expression_for_division_by_zero(arm.guard, table)", 1),
    ("for arm in arms |table| -> table:", "table <- walk_statements_for_division_by_zero(arm.body, table)", 1),
    ("Expr.Refinement(base, predicate, line):", "table <- walk_expression_for_division_by_zero(base, table)"),
    ("Expr.Refinement(base, predicate, line):", "table <- walk_expression_for_division_by_zero(predicate, table)"),
    ("Expr.GetElse(guarded, recovery, line):", "table <- walk_expression_for_division_by_zero(guarded, table)"),
    ("Expr.GetElse(guarded, recovery, line):", "table <- walk_statements_for_division_by_zero(recovery, table)"),
)
statement_walk_path = (
    "Stmt.Expr(expression, line): table <- walk_expression_for_division_by_zero(expression, table)",
    "Stmt.VarDecl(name, type_expression, value, line): table <- walk_expression_for_division_by_zero(type_expression, table) table <- walk_expression_for_division_by_zero(value, table)",
    "Stmt.Assign(target, operator, value, line): table <- walk_expression_for_division_by_zero(target, table) table <- walk_expression_for_division_by_zero(value, table)",
    "Stmt.If(condition, then_body, else_body, line): table <- walk_expression_for_division_by_zero(condition, table) table <- walk_statements_for_division_by_zero(then_body, table) table <- walk_statements_for_division_by_zero(else_body, table)",
    "Stmt.While(condition, body, line): table <- walk_expression_for_division_by_zero(condition, table) table <- walk_statements_for_division_by_zero(body, table)",
    "Stmt.For(bind, variables, iterable, body, line): table <- walk_expression_for_division_by_zero(iterable, table) table <- walk_statements_for_division_by_zero(body, table)",
    "Stmt.Return(value, line): table <- walk_expression_for_division_by_zero(return_value, table) if value is return_value",
    "Stmt.Block(kind, clause, binding, body, line): table <- walk_statements_for_division_by_zero(body, table)",
    "Stmt.Match(scrutinee, arms, line): table <- walk_expression_for_division_by_zero(scrutinee, table) for arm in arms |table|: table <- walk_expression_for_division_by_zero(arm.guard, table) table <- walk_statements_for_division_by_zero(arm.body, table)",
    "Stmt.Contract(kind, expression, line): table <- walk_expression_for_division_by_zero(expression, table)",
)
statement_edges = (
    ("def walk_statements_for_division_by_zero(statements: darray[Ast::Stmt], table: lmut SymbolTable) -> void:", "can Memory.Allocate, Abort.Panic:"),
    ("can Memory.Allocate, Abort.Panic:", "for statement in statements |table|:"),
    ("for statement in statements |table|:", "match statement:"),
    ("match statement:", "Stmt.Expr(expression, line):"),
    ("match statement:", "Stmt.VarDecl(name, type_expression, value, line):"),
    ("match statement:", "Stmt.Assign(target, operator, value, line):"),
    ("match statement:", "Stmt.If(condition, then_body, else_body, line):"),
    ("match statement:", "Stmt.While(condition, body, line):"),
    ("match statement:", "Stmt.For(bind, variables, iterable, body, line):"),
    ("match statement:", "Stmt.Return(value, line):"),
    ("match statement:", "Stmt.Block(kind, clause, binding, body, line):"),
    ("match statement:", "Stmt.Match(scrutinee, arms, line):"),
    ("match statement:", "Stmt.Contract(kind, expression, line):"),
    ("Stmt.Expr(expression, line):", "table <- walk_expression_for_division_by_zero(expression, table)"),
    ("Stmt.VarDecl(name, type_expression, value, line):", "table <- walk_expression_for_division_by_zero(type_expression, table)"),
    ("Stmt.VarDecl(name, type_expression, value, line):", "table <- walk_expression_for_division_by_zero(value, table)"),
    ("Stmt.Assign(target, operator, value, line):", "table <- walk_expression_for_division_by_zero(target, table)"),
    ("Stmt.Assign(target, operator, value, line):", "table <- walk_expression_for_division_by_zero(value, table)"),
    ("Stmt.If(condition, then_body, else_body, line):", "table <- walk_expression_for_division_by_zero(condition, table)"),
    ("Stmt.If(condition, then_body, else_body, line):", "table <- walk_statements_for_division_by_zero(then_body, table)"),
    ("Stmt.If(condition, then_body, else_body, line):", "table <- walk_statements_for_division_by_zero(else_body, table)"),
    ("Stmt.While(condition, body, line):", "table <- walk_expression_for_division_by_zero(condition, table)"),
    ("Stmt.While(condition, body, line):", "table <- walk_statements_for_division_by_zero(body, table)"),
    ("Stmt.For(bind, variables, iterable, body, line):", "table <- walk_expression_for_division_by_zero(iterable, table)"),
    ("Stmt.For(bind, variables, iterable, body, line):", "table <- walk_statements_for_division_by_zero(body, table)"),
    ("Stmt.Return(value, line):", "table <- walk_expression_for_division_by_zero(return_value, table)"),
    ("Stmt.Block(kind, clause, binding, body, line):", "table <- walk_statements_for_division_by_zero(body, table)"),
    ("Stmt.Match(scrutinee, arms, line):", "table <- walk_expression_for_division_by_zero(scrutinee, table)"),
    ("Stmt.Match(scrutinee, arms, line):", "for arm in arms |table|:"),
    ("for arm in arms |table|:", "table <- walk_expression_for_division_by_zero(arm.guard, table)"),
    ("for arm in arms |table|:", "table <- walk_statements_for_division_by_zero(arm.body, table)"),
    ("Stmt.Contract(kind, expression, line):", "table <- walk_expression_for_division_by_zero(expression, table)"),
)

declaration_edges = (
    ("def check_division_by_zero(declarations: darray[Ast::Decl], table: lmut SymbolTable) -> void:", "can Memory.Allocate, Abort.Panic:"),
    ("can Memory.Allocate, Abort.Panic:", "for declaration in declarations |table|:"),
    ("for declaration in declarations |table|:", "match declaration:"),
    ("match declaration:", "Decl.Func(name, params, return_type, body, effects, decorators, line):"),
    ("match declaration:", "Decl.Struct(name, members, affinity, has_named_states, has_derive, invariants, line):"),
    ("match declaration:", "Decl.Enum(name, variants, is_const, storage_type, line):"),
    ("match declaration:", "Decl.Alias(name, target, line):"),
    ("match declaration:", "Decl.Law(name, predicate, line):"),
    ("match declaration:", "Decl.Const(name, type_expression, value, is_mutable, line):"),
    ("match declaration:", "Decl.Module(module_name, body, line):"),
    ("match declaration:", "Decl.Scoped(body, line):"),
    ("Decl.Func(name, params, return_type, body, effects, decorators, line):", "for parameter in params |table|:"),
    ("Decl.Func(name, params, return_type, body, effects, decorators, line):", "table <- walk_expression_for_division_by_zero(return_type, table)"),
    ("Decl.Func(name, params, return_type, body, effects, decorators, line):", "table <- walk_statements_for_division_by_zero(body, table)"),
    ("for parameter in params |table|:", "table <- walk_expression_for_division_by_zero(parameter.type_expression, table)"),
    ("for parameter in params |table|:", "table <- walk_expression_for_division_by_zero(parameter.default_value, table)"),
    ("Decl.Struct(name, members, affinity, has_named_states, has_derive, invariants, line):", "for member in members |table|:"),
    ("Decl.Struct(name, members, affinity, has_named_states, has_derive, invariants, line):", "for invariant in invariants |table| -> table:"),
    ("for member in members |table|:", "table <- walk_expression_for_division_by_zero(member.type_expression, table)"),
    ("for member in members |table|:", "table <- walk_expression_for_division_by_zero(member.default_value, table)"),
    ("for member in members |table|:", "for bit_member in member.bit_group_members |table| -> table:"),
    ("for bit_member in member.bit_group_members |table| -> table:", "table <- walk_expression_for_division_by_zero(bit_member.type_expression, table)"),
    ("for invariant in invariants |table| -> table:", "table <- walk_expression_for_division_by_zero(invariant, table)"),
    ("Decl.Enum(name, variants, is_const, storage_type, line):", "table <- walk_expression_for_division_by_zero(storage_type, table)"),
    ("Decl.Enum(name, variants, is_const, storage_type, line):", "for variant in variants |table|:"),
    ("for variant in variants |table|:", "for field_type in variant.fields |table| -> table:"),
    ("for variant in variants |table|:", "table <- walk_expression_for_division_by_zero(variant.value_expr, table)"),
    ("for field_type in variant.fields |table| -> table:", "table <- walk_expression_for_division_by_zero(field_type, table)"),
    ("Decl.Alias(name, target, line):", "table <- walk_expression_for_division_by_zero(target, table)"),
    ("Decl.Law(name, predicate, line):", "table <- walk_expression_for_division_by_zero(predicate, table)"),
    ("Decl.Const(name, type_expression, value, is_mutable, line):", "table <- walk_expression_for_division_by_zero(type_expression, table)"),
    ("Decl.Const(name, type_expression, value, is_mutable, line):", "table <- walk_expression_for_division_by_zero(value, table)"),
    ("Decl.Module(module_name, body, line):", "table <- check_division_by_zero(body, table)"),
    ("Decl.Scoped(body, line):", "table <- check_division_by_zero(body, table)"),
)

ROUTE_AGGREGATE_BINDINGS = {
    "proof_catch_division_children_reported": {
        "scrutinee_reported": (("expression", "Expr.Catch(guarded, arms, line):", "table <- walk_expression_for_division_by_zero(guarded, table)"),),
        "arm_guard_reported": (("expression", "for arm in arms |table| -> table:", "table <- walk_expression_for_division_by_zero(arm.guard, table)", 1),),
        "arm_body_reported": (("expression", "for arm in arms |table| -> table:", "table <- walk_statements_for_division_by_zero(arm.body, table)", 1),),
    },
    "proof_static_effect_division_children_reported": {
        "capture_reported": (("effect_helper", "children.extend(candidate.captures)"),),
        "argument_reported": (("effect_helper", "children.extend(arguments)"),),
    },
    "proof_unary_division_child_reported": {
        "child_reported": (
            ("expression", "Expr.Move(operand, line):", "table <- walk_expression_for_division_by_zero(operand, table)"),
            ("expression", "Expr.RegionNew(operand, region, line):", "table <- walk_expression_for_division_by_zero(operand, table)"),
        ),
    },
    "proof_refinement_division_children_reported": {
        "base_reported": (("expression", "Expr.Refinement(base, predicate, line):", "table <- walk_expression_for_division_by_zero(base, table)"),),
        "predicate_reported": (("expression", "Expr.Refinement(base, predicate, line):", "table <- walk_expression_for_division_by_zero(predicate, table)"),),
    },
    "proof_get_else_division_children_reported": {
        "guarded_reported": (("expression", "Expr.GetElse(guarded, recovery, line):", "table <- walk_expression_for_division_by_zero(guarded, table)"),),
        "recovery_reported": (("expression", "Expr.GetElse(guarded, recovery, line):", "table <- walk_statements_for_division_by_zero(recovery, table)"),),
    },
    "proof_match_children_reported": {
        "expression_scrutinee": (("expression", "Expr.Match(scrutinee, arms, line):", "table <- walk_expression_for_division_by_zero(scrutinee, table)"),),
        "expression_guard": (("expression", "for arm in arms |table| -> table:", "table <- walk_expression_for_division_by_zero(arm.guard, table)", 0),),
        "expression_body": (("expression", "for arm in arms |table| -> table:", "table <- walk_statements_for_division_by_zero(arm.body, table)", 0),),
        "statement_scrutinee": (("statement", "Stmt.Match(scrutinee, arms, line):", "table <- walk_expression_for_division_by_zero(scrutinee, table)"),),
        "statement_guard": (("statement", "for arm in arms |table|:", "table <- walk_expression_for_division_by_zero(arm.guard, table)"),),
        "statement_body": (("statement", "for arm in arms |table|:", "table <- walk_statements_for_division_by_zero(arm.body, table)"),),
    },
    "proof_statement_children_reported": {
        "expression": (("statement", "Stmt.Expr(expression, line):", "table <- walk_expression_for_division_by_zero(expression, table)"),),
        "variable_type": (("statement", "Stmt.VarDecl(name, type_expression, value, line):", "table <- walk_expression_for_division_by_zero(type_expression, table)"),),
        "variable_value": (("statement", "Stmt.VarDecl(name, type_expression, value, line):", "table <- walk_expression_for_division_by_zero(value, table)"),),
        "assignment_target": (("statement", "Stmt.Assign(target, operator, value, line):", "table <- walk_expression_for_division_by_zero(target, table)"),),
        "assignment_value": (("statement", "Stmt.Assign(target, operator, value, line):", "table <- walk_expression_for_division_by_zero(value, table)"),),
        "if_condition": (("statement", "Stmt.If(condition, then_body, else_body, line):", "table <- walk_expression_for_division_by_zero(condition, table)"),),
        "if_then_body": (("statement", "Stmt.If(condition, then_body, else_body, line):", "table <- walk_statements_for_division_by_zero(then_body, table)"),),
        "if_else_body": (("statement", "Stmt.If(condition, then_body, else_body, line):", "table <- walk_statements_for_division_by_zero(else_body, table)"),),
        "while_condition": (("statement", "Stmt.While(condition, body, line):", "table <- walk_expression_for_division_by_zero(condition, table)"),),
        "while_body": (("statement", "Stmt.While(condition, body, line):", "table <- walk_statements_for_division_by_zero(body, table)"),),
        "for_iterable": (("statement", "Stmt.For(bind, variables, iterable, body, line):", "table <- walk_expression_for_division_by_zero(iterable, table)"),),
        "for_body": (("statement", "Stmt.For(bind, variables, iterable, body, line):", "table <- walk_statements_for_division_by_zero(body, table)"),),
        "return_value": (("statement", "Stmt.Return(value, line):", "table <- walk_expression_for_division_by_zero(return_value, table)"),),
        "block_body": (("statement", "Stmt.Block(kind, clause, binding, body, line):", "table <- walk_statements_for_division_by_zero(body, table)"),),
        "match_scrutinee": (("statement", "Stmt.Match(scrutinee, arms, line):", "table <- walk_expression_for_division_by_zero(scrutinee, table)"),),
        "match_guard": (("statement", "for arm in arms |table|:", "table <- walk_expression_for_division_by_zero(arm.guard, table)"),),
        "match_body": (("statement", "for arm in arms |table|:", "table <- walk_statements_for_division_by_zero(arm.body, table)"),),
        "contract_expression": (("statement", "Stmt.Contract(kind, expression, line):", "table <- walk_expression_for_division_by_zero(expression, table)"),),
    },
    "proof_declaration_children_reported": {
        "parameter_type": (("declaration", "for parameter in params |table|:", "table <- walk_expression_for_division_by_zero(parameter.type_expression, table)"),),
        "parameter_default": (("declaration", "for parameter in params |table|:", "table <- walk_expression_for_division_by_zero(parameter.default_value, table)"),),
        "return_type": (("declaration", "Decl.Func(name, params, return_type, body, effects, decorators, line):", "table <- walk_expression_for_division_by_zero(return_type, table)"),),
        "function_body": (("declaration", "Decl.Func(name, params, return_type, body, effects, decorators, line):", "table <- walk_statements_for_division_by_zero(body, table)"),),
        "member_type": (("declaration", "for member in members |table|:", "table <- walk_expression_for_division_by_zero(member.type_expression, table)"),),
        "member_default": (("declaration", "for member in members |table|:", "table <- walk_expression_for_division_by_zero(member.default_value, table)"),),
        "bit_member_type": (("declaration", "for bit_member in member.bit_group_members |table| -> table:", "table <- walk_expression_for_division_by_zero(bit_member.type_expression, table)"),),
        "invariant": (("declaration", "for invariant in invariants |table| -> table:", "table <- walk_expression_for_division_by_zero(invariant, table)"),),
        "enum_storage_type": (("declaration", "Decl.Enum(name, variants, is_const, storage_type, line):", "table <- walk_expression_for_division_by_zero(storage_type, table)"),),
        "enum_payload_type": (("declaration", "for field_type in variant.fields |table| -> table:", "table <- walk_expression_for_division_by_zero(field_type, table)"),),
        "enum_variant_value": (("declaration", "for variant in variants |table|:", "table <- walk_expression_for_division_by_zero(variant.value_expr, table)"),),
        "alias_target": (("declaration", "Decl.Alias(name, target, line):", "table <- walk_expression_for_division_by_zero(target, table)"),),
        "law_predicate": (("declaration", "Decl.Law(name, predicate, line):", "table <- walk_expression_for_division_by_zero(predicate, table)"),),
        "const_type": (("declaration", "Decl.Const(name, type_expression, value, is_mutable, line):", "table <- walk_expression_for_division_by_zero(type_expression, table)"),),
        "const_value": (("declaration", "Decl.Const(name, type_expression, value, is_mutable, line):", "table <- walk_expression_for_division_by_zero(value, table)"),),
        "module_body": (("declaration", "Decl.Module(module_name, body, line):", "table <- check_division_by_zero(body, table)"),),
        "scoped_body": (("declaration", "Decl.Scoped(body, line):", "table <- check_division_by_zero(body, table)"),),
    },
}


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
if "par_pass_run(file,&loop_view,flags,table,shared_pool,0,5)" not in compact(SEMANTIC_API.read_text()):
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
    Path(__file__), HERE / "proof_product_gate.py", SOURCE, SEMANTIC,
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
