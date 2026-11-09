"""Source inspection and traversal inventories for literal range proofs."""
import re


def compact(text: str) -> str:
    return re.sub(
        r'"(?:\\.|[^"\\])*"|\s+',
        lambda match: match.group(0) if match.group(0).startswith('"') else "",
        text,
    )

def compact_code(text: str) -> str:
    return compact("\n".join(line for line in text.splitlines()
                              if not line.lstrip().startswith("#")))

def function_section(text: str, name: str) -> str:
    match = re.search(rf"(?m)^\s*def {re.escape(name)}\([^\n]*\n(.*?)(?=^\s*def |\Z)", text, re.DOTALL)
    if not match:
        raise SystemExit(f"missing source function {name}")
    return match.group(1)

def enum_variant_names(text: str, name: str, next_name: str) -> tuple[str, ...]:
    match = re.search(
        rf"(?ms)^    enum {re.escape(name)} is Node:\n(.*?)(?=^    enum {re.escape(next_name)} is Node:)" ,
        text,
    )
    if not match:
        raise SystemExit(f"AST enum {name} is missing")
    names = []
    for line in match.group(1).splitlines():
        if len(line) - len(line.lstrip(" \t")) != 8:
            continue
        variant = re.match(r"([A-Z][A-Za-z0-9_]*)(?:\(|$)", line.strip())
        if variant:
            names.append(variant.group(1))
    return tuple(names)

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
            variant = re.match(r"[A-Za-z_][A-Za-z0-9_]*", value[len(prefix):])
            if variant:
                names.append(variant.group(0))
    return tuple(names)

def direct_child(source: str, parent: str, child: str, occurrence: int = 0) -> bool:
    """Require one recursive edge to be a direct statement under its AST arm."""
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
    raise SystemExit("malformed literal-comparison source edge")

def wrap_direct_child_block(source: str, parent: str, child: str, occurrence: int = 0) -> str:
    """Move one expected route under an unreachable branch for a negative control."""
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

def validate_edge_set(source: str, edges: tuple[tuple, ...], label: str) -> None:
    for edge in edges:
        parent, child, occurrence = edge_parts(edge)
        if not direct_child(source, parent, child, occurrence):
            raise SystemExit(f"{label} walker is missing direct child route {parent} -> {child}")
        mutated = wrap_direct_child_block(source, parent, child, occurrence)
        if mutated == source or direct_child(mutated, parent, child, occurrence):
            raise SystemExit(f"{label} child-route negative control failed for {parent} -> {child}")

def validate_or_theorem(text: str, name: str, routes: dict[str, tuple], source: str,
                        edges: tuple[tuple, ...], label: str) -> None:
    match = re.search(
        rf"(?ms)^def {re.escape(name)}\((.*?)\)\s*-> bool:\n(.*?)(?=^def |\Z)",
        text,
    )
    if not match:
        raise SystemExit(f"missing child-coverage theorem {name}")
    parameters = tuple(re.findall(r"([A-Za-z_][A-Za-z0-9_]*): bool", match.group(1)))
    if parameters != tuple(routes):
        raise SystemExit(f"{name} proof inputs no longer match its source routes")
    expression = " or ".join(parameters)
    actual = compact_code(match.group(2))
    expected_forms = {
        compact_code(f"ensure result == {ensure_expression}\nreturn {return_expression}")
        for ensure_expression in (expression, f"({expression})")
        for return_expression in (expression, f"({expression})")
    }
    if actual not in expected_forms:
        raise SystemExit(f"{name} no longer proves the disjunction of all reachable child reports")
    edge_set = {edge_parts(edge) for edge in edges}
    for parameter, route_edges in routes.items():
        for edge in route_edges:
            normalized = edge_parts(edge)
            if normalized not in edge_set:
                raise SystemExit(f"{name} route {parameter} is not part of the {label} source inventory")
            parent, child, occurrence = normalized
            if not direct_child(source, parent, child, occurrence):
                raise SystemExit(f"{name} route {parameter} no longer reaches {parent} -> {child}")

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

EXPECTED_EXPR_NAMES = tuple("""Invalid Absent IntLit FloatLit StringLit CharLit BoolLit Ident Call
    StaticEffectCall Field Scope ShorthandMember Index Slice IndexN Binary Unary Move RegionNew Paren
    Array Tuple SetLit DictLit Construct RecordUpdate If Match Catch Comprehension Refinement GetElse Lambda Block""".split())

EXPECTED_STMT_NAMES = tuple("Invalid Expr Block VarDecl Assign If While For Return Break Continue Match Contract".split())

EXPECTED_DECL_NAMES = tuple("Invalid Func Struct Enum Alias Law Import Scoped Extern Const Module".split())

EXPECTED_SIDE_TABLE_FIELDS = {
    "ParamDecl": tuple("name:sview name_pos:Pos type_expression:Expr is_mutable:bool has_default:bool default_value:Expr is_affine:bool value_thread:bool".split()),
    "BitGroupMember": tuple("name:sview type_expression:Expr pos:Pos".split()),
    "StructMember": tuple("is_private:bool name:sview type_expression:Expr omittable:bool is_ghost:bool has_default:bool default_value:Expr region:sview bit_group_kind:sview bit_group_members:darray[BitGroupMember]".split()),
    "EnumVariant": tuple("name:sview fields:darray[Expr] field_names:darray[sview] value_expr:Expr".split()),
    "MatchArm": tuple("pattern:Pattern body:darray[Stmt] guard:Expr pos:Pos".split()),
    "FieldInit": tuple("name:sview value:Expr is_copy_base:bool".split()),
    "DictEntry": tuple("key:Expr value:Expr".split()),
    "StaticEffectCandidate": tuple("effect_type:Expr callee:sview captures:darray[Expr] effect_identity_id:u32 handler_identity_id:u32 callee_owner:sview".split()),
}

STATEMENT_EDGES = (
    ("Stmt.Expr(expression, line):", "table <- walk_expression_for_literal_comparison(expression, table, var_types, type_names)"),
    ("Stmt.Block(kind, clause, binding, body, line):", "table <- walk_statements_for_literal_comparison(body, table, var_types, type_names)"),
    ("Stmt.VarDecl(name, type_expression, value, line):", "table <- walk_expression_for_literal_comparison(type_expression, table, var_types, type_names)"),
    ("Stmt.VarDecl(name, type_expression, value, line):", "table <- walk_expression_for_literal_comparison(value, table, var_types, type_names)"),
    ("Stmt.Assign(target, operator, value, line):", "table <- walk_expression_for_literal_comparison(target, table, var_types, type_names)"),
    ("Stmt.Assign(target, operator, value, line):", "table <- walk_expression_for_literal_comparison(value, table, var_types, type_names)"),
    ("Stmt.If(condition, then_body, else_body, line):", "table <- walk_expression_for_literal_comparison(condition, table, var_types, type_names)"),
    ("Stmt.If(condition, then_body, else_body, line):", "table <- walk_statements_for_literal_comparison(then_body, table, var_types, type_names)"),
    ("Stmt.If(condition, then_body, else_body, line):", "table <- walk_statements_for_literal_comparison(else_body, table, var_types, type_names)"),
    ("Stmt.While(condition, body, line):", "table <- walk_expression_for_literal_comparison(condition, table, var_types, type_names)"),
    ("Stmt.While(condition, body, line):", "table <- walk_statements_for_literal_comparison(body, table, var_types, type_names)"),
    ("Stmt.For(bind, variables, iterable, body, line):", "table <- walk_expression_for_literal_comparison(iterable, table, var_types, type_names)"),
    ("Stmt.For(bind, variables, iterable, body, line):", "table <- walk_statements_for_literal_comparison(body, table, var_types, type_names)"),
    ("Stmt.Match(scrutinee, arms, line):", "table <- walk_expression_for_literal_comparison(scrutinee, table, var_types, type_names)"),
    ("Stmt.Match(scrutinee, arms, line):", "for arm in arms |table|:"),
    ("for arm in arms |table|:", "table <- walk_expression_for_literal_comparison(arm.guard, table, var_types, type_names)"),
    ("for arm in arms |table|:", "table <- walk_statements_for_literal_comparison(arm.body, table, var_types, type_names)"),
    ("Stmt.Return(value, line):", "if value is return_value:"),
    ("if value is return_value:", "table <- walk_expression_for_literal_comparison(return_value, table, var_types, type_names)"),
    ("Stmt.Contract(kind, expression, line):", "table <- walk_expression_for_literal_comparison(expression, table, var_types, type_names)"),
)

DECLARATION_EDGES = (
    ("Decl.Func(name, params, return_type, body, effects, decorators, line):", "for param in params |table|:"),
    ("for param in params |table|:", "table <- walk_expression_for_literal_comparison(param.type_expression, table, var_types, type_names)"),
    ("for param in params |table|:", "table <- walk_expression_for_literal_comparison(param.default_value, table, var_types, type_names)"),
    ("Decl.Func(name, params, return_type, body, effects, decorators, line):", "table <- walk_expression_for_literal_comparison(return_type, table, var_types, type_names)"),
    ("Decl.Func(name, params, return_type, body, effects, decorators, line):", "table <- walk_statements_for_literal_comparison(body, table, var_types, type_names)"),
    ("Decl.Struct(name, members, affinity, has_named_states, has_derive, invariants, line):", "for member in members |table|:"),
    ("for member in members |table|:", "table <- walk_expression_for_literal_comparison(member.type_expression, table, var_types, type_names)"),
    ("for member in members |table|:", "table <- walk_expression_for_literal_comparison(member.default_value, table, var_types, type_names)"),
    ("for member in members |table|:", "for bit_member in member.bit_group_members |table|:"),
    ("for bit_member in member.bit_group_members |table|:", "table <- walk_expression_for_literal_comparison(bit_member.type_expression, table, var_types, type_names)"),
    ("Decl.Struct(name, members, affinity, has_named_states, has_derive, invariants, line):", "for invariant in invariants |table|:"),
    ("for invariant in invariants |table|:", "table <- walk_expression_for_literal_comparison(invariant, table, var_types, type_names)"),
    ("Decl.Enum(name, variants, is_const, storage_type, line):", "table <- walk_expression_for_literal_comparison(storage_type, table, var_types, type_names)"),
    ("Decl.Enum(name, variants, is_const, storage_type, line):", "for variant in variants |table|:"),
    ("for variant in variants |table|:", "for field_type in variant.fields |table|:"),
    ("for field_type in variant.fields |table|:", "table <- walk_expression_for_literal_comparison(field_type, table, var_types, type_names)"),
    ("for variant in variants |table|:", "table <- walk_expression_for_literal_comparison(variant.value_expr, table, var_types, type_names)"),
    ("Decl.Alias(name, target, line):", "table <- walk_expression_for_literal_comparison(target, table, var_types, type_names)"),
    ("Decl.Law(name, predicate, line):", "table <- walk_expression_for_literal_comparison(predicate, table, var_types, type_names)"),
    ("Decl.Const(name, type_expression, value, is_mutable, line):", "table <- walk_expression_for_literal_comparison(type_expression, table, var_types, type_names)"),
    ("Decl.Const(name, type_expression, value, is_mutable, line):", "table <- walk_expression_for_literal_comparison(value, table, var_types, type_names)"),
    ("Decl.Module(module_name, body, line):", "table <- check_literal_comparison_declarations(body, table)"),
    ("Decl.Scoped(body, line):", "table <- check_literal_comparison_declarations(body, table)"),
)

EXPRESSION_PROOF_ROUTES = {
    "scrutinee_reported": (("Expr.Match(scrutinee, arms, line):", "table <- walk_expression_for_literal_comparison(scrutinee, table, var_types, type_names)"),),
    "guard_reported": (("for arm in arms |table|:", "table <- walk_expression_for_literal_comparison(arm.guard, table, var_types, type_names)", 0),),
    "body_reported": (("for arm in arms |table|:", "table <- walk_statements_for_literal_comparison(arm.body, table, var_types, type_names)", 0),),
    "guarded_reported": (("Expr.Catch(guarded, arms, line):", "table <- walk_expression_for_literal_comparison(guarded, table, var_types, type_names)"),),
    "arm_guard_reported": (("for arm in arms |table|:", "table <- walk_expression_for_literal_comparison(arm.guard, table, var_types, type_names)", 1),),
    "arm_body_reported": (("for arm in arms |table|:", "table <- walk_statements_for_literal_comparison(arm.body, table, var_types, type_names)", 1),),
    "capture_reported": (),
    "argument_reported": (),
    "child_reported": (("Expr.Unary(operator, operand, line):", "table <- walk_expression_for_literal_comparison(operand, table, var_types, type_names)"),),
    "base_reported": (("Expr.Refinement(base, predicate, line):", "table <- walk_expression_for_literal_comparison(base, table, var_types, type_names)"),),
    "predicate_reported": (("Expr.Refinement(base, predicate, line):", "table <- walk_expression_for_literal_comparison(predicate, table, var_types, type_names)"),),
    "recovery_reported": (("Expr.GetElse(guarded, recovery, line):", "table <- walk_statements_for_literal_comparison(recovery, table, var_types, type_names)"),),
    "get_else_guarded_reported": (("Expr.GetElse(guarded, recovery, line):", "table <- walk_expression_for_literal_comparison(guarded, table, var_types, type_names)"),),
}

EXPRESSION_PROOF_THEOREMS = {
    "proof_literal_comparison_match_children_reported": {
        "scrutinee_reported": EXPRESSION_PROOF_ROUTES["scrutinee_reported"],
        "guard_reported": EXPRESSION_PROOF_ROUTES["guard_reported"],
        "body_reported": EXPRESSION_PROOF_ROUTES["body_reported"],
    },
    "proof_literal_comparison_catch_children_reported": {
        "guarded_reported": EXPRESSION_PROOF_ROUTES["guarded_reported"],
        "arm_guard_reported": EXPRESSION_PROOF_ROUTES["arm_guard_reported"],
        "arm_body_reported": EXPRESSION_PROOF_ROUTES["arm_body_reported"],
    },
    "proof_literal_comparison_static_effect_children_reported": {
        "capture_reported": (),
        "argument_reported": (),
    },
    "proof_literal_comparison_unary_child_reported": {
        "child_reported": EXPRESSION_PROOF_ROUTES["child_reported"],
    },
    "proof_literal_comparison_refinement_children_reported": {
        "base_reported": EXPRESSION_PROOF_ROUTES["base_reported"],
        "predicate_reported": EXPRESSION_PROOF_ROUTES["predicate_reported"],
    },
    "proof_literal_comparison_get_else_children_reported": {
        "guarded_reported": EXPRESSION_PROOF_ROUTES["get_else_guarded_reported"],
        "recovery_reported": EXPRESSION_PROOF_ROUTES["recovery_reported"],
    },
}

STATEMENT_PROOF_ROUTES = {
    "expression": (("Stmt.Expr(expression, line):", "table <- walk_expression_for_literal_comparison(expression, table, var_types, type_names)"),),
    "variable_type": (("Stmt.VarDecl(name, type_expression, value, line):", "table <- walk_expression_for_literal_comparison(type_expression, table, var_types, type_names)"),),
    "variable_value": (("Stmt.VarDecl(name, type_expression, value, line):", "table <- walk_expression_for_literal_comparison(value, table, var_types, type_names)"),),
    "assignment_target": (("Stmt.Assign(target, operator, value, line):", "table <- walk_expression_for_literal_comparison(target, table, var_types, type_names)"),),
    "assignment_value": (("Stmt.Assign(target, operator, value, line):", "table <- walk_expression_for_literal_comparison(value, table, var_types, type_names)"),),
    "if_condition": (("Stmt.If(condition, then_body, else_body, line):", "table <- walk_expression_for_literal_comparison(condition, table, var_types, type_names)"),),
    "if_then_body": (("Stmt.If(condition, then_body, else_body, line):", "table <- walk_statements_for_literal_comparison(then_body, table, var_types, type_names)"),),
    "if_else_body": (("Stmt.If(condition, then_body, else_body, line):", "table <- walk_statements_for_literal_comparison(else_body, table, var_types, type_names)"),),
    "while_condition": (("Stmt.While(condition, body, line):", "table <- walk_expression_for_literal_comparison(condition, table, var_types, type_names)"),),
    "while_body": (("Stmt.While(condition, body, line):", "table <- walk_statements_for_literal_comparison(body, table, var_types, type_names)"),),
    "for_iterable": (("Stmt.For(bind, variables, iterable, body, line):", "table <- walk_expression_for_literal_comparison(iterable, table, var_types, type_names)"),),
    "for_body": (("Stmt.For(bind, variables, iterable, body, line):", "table <- walk_statements_for_literal_comparison(body, table, var_types, type_names)"),),
    "return_value": (("if value is return_value:", "table <- walk_expression_for_literal_comparison(return_value, table, var_types, type_names)"),),
    "block_body": (("Stmt.Block(kind, clause, binding, body, line):", "table <- walk_statements_for_literal_comparison(body, table, var_types, type_names)"),),
    "match_scrutinee": (("Stmt.Match(scrutinee, arms, line):", "table <- walk_expression_for_literal_comparison(scrutinee, table, var_types, type_names)"),),
    "match_guard": (("for arm in arms |table|:", "table <- walk_expression_for_literal_comparison(arm.guard, table, var_types, type_names)"),),
    "match_body": (("for arm in arms |table|:", "table <- walk_statements_for_literal_comparison(arm.body, table, var_types, type_names)"),),
    "contract_expression": (("Stmt.Contract(kind, expression, line):", "table <- walk_expression_for_literal_comparison(expression, table, var_types, type_names)"),),
}

DECLARATION_PROOF_ROUTES = {
    "parameter_type": (("for param in params |table|:", "table <- walk_expression_for_literal_comparison(param.type_expression, table, var_types, type_names)"),),
    "parameter_default": (("for param in params |table|:", "table <- walk_expression_for_literal_comparison(param.default_value, table, var_types, type_names)"),),
    "return_type": (("Decl.Func(name, params, return_type, body, effects, decorators, line):", "table <- walk_expression_for_literal_comparison(return_type, table, var_types, type_names)"),),
    "function_body": (("Decl.Func(name, params, return_type, body, effects, decorators, line):", "table <- walk_statements_for_literal_comparison(body, table, var_types, type_names)"),),
    "member_type": (("for member in members |table|:", "table <- walk_expression_for_literal_comparison(member.type_expression, table, var_types, type_names)"),),
    "member_default": (("for member in members |table|:", "table <- walk_expression_for_literal_comparison(member.default_value, table, var_types, type_names)"),),
    "bit_member_type": (("for bit_member in member.bit_group_members |table|:", "table <- walk_expression_for_literal_comparison(bit_member.type_expression, table, var_types, type_names)"),),
    "invariant": (("for invariant in invariants |table|:", "table <- walk_expression_for_literal_comparison(invariant, table, var_types, type_names)"),),
    "enum_storage_type": (("Decl.Enum(name, variants, is_const, storage_type, line):", "table <- walk_expression_for_literal_comparison(storage_type, table, var_types, type_names)"),),
    "enum_payload_type": (("for field_type in variant.fields |table|:", "table <- walk_expression_for_literal_comparison(field_type, table, var_types, type_names)"),),
    "enum_variant_value": (("for variant in variants |table|:", "table <- walk_expression_for_literal_comparison(variant.value_expr, table, var_types, type_names)"),),
    "alias_target": (("Decl.Alias(name, target, line):", "table <- walk_expression_for_literal_comparison(target, table, var_types, type_names)"),),
    "law_predicate": (("Decl.Law(name, predicate, line):", "table <- walk_expression_for_literal_comparison(predicate, table, var_types, type_names)"),),
    "const_type": (("Decl.Const(name, type_expression, value, is_mutable, line):", "table <- walk_expression_for_literal_comparison(type_expression, table, var_types, type_names)"),),
    "const_value": (("Decl.Const(name, type_expression, value, is_mutable, line):", "table <- walk_expression_for_literal_comparison(value, table, var_types, type_names)"),),
    "module_body": (("Decl.Module(module_name, body, line):", "table <- check_literal_comparison_declarations(body, table)"),),
    "scoped_body": (("Decl.Scoped(body, line):", "table <- check_literal_comparison_declarations(body, table)"),),
}

EXPRESSION_EDGES = (
    ("Expr.Binary(left, operator, right, line):", "table <- walk_expression_for_literal_comparison(left, table, var_types, type_names)"),
    ("Expr.Binary(left, operator, right, line):", "table <- walk_expression_for_literal_comparison(right, table, var_types, type_names)"),
    ("Expr.Call(callee, arguments, argument_names, line):", "table <- walk_expression_for_literal_comparison(callee, table, var_types, type_names)"),
    ("Expr.Call(callee, arguments, argument_names, line):", "for argument in arguments |table|:"),
    ("for argument in arguments |table|:", "table <- walk_expression_for_literal_comparison(argument, table, var_types, type_names)", 0),
    ("for argument in arguments |table|:", "table <- walk_expression_for_literal_comparison(argument, table, var_types, type_names)", 1),
    ("Expr.StaticEffectCall(effect_type, operation, candidates, arguments, argument_names, line):", "for child in Ast::effect_runtime_children(candidates, arguments) |table|:"),
    ("for child in Ast::effect_runtime_children(candidates, arguments) |table|:", "table <- walk_expression_for_literal_comparison(child, table, var_types, type_names)"),
    ("Expr.Field(object, field, line):", "table <- walk_expression_for_literal_comparison(object, table, var_types, type_names)"),
    ("Expr.Scope(base, name, line):", "table <- walk_expression_for_literal_comparison(base, table, var_types, type_names)"),
    ("Expr.Index(object, index, line):", "table <- walk_expression_for_literal_comparison(object, table, var_types, type_names)"),
    ("Expr.Index(object, index, line):", "table <- walk_expression_for_literal_comparison(index, table, var_types, type_names)"),
    ("Expr.Unary(operator, operand, line):", "table <- walk_expression_for_literal_comparison(operand, table, var_types, type_names)"),
    ("Expr.Move(operand, line):", "table <- walk_expression_for_literal_comparison(operand, table, var_types, type_names)"),
    ("Expr.RegionNew(operand, region, line):", "table <- walk_expression_for_literal_comparison(operand, table, var_types, type_names)"),
    ("Expr.Paren(inner, line):", "table <- walk_expression_for_literal_comparison(inner, table, var_types, type_names)"),
    ("Expr.Array(elements, line):", "for element in elements |table|:", 0),
    ("Expr.Tuple(elements, line):", "for element in elements |table|:"),
    ("Expr.SetLit(elements, line):", "for element in elements |table|:"),
    ("for element in elements |table|:", "table <- walk_expression_for_literal_comparison(element, table, var_types, type_names)", 0),
    ("for element in elements |table|:", "table <- walk_expression_for_literal_comparison(element, table, var_types, type_names)", 1),
    ("for element in elements |table|:", "table <- walk_expression_for_literal_comparison(element, table, var_types, type_names)", 2),
    ("Expr.Slice(object, low, high, line):", "table <- walk_expression_for_literal_comparison(object, table, var_types, type_names)"),
    ("Expr.Slice(object, low, high, line):", "table <- walk_expression_for_literal_comparison(low, table, var_types, type_names)"),
    ("Expr.Slice(object, low, high, line):", "table <- walk_expression_for_literal_comparison(high, table, var_types, type_names)"),
    ("Expr.IndexN(object, arguments, line):", "table <- walk_expression_for_literal_comparison(object, table, var_types, type_names)"),
    ("Expr.IndexN(object, arguments, line):", "for argument in arguments |table|:"),
    ("Expr.DictLit(entries, line):", "for entry in entries |table|:"),
    ("for entry in entries |table|:", "table <- walk_expression_for_literal_comparison(entry.key, table, var_types, type_names)"),
    ("for entry in entries |table|:", "table <- walk_expression_for_literal_comparison(entry.value, table, var_types, type_names)"),
    ("Expr.Construct(type_expression, fields, line):", "table <- walk_expression_for_literal_comparison(type_expression, table, var_types, type_names)"),
    ("Expr.Construct(type_expression, fields, line):", "for field in fields |table|:"),
    ("Expr.RecordUpdate(base, fields, line):", "table <- walk_expression_for_literal_comparison(base, table, var_types, type_names)"),
    ("Expr.RecordUpdate(base, fields, line):", "for field in fields |table|:"),
    ("for field in fields |table|:", "table <- walk_expression_for_literal_comparison(field.value, table, var_types, type_names)", 0),
    ("for field in fields |table|:", "table <- walk_expression_for_literal_comparison(field.value, table, var_types, type_names)", 1),
    ("Expr.If(condition, then_expr, else_expr, line):", "table <- walk_expression_for_literal_comparison(condition, table, var_types, type_names)"),
    ("Expr.If(condition, then_expr, else_expr, line):", "table <- walk_expression_for_literal_comparison(then_expr, table, var_types, type_names)"),
    ("Expr.If(condition, then_expr, else_expr, line):", "table <- walk_expression_for_literal_comparison(else_expr, table, var_types, type_names)"),
    ("Expr.Comprehension(loop_variable, iterable, condition, body, line, _):", "table <- walk_expression_for_literal_comparison(iterable, table, var_types, type_names)"),
    ("Expr.Comprehension(loop_variable, iterable, condition, body, line, _):", "table <- walk_expression_for_literal_comparison(condition, table, var_types, type_names)"),
    ("Expr.Comprehension(loop_variable, iterable, condition, body, line, _):", "table <- walk_expression_for_literal_comparison(body, table, var_types, type_names)"),
    ("Expr.Lambda(parameters, body, line):", "table <- walk_statements_for_literal_comparison(body, table, var_types, type_names)"),
    ("Expr.Block(statements, value, captures, line):", "table <- walk_statements_for_literal_comparison(statements, table, var_types, type_names)"),
    ("Expr.Block(statements, value, captures, line):", "table <- walk_expression_for_literal_comparison(value, table, var_types, type_names)"),
    ("Expr.Match(scrutinee, arms, line):", "table <- walk_expression_for_literal_comparison(scrutinee, table, var_types, type_names)"),
    ("Expr.Match(scrutinee, arms, line):", "for arm in arms |table|:"),
    ("Expr.Catch(guarded, arms, line):", "table <- walk_expression_for_literal_comparison(guarded, table, var_types, type_names)"),
    ("Expr.Catch(guarded, arms, line):", "for arm in arms |table|:"),
    ("for arm in arms |table|:", "table <- walk_expression_for_literal_comparison(arm.guard, table, var_types, type_names)", 0),
    ("for arm in arms |table|:", "table <- walk_statements_for_literal_comparison(arm.body, table, var_types, type_names)", 0),
    ("for arm in arms |table|:", "table <- walk_expression_for_literal_comparison(arm.guard, table, var_types, type_names)", 1),
    ("for arm in arms |table|:", "table <- walk_statements_for_literal_comparison(arm.body, table, var_types, type_names)", 1),
    ("Expr.Refinement(base, predicate, line):", "table <- walk_expression_for_literal_comparison(base, table, var_types, type_names)"),
    ("Expr.Refinement(base, predicate, line):", "table <- walk_expression_for_literal_comparison(predicate, table, var_types, type_names)"),
    ("Expr.GetElse(guarded, recovery, line):", "table <- walk_expression_for_literal_comparison(guarded, table, var_types, type_names)"),
    ("Expr.GetElse(guarded, recovery, line):", "table <- walk_statements_for_literal_comparison(recovery, table, var_types, type_names)"),
)
