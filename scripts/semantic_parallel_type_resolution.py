"""Type resolution for the semantic parallel-pass audit."""
import collections
from functools import lru_cache
import os
import re
import sys


def is_builtin_darray_type(_services, type_expression, aliases, seen=frozenset()):
    expression = re.sub(
        r"^(?:(?:mutable|static|heap|stack)\s+)+", "", type_expression.strip()
    )
    if re.match(r"(?:\w+::)?darray\s*\[", expression):
        return True
    if not re.fullmatch(r"(?:\w+::)*\w+", expression):
        return False
    name = expression.rsplit("::", 1)[-1]
    if name in seen:
        return False
    candidates = aliases.get(name, ())
    return bool(candidates) and all(
        _services['is_builtin_darray_type'](candidate, aliases, seen | {name})
        for candidate in candidates
    )

def is_builtin_scalar_type(_services, type_expression, aliases, seen=frozenset()):
    expression = re.sub(
        r"^(?:(?:mutable|static|heap|stack)\s+)+", "", type_expression.strip()
    )
    if not re.fullmatch(r"(?:\w+::)*\w+", expression):
        return False
    name = expression.rsplit("::", 1)[-1]
    if name in _services['COPY_VALUE_TYPE_NAMES'] | {"uintptr"}:
        return True
    if name in seen:
        return False
    candidates = aliases.get(name, ())
    return bool(candidates) and all(
        _services['is_builtin_scalar_type'](candidate, aliases, seen | {name})
        for candidate in candidates
    )

def function_return_type(_services, definition):
    """Read the declared return type from a definition's first source line."""
    body = definition.get("body", ())
    if not body:
        return ""
    header = body[0].strip()
    arrow = header.find("->")
    if arrow < 0:
        return ""
    expression = header[arrow + 2:].strip()
    if expression.endswith(":"):
        expression = expression[:-1].rstrip()
    return re.split(r"\s+can\b", expression, maxsplit=1)[0].strip()

def type_equivalents(_services, type_expression, aliases):
    """Return unambiguous spelling paths for a simple source type/alias."""
    def normalize(expression):
        expression = expression.strip()
        while expression.startswith("(") and _services['matching_delimiter'](expression, 0) == len(expression) - 1:
            expression = expression[1:-1].strip()
        expression = re.sub(
            r"^(?:(?:mutable|lmut|static|heap|stack)\s+)+", "", expression
        )
        return expression if re.fullmatch(r"(?:\w+::)*\w+", expression) else ""

    initial = normalize(type_expression)
    if not initial:
        return set()
    found, pending = set(), [initial]
    while pending:
        spelling = pending.pop()
        if spelling in found:
            continue
        found.add(spelling)
        terminal = spelling.rsplit("::", 1)[-1]
        for candidate in aliases.get(terminal, ()):
            normalized = normalize(candidate)
            if normalized and normalized not in found:
                pending.append(normalized)
    return found

def receiver_dispatch_type_key(_services, type_expression):
    """Normalize the outer borrow/region spelling for receiver dispatch matching."""
    expression = type_expression.strip()
    while expression.startswith("(") and _services['matching_delimiter'](expression, 0) == len(expression) - 1:
        expression = expression[1:-1].strip()
    expression = re.sub(
        r"^(?:(?:mutable|lmut|static|heap|stack)\s+)+", "", expression
    )
    # Regions affect the lifetime of a borrow, not the receiver's nominal type.
    expression = re.sub(r"\s+@[A-Za-z_]\w*", "", expression)
    expression = re.sub(r"\s+", "", expression)
    while expression.endswith("&"):
        expression = expression[:-1]
    return expression

def receiver_dispatch_type_equivalents(_services, type_expression, aliases):
    """Resolve only unambiguous aliases while retaining generic receiver spellings."""
    first = _services['receiver_dispatch_type_key'](type_expression)
    if not first:
        return set()
    found, pending = set(), [first]
    while pending:
        spelling = pending.pop()
        if not spelling:
            continue
        is_simple_name = re.fullmatch(r"(?:\w+::)*\w+", spelling)
        if not is_simple_name:
            found.add(spelling)
            continue
        alias_name = spelling.rsplit("::", 1)[-1]
        targets = {
            _services['receiver_dispatch_type_key'](candidate)
            for candidate in aliases.get(alias_name, ())
        }
        targets.discard("")
        # An ambiguous unqualified alias is not enough evidence to identify the
        # receiver type. Do not retain its spelling as a match either: the same
        # ambiguous alias on both sides does not prove a source dispatch.
        if len(targets) == 1:
            found.add(spelling)
            pending.extend(targets - found)
        elif len(targets) > 1 and "::" not in spelling:
            continue
        else:
            found.add(spelling)
    return found

def receiver_method_has_source_dispatch(_services, 
    receiver, callee, text, tables, table_field_types, aliases, structs, definitions,
):
    """Whether a parsed source function's first formal matches this receiver type.

    A name-only match is insufficient: a method from elisacore_std may share its
    name with an unrelated free function in src.  Source methods use their
    receiver as the first formal, so require a statically known matching type.
    """
    receiver_type = _services['receiver_expression_type'](
        receiver, text, tables, table_field_types, aliases, structs, definitions
    )
    receiver_types = _services['receiver_dispatch_type_equivalents'](receiver_type, aliases)
    if not receiver_types:
        return False
    for candidate in definitions.get(callee, ()):
        if candidate.get("external"):
            continue
        formals = _services['split_top_level_arguments'](candidate.get("params", ""))
        if not formals:
            continue
        formal = formals[0].split(":", 1)
        if len(formal) != 2:
            continue
        formal_type = re.split(r"\s*=(?!=)", formal[1], maxsplit=1)[0].strip()
        formal_types = _services['receiver_dispatch_type_equivalents'](formal_type, aliases)
        if receiver_types & formal_types:
            return True
    return False

def receiver_is_static_owner(_services, receiver):
    """Recognize the type-style `Type.method(...)` qualifier used for static calls."""
    return bool(re.fullmatch(r"[A-Z]\w*(?:\.[A-Z]\w*)*", receiver.strip()))

def matching_cast_candidate_indexes(_services, candidates, source_type, target_type, aliases):
    """Match scalar cast hooks by source and target type; unknown signatures fail closed."""
    source_names = _services['type_equivalents'](source_type, aliases)
    target_names = _services['type_equivalents'](target_type, aliases)
    selected = []
    for index, candidate in enumerate(candidates):
        formals = _services['split_top_level_arguments'](candidate.get("params", ""))
        if len(formals) != 1 or not source_names or not target_names:
            selected.append(index)
            continue
        formal = formals[0].split(":", 1)
        if len(formal) != 2:
            selected.append(index)
            continue
        parameter_type = re.split(r"\s*=(?!=)", formal[1], maxsplit=1)[0].strip()
        returned_type = _services['function_return_type'](candidate)
        parameter_names = _services['type_equivalents'](parameter_type, aliases)
        returned_names = _services['type_equivalents'](returned_type, aliases)
        if not parameter_names or not returned_names:
            selected.append(index)
        elif source_names & parameter_names and target_names & returned_names:
            selected.append(index)
    return selected

def receiver_expression_type(_services, 
    receiver, text, tables, table_field_types, aliases, structs, definitions
):
    """Infer the receiver type from local/table paths, literals, or a source call."""
    expression = receiver.strip()
    value_type = _services['table_field_expression_type'](
        expression, tables, table_field_types, aliases, structs
    )
    if not value_type:
        value_type = _services['local_path_expression_type'](expression, text, structs)
    if value_type:
        return value_type

    if re.fullmatch(r"[-+]?(?:\d+|0[xX][0-9A-Fa-f]+)", expression):
        return "i64"
    if re.fullmatch(r"[-+]?(?:\d+\.\d*|\d*\.\d+)(?:[eE][-+]?\d+)?", expression):
        return "f64"
    if re.fullmatch(r"'(?:\\.|[^'\\])'", expression):
        return "char"

    # A member of a declared const enum has the enum's value type.
    enum_member = re.fullmatch(r"((?:\w+::)*\w+)(?:::|\.)\w+", expression)
    if enum_member:
        owner = enum_member.group(1).rsplit("::", 1)[-1]
        if any(fields == [] for fields in structs.get(owner, ())):
            return owner

    # Function return types make casts such as `decode(bytes).i64()` resolvable
    # without pretending that arbitrary method calls are pure.
    call = re.match(r"^([A-Za-z_]\w*)[ \t]*(?:\[[^\]\n]*\])?[ \t]*\(", expression)
    if call:
        opening = expression.find("(", call.start())
        if _services['matching_delimiter'](expression, opening) == len(expression) - 1:
            returns = {
                _services['function_return_type'](candidate)
                for candidate in definitions.get(call.group(1), ())
                if _services['function_return_type'](candidate)
            }
            if len(returns) == 1:
                return next(iter(returns))
    return ""

def receiver_method_is_known_intrinsic(_services, 
    receiver, callee, text, tables, table_field_types, aliases, structs, definitions,
    enum_variants=None,
):
    """Recognize compiler built-ins only when the receiver's type supports them."""
    # `Ast::Expr.Call(...)`, nested `Expr.Unary(..., Expr.Ident(...))` patterns,
    # and `Pattern.Binding(...)` are enum variants, not receiver method dispatch.
    enum_variants = enum_variants or {}
    if re.fullmatch(r"[A-Z]\w*", callee):
        # Nested enum patterns like `Stmt.Assign(Expr.Ident(...))` are reported
        # with the full preceding constructor expression as their receiver. Match
        # the innermost enum namespace, not the outer `Stmt` constructor.
        owners = re.findall(r"(?:[A-Za-z_]\w*::)*([A-Za-z_]\w*)", receiver)
        if owners and callee in enum_variants.get(owners[-1], ()):
            return True

    receiver_type = _services['receiver_expression_type'](
        receiver, text, tables, table_field_types, aliases, structs, definitions
    )
    if not receiver_type:
        return False

    if callee in _services['BUILTIN_NUMERIC_CAST_METHODS'] | {"char", "int"}:
        terminal = receiver_type.rsplit("::", 1)[-1].rstrip("&?").strip()
        return _services['is_builtin_scalar_type'](receiver_type, aliases) or any(
            fields == [] for fields in structs.get(terminal, ())
        )

    container = re.sub(
        r"^(?:(?:mutable|lmut|static|heap|stack)\s+)+", "", receiver_type.strip()
    ).rstrip("&?").strip()
    container_match = re.match(r"(?:\w+::)?(darray|array|dict|map|set|sview)\s*(?:\[|$)", container)
    is_container = bool(container_match) or _services['is_builtin_darray_type'](receiver_type, aliases)
    if is_container and (
        re.fullmatch(_services['MUTATORS'], callee)
        or callee in _services['READ_ONLY_TABLE_METHODS'] | _services['READ_ONLY_TABLE_CALLS']
    ):
        return True
    return False

def specialized_cast_definitions(_services, definitions, candidate):
    """Build only the source call closure needed to summarize one cast overload."""
    subset = {"__cast__": [candidate]}
    pending = [candidate]
    seen_names = {"__cast__"}
    nested_cast = False
    while pending:
        definition = pending.pop()
        text = _services['mask_string_literals'](_services['strip_comments']("".join(definition.get("body", ()))))
        for callee, receiver, _arguments in _services['call_sites'](text):
            if callee == "__cast__" or (receiver and callee in _services['BUILTIN_NUMERIC_CAST_METHODS']):
                nested_cast = True
                continue
            if callee in definitions and callee not in seen_names:
                seen_names.add(callee)
                subset[callee] = definitions[callee]
                pending.extend(definitions[callee])
    return subset, nested_cast
