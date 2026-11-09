"""Source scan for the semantic parallel-pass audit."""
import collections
from functools import lru_cache
import os
import re
import sys


def elisa_files(_services):
    for base, _dirs, files in os.walk(_services['SRC']):
        for name in sorted(files):
            if name.endswith(".elisa"):
                yield os.path.join(base, name)

def type_expression_is_mutable_ref(_services, type_expression, aliases, alias_cache=None):
    """Resolve source type aliases enough to detect a mutable reference spelling."""
    if re.search(r"\b(?:mutable|lmut)\b", type_expression):
        return True
    if alias_cache is None:
        alias_cache = {}

    def alias_is_mutable_ref(alias, visiting):
        if alias in alias_cache:
            return alias_cache[alias]
        if alias in visiting:
            # Alias cycles fail closed. The audit may serialize extra passes, but it
            # must not miss a mutable reference global.
            return True
        visiting.add(alias)
        result = False
        for aliased_type in aliases.get(alias, ()):
            if re.search(r"\b(?:mutable|lmut)\b", aliased_type):
                result = True
                break
            if any(
                alias_is_mutable_ref(qualified_name.rsplit("::", 1)[-1], visiting)
                for qualified_name in re.findall(r"(?:\w+::)*\w+", aliased_type)
            ):
                result = True
                break
        visiting.remove(alias)
        alias_cache[alias] = result
        return result

    try:
        return any(
            alias_is_mutable_ref(qualified_name.rsplit("::", 1)[-1], set())
            for qualified_name in re.findall(r"(?:\w+::)*\w+", type_expression)
        )
    except RecursionError:
        # Generated or malformed alias chains must not abort the audit. Unknown depth
        # is treated as a possible mutable reference.
        return True

def parse_functions(_services):
    """name -> list of (file, params text, body lines)."""
    defs = collections.defaultdict(list)
    globals_ = set()
    global_types = collections.defaultdict(list)
    type_aliases = collections.defaultdict(list)
    table_field_types = {}
    struct_field_types = collections.defaultdict(list)
    enum_variants = collections.defaultdict(set)
    for path in _services['elisa_files']():
        current = None
        indent = -1
        current_struct = None
        current_enum = None
        for line in open(path, encoding="utf-8"):
            enum = _services['ENUM_RE'].match(line)
            if enum:
                current_enum = {"indent": len(enum.group(1)), "name": enum.group(2)}
            elif current_enum is not None:
                stripped = line.strip()
                line_indent = len(line) - len(line.lstrip())
                if stripped and not stripped.startswith("#") and line_indent <= current_enum["indent"]:
                    current_enum = None
                elif stripped and not stripped.startswith("#") and line_indent == current_enum["indent"] + 4:
                    variant = _services['ENUM_VARIANT_RE'].match(line)
                    if variant:
                        enum_variants[current_enum["name"]].add(variant.group(1))
            const_enum = _services['CONST_ENUM_RE'].match(line)
            if const_enum:
                # Const enums have a scalar representation and no payload storage.
                struct_field_types[const_enum.group(1)].append([])
            struct = _services['STRUCT_RE'].match(line)
            if struct:
                if current_struct is not None:
                    struct_field_types[current_struct["name"]].append(current_struct["fields"])
                current_struct = {
                    "indent": len(struct.group(1)),
                    "name": struct.group(2),
                    "fields": {},
                }
            elif current_struct is not None:
                stripped = line.strip()
                line_indent = len(line) - len(line.lstrip())
                if stripped and not stripped.startswith("#") and line_indent <= current_struct["indent"]:
                    struct_field_types[current_struct["name"]].append(current_struct["fields"])
                    current_struct = None
                elif stripped and not stripped.startswith("#") and line_indent == current_struct["indent"] + 4:
                    struct_field = _services['STRUCT_FIELD_RE'].match(line)
                    if struct_field:
                        field_name, field_type = struct_field.group(1), struct_field.group(2).strip()
                        current_struct["fields"][field_name] = field_type
                        if current_struct["name"] == "SymbolTable":
                            table_field_types[field_name] = field_type
            g = _services['GLOBAL_RE'].match(line)
            if g:
                globals_.add(g.group(1))
                if g.group(2):
                    global_types[g.group(1)].append(g.group(2).strip())
            type_alias = _services['TYPE_ALIAS_RE'].match(line)
            if type_alias:
                type_aliases[type_alias.group(1)].append(type_alias.group(2).strip())
            external = _services['EXTERN_FUNC_RE'].match(line)
            if external:
                defs[external.group(1)].append(
                    {"file": path, "params": "", "body": [], "external": True}
                )
            m = _services['DEF_RE'].match(line)
            if m:
                current = {"file": path, "params": m.group(3), "body": [line]}
                indent = len(m.group(1))
                defs[m.group(2)].append(current)
                continue
            if current is not None:
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and len(line) - len(line.lstrip()) <= indent:
                    current = None
                    continue
                current["body"].append(line)
        if current_struct is not None:
            struct_field_types[current_struct["name"]].append(current_struct["fields"])
    # Alias names are resolved by their terminal identifier. When modules reuse a name,
    # treating all candidates as possible spellings is conservative and avoids binding
    # a qualified global to whichever module happened to be scanned last.
    alias_cache = {}
    mutable_ref_globals = {
        name
        for name, type_expressions in global_types.items()
        if any(
            _services['type_expression_is_mutable_ref'](expression, type_aliases, alias_cache)
            for expression in type_expressions
        )
    }
    return (
        defs, globals_, mutable_ref_globals, type_aliases, table_field_types,
        struct_field_types, enum_variants,
    )

def strip_comments(_services, text):
    """Drop `#` comments, leaving string literals (which may contain `#`) intact."""
    out = []
    for line in text.splitlines():
        quote = None
        cut = len(line)
        i = 0
        while i < len(line):
            c = line[i]
            if quote:
                if c == "\\":
                    i += 1
                elif c == quote:
                    quote = None
            elif c in "\"'":
                quote = c
            elif c == "#":
                cut = i
                break
            i += 1
        out.append(line[:cut])
    return "\n".join(out)

def mask_string_literals(_services, text):
    """Mask literal text while retaining executable f-string interpolation code."""
    chars = list(text)

    def mask_plain_string(start):
        quote = chars[start]
        # Retain one inert token so a real string argument does not collapse into a
        # zero-argument call after masking (for example `getenv("FLAG")`).
        chars[start] = "x"
        index = start + 1
        while index < len(chars):
            char = chars[index]
            if char == "\\":
                chars[index] = " "
                if index + 1 < len(chars) and chars[index + 1] != "\n":
                    chars[index + 1] = " "
                    index += 1
            elif char == quote:
                chars[index] = " "
                return index + 1
            elif char != "\n":
                chars[index] = " "
            index += 1
        return index

    def mask_fstring(start):
        # Elisa's f-string token uses the `f"..."` spelling. Preserve each
        # interpolation as source code and mask the literal chunks around it.
        quote_index = start + 1
        chars[quote_index] = "x"
        index = quote_index + 1
        while index < len(chars):
            char = chars[index]
            if char == "\\":
                chars[index] = " "
                if index + 1 < len(chars) and chars[index + 1] != "\n":
                    chars[index + 1] = " "
                    index += 1
            elif char == '"':
                chars[index] = " "
                return index + 1
            elif char == "{" and index + 1 < len(chars) and chars[index + 1] == "{":
                chars[index] = chars[index + 1] = " "
                index += 1
            elif char == "}" and index + 1 < len(chars) and chars[index + 1] == "}":
                chars[index] = chars[index + 1] = " "
                index += 1
            elif char == "{":
                index = mask_code(index + 1, stop_at_interp=True)
                if index < len(chars) and chars[index] == "}":
                    index += 1
                # `index` now points just after the closing brace. Continue directly so
                # the first literal character after the interpolation (which may be the
                # opening brace of an adjacent interpolation) is processed on the next
                # iteration instead of being skipped by the loop's increment below.
                continue
            elif char != "\n":
                chars[index] = " "
            index += 1
        return index

    def mask_code(start, stop_at_interp=False):
        index = start
        brace_depth = 0
        while index < len(chars):
            char = chars[index]
            if (
                char == "f"
                and index + 1 < len(chars)
                and chars[index + 1] == '"'
                and (index == 0 or not (chars[index - 1].isalnum() or chars[index - 1] == "_"))
            ):
                index = mask_fstring(index)
                continue
            if char in "\"'":
                index = mask_plain_string(index)
                continue
            if stop_at_interp:
                if char == "{":
                    brace_depth += 1
                elif char == "}":
                    if brace_depth == 0:
                        return index
                    brace_depth -= 1
            index += 1
        return index

    mask_code(0)
    return "".join(chars)

def audit_normalize_field_dots(_services, text):
    """Normalize horizontal dot spacing in code while preserving literal bytes.

    The mask retains f-string interpolation. Validate each candidate against
    the original text: masked literal bytes look like spaces and must never be
    removed from the original string.
    """
    masked = _services['mask_string_literals'](text)
    pieces, masked_pieces, start = [], [], 0
    for match in _services['_FIELD_DOT_SPACING_RE'].finditer(masked):
        piece = text[match.start():match.end()]
        if not re.fullmatch(r"[ \t]*\.[ \t]*", piece):
            continue
        pieces.extend((text[start:match.start()], "."))
        masked_pieces.extend((masked[start:match.start()], "."))
        start = match.end()
    if not pieces:
        return text, masked
    pieces.append(text[start:])
    masked_pieces.append(masked[start:])
    return "".join(pieces), "".join(masked_pieces)

def par_run_calls(_services, lines, offset=0):
    """Parse every par_pass_run call in a line sequence, rejecting partial matches."""
    calls, errors = [], []
    for index, line in enumerate(lines):
        code = _services['strip_comments'](line)
        if not _services['PAR_RUN_ANY_RE'].search(code):
            continue
        match = _services['PAR_RUN_RE'].fullmatch(code)
        if match is None:
            errors.append(offset + index + 1)
            continue
        calls.append({"line": offset + index, "match": match,
                      "start": int(match.group(4)), "count": int(match.group(5))})
    return calls, errors

def normalized_par_run_line(_services, line, match):
    """Emit the lmut call with an explicit table update while preserving effects/indentation."""
    return (match.group(1) + "table <- par_pass_run(file, flags, table, shared_pool, " + "loop_view" + ", "
            + match.group(4) + ", " + match.group(5) + ")" + (match.group(6) or ""))

def split_parallel_range(_services, first, count, safe_ids):
    """Keep unsafe passes serial while batching consecutive audited passes in order."""
    end = first + count
    while first < end:
        stop = first + 1
        if first in safe_ids:
            while stop < end and stop in safe_ids:
                stop += 1
        yield first, stop - first
        first = stop
