"""Source inspection and recursive traversal facts for division proofs."""
import re


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
    "Expr.Comprehension(loop_variable, iterable, condition, body, line, _): table <- walk_expression_for_division_by_zero(iterable, table) table <- walk_expression_for_division_by_zero(condition, table) table <- walk_expression_for_division_by_zero(body, table)",
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
    ("match expression:", "Expr.Comprehension(loop_variable, iterable, condition, body, line, _):"),
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
    ("Expr.Comprehension(loop_variable, iterable, condition, body, line, _):", "table <- walk_expression_for_division_by_zero(iterable, table)"),
    ("Expr.Comprehension(loop_variable, iterable, condition, body, line, _):", "table <- walk_expression_for_division_by_zero(condition, table)"),
    ("Expr.Comprehension(loop_variable, iterable, condition, body, line, _):", "table <- walk_expression_for_division_by_zero(body, table)"),
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
    ("Decl.Func(name, params, return_type, body, effects, decorators, line):", "table <- walk_expression_for_division_by_zero(declared_return, table) if return_type is declared_return"),
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
        "return_type": (("declaration", "Decl.Func(name, params, return_type, body, effects, decorators, line):", "table <- walk_expression_for_division_by_zero(declared_return, table) if return_type is declared_return"),),
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
