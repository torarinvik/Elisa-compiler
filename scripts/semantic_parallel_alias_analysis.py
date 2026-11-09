"""Alias analysis for the semantic parallel-pass audit."""
import collections
from functools import lru_cache
import os
import re
import sys


def local_table_aliases(_services, text, tables):
    """Track simple local aliases and borrows of whole SymbolTables."""
    if not tables:
        return set()
    bare_name = _services['BORROWED_NAME_PREFIX'] + r"(\w+)(?:\s*\))*"
    assignment = re.compile(
        r"^\s*(\w+)\s*(?::[^=\n]+)?\s*(?:<-|=)\s*" + bare_name + r"\s*$",
        re.MULTILINE,
    )
    aliases = set()
    changed = True
    while changed:
        changed = False
        for match in assignment.finditer(text):
            target, source = match.group(1), match.group(2)
            if source in tables or source in aliases:
                if target not in tables and target not in aliases:
                    aliases.add(target)
                    changed = True
    return aliases

def local_global_aliases(_services, text, globals_, mutable_ref_globals):
    """Track simple local aliases of mutable globals and their nested fields."""
    if not globals_:
        return set(), set()
    global_names = "(?:" + "|".join(sorted(map(re.escape, globals_))) + ")"
    global_path = r"(?P<global_root>" + global_names + r")(?:(?:\s*\.\s*\w+)|(?:\s*\[[^\]\n]*\]))*"
    alias_path = r"(\w+)(?:(?:\s*\.\s*\w+)|(?:\s*\[[^\]\n]*\]))*"
    borrowed_prefix = r"(?:\(\s*)*&\s*(?:\(\s*)*"
    assignment = re.compile(
        r"^\s*(\w+)\s*(?::[^=\n]+)?\s*(?:<-|=)\s*"
        + _services['BORROWED_NAME_PREFIX'] + global_path + r"(?:\s*\))*\s*$",
        re.MULTILINE,
    )
    borrowed_global_assignment = re.compile(
        r"^\s*(\w+)\s*(?::[^=\n]+)?\s*(?:<-|=)\s*"
        + borrowed_prefix + global_path + r"(?:\s*\))*\s*$",
        re.MULTILINE,
    )
    alias_assignment = re.compile(
        r"^\s*(\w+)\s*(?::[^=\n]+)?\s*(?:<-|=)\s*"
        + _services['BORROWED_NAME_PREFIX'] + alias_path + r"(?:\s*\))*\s*$",
        re.MULTILINE,
    )
    borrowed_alias_assignment = re.compile(
        r"^\s*(\w+)\s*(?::[^=\n]+)?\s*(?:<-|=)\s*"
        + borrowed_prefix + alias_path + r"(?:\s*\))*\s*$",
        re.MULTILINE,
    )
    aliases = set()
    borrowed_aliases = set()
    changed = True
    while changed:
        changed = False
        for match in assignment.finditer(text):
            target = match.group(1)
            if target not in aliases and target not in globals_:
                aliases.add(target)
                changed = True
            if match.group("global_root") in mutable_ref_globals and target not in globals_:
                if target not in borrowed_aliases:
                    borrowed_aliases.add(target)
                    changed = True
        for match in borrowed_global_assignment.finditer(text):
            target = match.group(1)
            if target not in globals_:
                if target not in aliases:
                    aliases.add(target)
                    changed = True
                if target not in borrowed_aliases:
                    borrowed_aliases.add(target)
                    changed = True
        for match in alias_assignment.finditer(text):
            target, source = match.group(1), match.group(2)
            if source in aliases and target not in aliases and target not in globals_:
                aliases.add(target)
                changed = True
            if source in borrowed_aliases and target not in borrowed_aliases and target not in globals_:
                borrowed_aliases.add(target)
                changed = True
        for match in borrowed_alias_assignment.finditer(text):
            target, source = match.group(1), match.group(2)
            if source in aliases and target not in aliases and target not in globals_:
                aliases.add(target)
                changed = True
            if source in aliases and target not in borrowed_aliases and target not in globals_:
                borrowed_aliases.add(target)
                changed = True
    return aliases, borrowed_aliases

def mutable_cast_source_names(_services, parameters, text, aliases, structs, additional_sources=()):
    """Names whose reference/view-derived storage may reach a mutable pointer cast."""
    # Globals are identifiers: tokenize the body once instead of searching it
    # once per global. Keep the original matching rule for compound spellings.
    words = set(re.findall(r"\w+", text))
    names = {
        name for name in additional_sources
        if name in words or (
            not re.fullmatch(r"\w+", name)
            and re.search(r"\b" + re.escape(name) + r"\b", text)
        )
    }
    for formal in _services['split_top_level_arguments'](parameters):
        match = re.match(r"\s*(\w+)\s*:\s*(.+?)\s*(?:=(?!=).*)?$", formal)
        if match:
            formal_type = match.group(2)
            if (
                re.search(r"\b(?:mutable|lmut)\b|&", formal_type)
                or _services['type_may_contain_reference'](formal_type, aliases, structs)
            ):
                names.add(match.group(1))
    typed_local = re.compile(
        r"^[ \t]*(\w+)[ \t]*:[ \t]*(.+?)[ \t]*(?:<-|=(?!=))",
        re.MULTILINE,
    )
    for match in typed_local.finditer(text):
        local_type = match.group(2).strip()
        if (
            re.search(r"\b(?:mutable|lmut)\b|&", local_type)
            or _services['type_may_contain_reference'](local_type, aliases, structs)
        ):
            names.add(match.group(1))
    assignment = re.compile(
        r"^[ \t]*(\w+)[ \t]*(?::[^=\n]+)?[ \t]*(?:<-|=(?!=))[ \t]*(.*?)[ \t]*$",
        re.MULTILINE,
    )
    assignments = [
        (match.group(1), match.group(2), set(re.findall(r"\w+", match.group(2))))
        for match in assignment.finditer(text)
    ]
    compound_names = {name for name in names if not re.fullmatch(r"\w+", name)}
    changed = True
    while changed:
        changed = False
        for target, value, value_words in assignments:
            if target not in names and (
                not names.isdisjoint(value_words) or any(
                    re.search(r"\b" + re.escape(source) + r"\b", value)
                    for source in compound_names
                )
            ):
                names.add(target)
                changed = True
    return names

def local_table_field_aliases(_services, text, tables, table_field_types, type_aliases, struct_field_types):
    """Track simple local aliases of SymbolTable fields for mutation checks at callsites."""
    if not tables:
        return set(), set(), set()
    table_names = "(?:" + "|".join(sorted(map(re.escape, tables))) + ")"
    field_aliases = set()
    diagnostic_aliases = set()
    borrowed_aliases = set()
    borrowed_prefix = r"(?:\(\s*)*&\s*(?:\(\s*)*"
    local_types = {
        match.group(1): match.group(2).strip()
        for match in re.finditer(
            r"^[ \t]*(\w+)[ \t]*:[ \t]*(.+?)[ \t]*(?:<-|=(?!=))",
            text,
            re.MULTILINE,
        )
    }
    plain_group_prefix = r"(?:\(\s*)*"
    field_assignment = re.compile(
        r"^\s*(\w+)\s*(?::\s*([^=\n]+?))?\s*(?:<-|=)\s*"
        + plain_group_prefix
        + table_names + r"\.(\w+)\b(?:(?:\.\w+)|(?:\[[^\]\n]*\]))*(?:\s*\))*\s*$",
        re.MULTILINE,
    )
    alias_assignment = re.compile(
        r"^\s*(\w+)\s*(?::[^=\n]+)?\s*(?:<-|=)\s*"
        + _services['BORROWED_NAME_PREFIX']
        + r"(\w+)(?:(?:\s*\.\s*\w+)|(?:\s*\[[^\]\n]*\]))*(?:\s*\))*\s*$",
        re.MULTILINE,
    )
    borrowed_field_assignment = re.compile(
        r"^\s*(\w+)\s*(?::[^=\n]+)?\s*(?:<-|=)\s*"
        + borrowed_prefix + table_names + r"\.(\w+)\b(?:(?:\s*\.\s*\w+)|(?:\s*\[[^\]\n]*\]))*(?:\s*\))*\s*$",
        re.MULTILINE,
    )
    borrowed_alias_assignment = re.compile(
        r"^\s*(\w+)\s*(?::[^=\n]+)?\s*(?:<-|=)\s*"
        + borrowed_prefix
        + r"(\w+)(?:(?:\s*\.\s*\w+)|(?:\s*\[[^\]\n]*\]))*(?:\s*\))*\s*$",
        re.MULTILINE,
    )
    for match in field_assignment.finditer(text):
        target_name, declared_type, field_name = match.groups()
        source_type = declared_type or table_field_types.get(field_name, "")
        line_start = text.rfind("\n", 0, match.start()) + 1
        line_end = text.find("\n", match.start())
        assignment = text[line_start:line_end if line_end >= 0 else len(text)]
        rhs = re.split(r"(?:<-|=(?!=))", assignment, maxsplit=1)[-1].strip()
        expression_type = _services['table_field_expression_type'](
            rhs, tables, table_field_types, type_aliases, struct_field_types
        )
        declared_is_copy = bool(
            declared_type
            and _services['type_is_copy_value'](declared_type, type_aliases, struct_field_types)
        )
        expression_is_copy = bool(
            expression_type
            and _services['type_is_copy_value'](expression_type, type_aliases, struct_field_types)
        )
        source_is_copy = (
            declared_is_copy and (not expression_type or expression_is_copy)
            if declared_type
            else expression_is_copy
            or bool(source_type and _services['type_is_copy_value'](source_type, type_aliases, struct_field_types))
        )
        if source_is_copy and not _services['type_may_contain_reference'](
            source_type, type_aliases, struct_field_types
        ) and (not expression_type or not _services['type_may_contain_reference'](
            expression_type, type_aliases, struct_field_types
        )):
            continue
        target = diagnostic_aliases if field_name == "diagnostics" else field_aliases
        target.add(target_name)
    for match in borrowed_field_assignment.finditer(text):
        target = diagnostic_aliases if match.group(2) == "diagnostics" else field_aliases
        target.add(match.group(1))
        borrowed_aliases.add(match.group(1))
    changed = True
    while changed:
        changed = False
        for match in alias_assignment.finditer(text):
            target_name, source_name = match.group(1), match.group(2)
            target_type = local_types.get(target_name, "")
            if _services['type_is_copy_value'](target_type, type_aliases, struct_field_types) and not _services['type_may_contain_reference'](
                target_type, type_aliases, struct_field_types
            ):
                continue
            if source_name in field_aliases and target_name not in field_aliases:
                field_aliases.add(target_name)
                changed = True
            if source_name in diagnostic_aliases and target_name not in diagnostic_aliases:
                diagnostic_aliases.add(target_name)
                changed = True
            if source_name in borrowed_aliases and target_name not in borrowed_aliases:
                borrowed_aliases.add(target_name)
                changed = True
        for match in borrowed_alias_assignment.finditer(text):
            target_name, source_name = match.group(1), match.group(2)
            if source_name in field_aliases and target_name not in field_aliases:
                field_aliases.add(target_name)
                changed = True
            if source_name in diagnostic_aliases and target_name not in diagnostic_aliases:
                diagnostic_aliases.add(target_name)
                changed = True
            if source_name in field_aliases or source_name in diagnostic_aliases:
                if target_name not in borrowed_aliases:
                    borrowed_aliases.add(target_name)
                    changed = True
    return field_aliases, diagnostic_aliases, borrowed_aliases

def immutable_table_field_borrow_starts(_services, text, tables):
    """Locations of direct table-field borrows stored in explicitly immutable refs.

    A bare `T&` local cannot mutate its referent; `mutable T&` and `lmut T&` can.
    The caller still tracks the local as a table-backed alias, so forwarding it to a
    mutable formal or returning it remains rejected by the usual escape checks.
    Only a single-line, explicitly typed direct borrow is recognized here.
    """
    if not tables:
        return set()
    table_names = "(?:" + "|".join(sorted(map(re.escape, tables))) + ")"
    assignment = re.compile(
        r"^[ \t]*\w+[ \t]*:[ \t]*(?P<type>[^=\n]+?)[ \t]*(?:<-|=(?!=))[ \t]*"
        r"(?P<rhs>(?:\([ \t]*)*&[ \t]*(?:\([ \t]*)*" + table_names
        + r"\.(?:\w+)(?:(?:\s*\.\s*\w+)|(?:\s*\[[^\]\n]*\]))*(?:\s*\))*)[ \t]*$",
        re.MULTILINE,
    )
    borrow = re.compile(r"&[ \t]*(?:" + table_names + r")\s*\.\s*\w+\b")
    starts = set()
    for match in assignment.finditer(text):
        type_expression = match.group("type").strip()
        if not type_expression.endswith("&") or re.search(r"\b(?:mutable|lmut)\b", type_expression):
            continue
        rhs_borrow = borrow.search(match.group("rhs"))
        if rhs_borrow is not None:
            starts.add(match.start("rhs") + rhs_borrow.start())
    return starts

def argument_is_table_field_or_alias(_services, argument, tables, aliases):
    if tables:
        table_names = "(?:" + "|".join(sorted(map(re.escape, tables))) + ")"
        if re.search(r"\b" + table_names + r"\s*(?:\.\s*\w+|\[[^\]\n]*\])", argument):
            return True
    return any(re.search(r"\b" + re.escape(alias) + r"\b", argument) for alias in aliases)

def table_field_expression_type(_services, argument, tables, table_field_types, type_aliases, struct_field_types):
    """Resolve a simple table-field path to its value type, including indexed elements."""
    expression = argument.strip()
    if expression.startswith("&"):
        return ""
    while expression.startswith("(") and _services['matching_delimiter'](expression, 0) == len(expression) - 1:
        expression = expression[1:-1].strip()
    root = re.match(r"(\w+)\s*\.\s*(\w+)", expression)
    if root is None or root.group(1) not in tables:
        return ""
    current_type = table_field_types.get(root.group(2), "")
    if not current_type:
        return ""
    cursor = root.end()
    while cursor < len(expression):
        while cursor < len(expression) and expression[cursor].isspace():
            cursor += 1
        if cursor >= len(expression):
            return current_type
        if expression[cursor] == ".":
            member = re.match(r"\s*\.\s*(\w+)", expression[cursor:])
            if member is None:
                return ""
            owner_name = re.sub(r"^(?:(?:mutable|static|heap|stack)\s+)+", "", current_type.strip())
            owner_name = owner_name.rsplit("::", 1)[-1]
            schemas = struct_field_types.get(owner_name, ())
            member_types = [schema[member.group(1)] for schema in schemas if isinstance(schema, dict) and member.group(1) in schema]
            if not member_types and member.group(1) == "count":
                container = re.sub(
                    r"^(?:(?:mutable|static|heap|stack)\s+)+", "", current_type.strip()
                )
                if re.match(r"(?:\w+::)?(?:darray|array|dict|map|set|sview)\b", container):
                    member_types = ["usize"]
            if not member_types or any(value != member_types[0] for value in member_types):
                return ""
            current_type = member_types[0]
            cursor += member.end()
        elif expression[cursor] == "[":
            close = _services['matching_delimiter'](expression, cursor)
            if close is None:
                return ""
            container_type = re.sub(r"^(?:(?:mutable|static|heap|stack)\s+)+", "", current_type.strip())
            container_name = re.match(r"(?:\w+::)*([\w]+)\s*\[", container_type)
            if container_name is None:
                return ""
            type_open = container_type.find("[")
            type_close = _services['matching_delimiter'](container_type, type_open)
            if type_close is None:
                return ""
            type_args = _services['split_top_level_arguments'](container_type[type_open + 1:type_close])
            if not type_args:
                return ""
            if container_name.group(1) in {"dict", "map", "HashMap", "Dict"} and len(type_args) > 1:
                current_type = type_args[1]
            else:
                current_type = type_args[0]
            cursor = close + 1
        else:
            return ""
    return current_type

def local_declaration_types(_services, text):
    """Parse each body once across its many receiver and field-path queries."""
    local_types = {
        match.group(1): match.group(2).strip()
        for match in re.finditer(
            r"^[ \t]*(\w+)[ \t]*:[ \t]*(.+?)[ \t]*(?:<-|=(?!=))", text, re.MULTILINE
        )
    }
    header = _services['DEF_RE'].match(text)
    if header:
        for formal in _services['split_top_level_arguments'](header.group(3)):
            match = re.match(r"\s*(\w+)\s*:\s*(.+?)\s*(?:=(?!=).*)?$", formal)
            if match:
                local_types[match.group(1)] = match.group(2).strip()
    return local_types

def local_path_expression_type(_services, expression, text, struct_field_types):
    """Resolve a simple local or local-struct-field type from its declaration."""
    path = re.fullmatch(r"\s*(\w+)((?:\s*\.\s*\w+)*)\s*", expression)
    if path is None:
        return ""
    local_types = _services['local_declaration_types'](text)
    current_type = local_types.get(path.group(1), "")
    for member in re.findall(r"\.\s*(\w+)", path.group(2)):
        owner = re.sub(r"^(?:(?:mutable|static|heap|stack)\s+)+", "", current_type.strip())
        owner = owner.rstrip("&?").strip()
        owner = owner.rsplit("::", 1)[-1]
        schemas = struct_field_types.get(owner, ())
        member_types = [
            schema[member]
            for schema in schemas
            if isinstance(schema, dict) and member in schema
        ]
        if not member_types and member == "count":
            container = re.sub(
                r"^(?:(?:mutable|lmut|static|heap|stack)\s+)+", "", current_type.strip()
            ).rstrip("&?").strip()
            if re.match(r"(?:\w+::)?(?:darray|array|dict|map|set|sview)\b", container):
                member_types = ["usize"]
        if not member_types or any(candidate != member_types[0] for candidate in member_types):
            return ""
        current_type = member_types[0]
    return current_type

def returned_shared_paths_are_copies(_services, 
    expression, text, tables, field_aliases, diagnostic_aliases,
    table_field_types, type_aliases, struct_field_types,
):
    """Prove every returned path into shared state is a non-reference copy value."""
    roots = tables | field_aliases | diagnostic_aliases
    if not roots:
        return False
    paths = []
    for root in sorted(roots):
        pattern = re.compile(
            r"\b" + re.escape(root)
            + r"((?:\s*\.\s*\w+|\s*\[[^\]\n]*\])*)"
        )
        paths.extend(match.group(0) for match in pattern.finditer(expression))
    if not paths:
        return False
    for path in paths:
        value_type = _services['table_field_expression_type'](
            path, tables, table_field_types, type_aliases, struct_field_types
        )
        if not value_type:
            value_type = _services['local_path_expression_type'](path, text, struct_field_types)
        if not value_type or not _services['type_is_copy_value'](
            value_type, type_aliases, struct_field_types
        ) or _services['type_may_contain_reference'](value_type, type_aliases, struct_field_types):
            return False
    return True
