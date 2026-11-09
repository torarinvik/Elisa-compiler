"""Call analysis for the semantic parallel-pass audit."""
import collections
from functools import lru_cache
import os
import re
import sys


def argument_is_whole_table(_services, argument, tables, aliases):
    """Whether an argument is a bare SymbolTable value or alias (possibly borrowed)."""
    expression = argument.strip()
    while expression.startswith("&"):
        expression = expression[1:].strip()
    while expression.startswith("(") and _services['matching_delimiter'](expression, 0) == len(expression) - 1:
        expression = expression[1:-1].strip()
    return bool(re.fullmatch(r"\w+", expression) and expression in tables | aliases)

def has_top_level_colon(_services, expression):
    """Whether a colon occurs outside nested value delimiters."""
    stack = []
    matching_open = {")": "(", "]": "[", "}": "{"}
    for index, char in enumerate(expression):
        if char in "([{":
            stack.append(char)
        elif char in matching_open:
            if stack and stack[-1] == matching_open[char]:
                stack.pop()
        elif char == ":" and not stack:
            previous = expression[index - 1] if index else ""
            following = expression[index + 1] if index + 1 < len(expression) else ""
            if previous != ":" and following != ":":
                return True
    return False

def return_value_before_guard(_services, expression):
    """Discard only a no-else postfix guard; retain both arms of a value ternary."""
    stack = []
    matching_open = {")": "(", "]": "[", "}": "{"}
    guard_index = None
    for index, char in enumerate(expression):
        if char in "([{":
            stack.append(char)
        elif char in matching_open:
            if stack and stack[-1] == matching_open[char]:
                stack.pop()
        elif not stack:
            if expression.startswith(" if ", index) and guard_index is None:
                guard_index = index
            elif expression.startswith(" else ", index) and guard_index is not None:
                return expression
    return expression[:guard_index].strip() if guard_index is not None else expression

def _top_level_conditional_keyword(_services, expression, keyword, start=0):
    """Find a whitespace-delimited conditional keyword outside values and strings."""
    stack = []
    matching_open = {")": "(", "]": "[", "}": "{"}
    quote = ""
    escaped = False
    for index, char in enumerate(expression):
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
            continue
        if char in {'"', "'"}:
            quote = char
            continue
        if char in "([{":
            stack.append(char)
            continue
        if char in matching_open:
            if stack and stack[-1] == matching_open[char]:
                stack.pop()
            continue
        if stack or index < start or not expression.startswith(keyword, index):
            continue
        end = index + len(keyword)
        if index > 0 and end < len(expression) and expression[index - 1].isspace() and expression[end].isspace():
            return index
    return -1

def returned_value_arms(_services, expression):
    """Return only value arms, excluding predicates from a conditional return."""
    expression = expression.strip()
    lines = expression.splitlines()
    if lines and re.match(r"^if\b", lines[0]) and _services['has_top_level_colon'](lines[0]):
        # `return if predicate:\n    value\nelse:\n    other` is a block
        # expression. The predicate controls selection but is not returned. Since
        # returned_expressions intentionally flattens indentation, strip only the
        # branch headers and retain every branch value for the alias check.
        branch_headers = re.compile(r"^(?:if|elif|else)\b.*:\s*$")
        if any(branch_headers.match(line) for line in lines[1:]):
            values = [line for line in lines[1:] if not branch_headers.match(line)]
            return ["\n".join(values).strip()] if values else []

    conditional = _services['_top_level_conditional_keyword'](expression, "if", start=1)
    if conditional >= 0:
        else_index = _services['_top_level_conditional_keyword'](expression, "else", conditional + 2)
        if else_index >= 0:
            # Ternary form (`value if predicate else other`): both value operands
            # can escape; references used only by the predicate cannot.
            return _services['returned_value_arms'](expression[:conditional]) + _services['returned_value_arms'](
                expression[else_index + len("else"):]
            )
        # The no-else spelling is a postfix guard, so only its prefix is a value.
        return _services['returned_value_arms'](expression[:conditional])
    return [expression] if expression else []

def returned_expressions(_services, text):
    """Yield inline returns and indented return-value blocks from one function body."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        match = re.search(r"\breturn\b", line)
        if match is None:
            continue
        inline = line[match.end():].strip()
        prefix = line[:match.start()].strip()
        if prefix and re.match(r"if\b", inline):
            yield prefix
            continue
        base_indent = len(line) - len(line.lstrip())
        if re.match(r"if\b", inline) and not _services['has_top_level_colon'](inline):
            # Postfix guard form (`false return if condition`) has no returned
            # expression; the return value precedes the keyword on this line.
            continue
        parts = [inline] if inline else []
        value_block = not inline
        open_delimiters = []

        def update_delimiters(part):
            for char in part:
                if char in "([{":
                    open_delimiters.append(char)
                elif char in ")]}":
                    if open_delimiters:
                        open_delimiters.pop()

        if inline:
            update_delimiters(inline)
            value_block = bool(open_delimiters) or bool(
                re.match(r"(?:if|match|for)\b", inline) and inline.rstrip().endswith(":")
            )
        for following in lines[index + 1:]:
            stripped = following.strip()
            indent = len(following) - len(following.lstrip()) if stripped else base_indent + 1
            continuation = bool(re.match(r"(?:else|elif|catch)\b", stripped))
            if stripped and indent <= base_indent and not continuation and not open_delimiters:
                break
            if stripped and indent <= base_indent and not continuation and not value_block:
                break
            if stripped:
                parts.append(stripped)
                update_delimiters(stripped)
            elif value_block:
                parts.append("")
            if not open_delimiters and value_block and not continuation and indent <= base_indent:
                # An indented return block or the final branch of a block expression
                # ends when parsing returns to the statement's indentation.
                break
        expression = "\n".join(parts).strip()
        if expression:
            yield expression

def argument_is_table_backed(_services, argument, tables, table_aliases, field_aliases):
    return (
        _services['argument_is_whole_table'](argument, tables, table_aliases)
        or _services['argument_is_table_field_or_alias'](argument, tables, field_aliases)
    )

def is_diagnostics_receiver(_services, receiver, tables, diagnostic_aliases):
    """Recognize only a direct diagnostics field or its already-tracked local alias."""
    expression = receiver.strip()
    while expression.startswith("(") and _services['matching_delimiter'](expression, 0) == len(expression) - 1:
        expression = expression[1:-1].strip()
    if expression in diagnostic_aliases:
        return True
    match = re.fullmatch(r"(\w+)\s*\.\s*diagnostics", expression)
    return bool(match and match.group(1) in tables)

def mutable_actual_indexes(_services, arguments, candidates):
    """Return actual positions that could reach mutable formals at a callsite."""
    if not candidates:
        return set(range(len(arguments)))
    possibly_mutable = set()
    for candidate in candidates:
        if candidate.get("external"):
            return set(range(len(arguments)))
        formals = _services['split_top_level_arguments'](candidate["params"])
        mutable = [bool(re.search(r"\b(?:mutable|lmut)\b", formal)) for formal in formals]
        if not any(mutable):
            continue
        # Named/defaulted calls and arity mismatches need semantic overload resolution;
        # fail closed when a mutable formal could receive a shared value.
        named = any(re.match(r"^\s*\w+\s*(?:=(?!=)|:(?!:))", argument) for argument in arguments)
        if named or len(arguments) != len(formals):
            return set(range(len(arguments)))
        possibly_mutable.update(index for index, is_mutable in enumerate(mutable) if is_mutable)
    return possibly_mutable

def _matched_source_names(_services, text, names):
    """Equivalent to individual word-boundary searches for each name."""
    words = set(re.findall(r"\w+", text))
    return {name for name in names if name in words or (
        not re.fullmatch(r"\w+", name) and re.search(r"\b" + re.escape(name) + r"\b", text)
    )}

def _global_callable_names(_services, text, names):
    """Match invoked global paths while scanning ordinary identifiers once."""
    result = set()
    for match in re.finditer(r"\b\w+\b", text):
        name = match.group()
        if name in names and _services['global_path_is_invoked'](text, match.end()):
            result.add(name)
    # Keep the original behavior for non-identifier names supplied by clients.
    for name in names:
        if re.fullmatch(r"\w+", name):
            continue
        for match in re.finditer(r"\b" + re.escape(name) + r"\b", text):
            if _services['global_path_is_invoked'](text, match.end()):
                result.add(name)
    return result

def argument_global_names(_services, argument, globals_, aliases):
    """Return mutable globals named directly or through a simple local alias."""
    names = _services['_matched_source_names'](argument, globals_)
    if _services['_matched_source_names'](argument, aliases):
        # Alias provenance is intentionally collapsed: any write through an alias
        # already disqualifies the defining pass, and mutable calls must do the same.
        names.add("aliased-global")
    return names

def call_may_mutate_table_field(_services, 
    arguments, candidates, tables, aliases, table_field_types=None, type_aliases=None,
    struct_field_types=None, allow_copied_values=False, builtin_value_push=False, text="",
):
    """Conservatively match tainted actuals to mutable formals across overloads."""
    table_field_types = table_field_types or {}
    type_aliases = type_aliases or {}
    struct_field_types = struct_field_types or {}
    possibly_mutable = _services['mutable_actual_indexes'](arguments, candidates)
    tainted = []
    for index, argument in enumerate(arguments):
        is_tainted = _services['argument_is_table_field_or_alias'](argument, tables, aliases)
        if is_tainted:
            table_names = "(?:" + "|".join(sorted(map(re.escape, tables))) + ")" if tables else r"(?!)"
            direct_table_path = bool(re.search(
                r"\b" + table_names + r"\s*(?:\.\s*\w+|\[[^\]\n]*\])", argument
            ))
            if not direct_table_path:
                local_expression = argument.strip()
                while True:
                    if local_expression.startswith("&"):
                        local_expression = local_expression[1:].strip()
                    elif local_expression.startswith("(") and _services['matching_delimiter'](local_expression, 0) == len(local_expression) - 1:
                        local_expression = local_expression[1:-1].strip()
                    else:
                        break
                value_type = _services['local_path_expression_type'](
                    local_expression, text, struct_field_types
                ) if text else ""
                if _services['is_detached_copy_value'](value_type, type_aliases, struct_field_types):
                    # The local owns this Copy value. Immutable views inside it may
                    # still alias table text, but a mutable formal can only modify
                    # the local descriptor; mutable owner containers remain tainted.
                    is_tainted = False
        if is_tainted and allow_copied_values:
            value_type = _services['table_field_expression_type'](
                argument, tables, table_field_types, type_aliases, struct_field_types
            )
            formal_is_by_value = bool(candidates) and index not in possibly_mutable
            if _services['is_detached_copy_value'](value_type, type_aliases, struct_field_types) and (
                formal_is_by_value or builtin_value_push
            ):
                is_tainted = False
        tainted.append(is_tainted)
    return any(is_tainted and index in possibly_mutable for index, is_tainted in enumerate(tainted))
