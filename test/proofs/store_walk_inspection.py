"""Inspect source structure for store-through traversal proofs."""
from __future__ import annotations

import re


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

FOR_ITERATOR_STATEMENT = "Stmt.For(bind, loop_variables, iterable, loop_body, _):"

FOR_ITERATOR_BINDER_LOOP = "for loop_variable_index in 0..<loop_variables.count |loop_flow, loop_variables|:"

FOR_ITERATOR_BIND = "chv_flow_bind(loop_flow, loop_variable, false, loop_variable_may_be_owned_view, loop_variable_may_alias_reference)"

FOR_ITERATOR_BODY_WALK = "table <- chv_walk_statements(loop_body, in_region, ref_params, binders, owned, view_names, view_values, loop_flow, summary, table)"

def validate_for_iterator_direct_routes(arm: str, full_source: str, label: str) -> None:
    """Require the per-variable bind and body walk to be direct, unconditional children."""
    if not direct_child(arm, FOR_ITERATOR_BINDER_LOOP, FOR_ITERATOR_BIND):
        raise SystemExit(f"{label} misses direct loop-variable bind")
    if not direct_child(full_source, FOR_ITERATOR_STATEMENT, FOR_ITERATOR_BODY_WALK):
        raise SystemExit(f"{label} misses direct loop-body walk")

def validate_for_iterator_order_self_cases() -> None:
    """Keep postfix guards and missing/misordered loop merges outside accepted routes."""
    statement = FOR_ITERATOR_STATEMENT
    iterable_walk = "table <- chv_walk_expression(iterable, in_region, ref_params, binders, owned, view_names, view_values, flow, summary, table)"
    branch_mark = "branch_mark: usize = flow.names.count"
    loop_flow = "loop_flow: mutable CHVViewFlow = chv_flow_clone(flow)"
    binder_loop = FOR_ITERATOR_BINDER_LOOP
    bind = FOR_ITERATOR_BIND
    body_walk = FOR_ITERATOR_BODY_WALK
    merge = "chv_flow_merge(flow, loop_flow, branch_mark)"
    required_order = (iterable_walk, branch_mark, loop_flow, binder_loop, bind, body_walk, merge)
    arm = "\n".join((
        statement,
        f"    {iterable_walk}",
        f"    {branch_mark}",
        f"    {loop_flow}",
        f"    {binder_loop}",
        f"        {bind}",
        f"    {body_walk}",
        f"    {merge}",
    ))

    def require_order_rejection(source: str, label: str) -> None:
        try:
            validate_ordered_source_lines(source, required_order, label)
        except SystemExit:
            return
        raise SystemExit(f"for-iterator order self-case accepted {label}")

    validate_ordered_source_lines(arm, required_order, "valid for-iterator route")
    validate_for_iterator_direct_routes(arm, arm, "valid for-iterator route self-case")

    postfix_bind = arm.replace(bind, bind + " if false", 1)
    try:
        validate_for_iterator_direct_routes(postfix_bind, postfix_bind, "postfix-guarded binder")
    except SystemExit:
        pass
    else:
        raise SystemExit("for-iterator route self-case accepted a postfix-guarded binder")
    require_order_rejection(postfix_bind, "postfix-guarded binder")

    postfix_body = arm.replace(body_walk, body_walk + " if false", 1)
    try:
        validate_for_iterator_direct_routes(postfix_body, postfix_body, "postfix-guarded body walk")
    except SystemExit:
        pass
    else:
        raise SystemExit("for-iterator route self-case accepted a postfix-guarded body walk")
    require_order_rejection(postfix_body, "postfix-guarded body walk")

    guarded_bind = arm.replace(f"        {bind}", f"        if false:\n            {bind}", 1)
    try:
        validate_for_iterator_direct_routes(guarded_bind, guarded_bind, "nested-guarded binder")
    except SystemExit:
        pass
    else:
        raise SystemExit("for-iterator route self-case accepted a nested guarded binder")
    guarded_body = arm.replace(f"    {body_walk}", f"    if false:\n        {body_walk}", 1)
    try:
        validate_for_iterator_direct_routes(guarded_body, guarded_body, "nested-guarded body walk")
    except SystemExit:
        pass
    else:
        raise SystemExit("for-iterator route self-case accepted a nested guarded body walk")

    merge_before_body = arm.replace(f"    {body_walk}\n    {merge}", f"    {merge}\n    {body_walk}", 1)
    require_order_rejection(merge_before_body, "pre-body merge")
    missing_merge = arm.replace(f"\n    {merge}", "", 1)
    require_order_rejection(missing_merge, "missing post-body merge")

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
