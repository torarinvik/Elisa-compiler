#!/usr/bin/env python3
"""Audit and generate the concurrent runs of append-only semantic passes (round 8).

A semantic pass may run on a worker thread over a frozen SymbolTable only if it is
APPEND-ONLY: through every function it can reach, the only SymbolTable field it writes is
`diagnostics`, it never reads earlier diagnostics, and it writes no mutable global. This script
audits that from the source, conservatively:

  * the call graph is by name and a name with several definitions (overloads, methods of the
    same name in different modules) reaches ALL of them;
  * a write is any `<table>.<field>... <-`, any mutating container call on a table field,
    any `in <table>.<field>:` region block and any `&<table>.<field>` borrow (read-only borrows
    included), where <table> is any parameter or local declared with a SymbolTable type;
  * a diagnostics read is any use of `<table>.diagnostics` other than `<- ....push(` on it;
  * a global write is any assignment to, borrow of, or `in <global>:` region block over a
    `global mutable` name;
  * an AST write is any AST node construction (a variant of Expr/Stmt/Decl/Pattern/Node used
    as a value): it grows the shared AST store.
  * local aliases of table fields are tracked; writes through them and calls that pass a table
    field or alias as an explicit argument or method receiver to a `mutable` / `lmut` formal are
    conservatively rejected. Whole-table aliases and borrows are tracked; declared `extern`
    calls and calls outside the source call graph that receive table-backed values are rejected
    because their effects cannot be inspected.
    Local aliases of diagnostics are treated as reads because they may inspect earlier-pass
    results.

Passes run in `check_full_into_pipeline` (semantic_api.elisa) as `table <- pass(ARGS) [if COND]`. A
maximal run of consecutive append-only passes whose ARGS/COND use only `file`, `loop_view`,
`table` and the function's scalar flags becomes one `par_pass_run` call; the passes go into
semantic_parallel_passes.elisa by id, in pipeline order (the splice order).

  semantic_parallel_gen.py --check      verify every pass in semantic_parallel_passes.elisa
                                        (exit 1 naming each one that is not append-only)
  semantic_parallel_gen.py --write      rewrite semantic_api.elisa runs + the passes file
                                        (input: sequential or already generated pipeline)
  semantic_parallel_gen.py --report     list every pipeline pass and its classification
"""
import collections
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
API = os.path.join(SRC, "semantic", "semantic_api.elisa")
PASSES = os.path.join(SRC, "semantic", "semantic_parallel_passes.elisa")
PIPELINE = "check_full_into_pipeline"
PIPELINE_CONTEXT = {"file", "table", "shared_pool", "snapshot", "incremental_skip_count", "enforce_mutable_global_grants"}
MIN_RUN = 2
MUTATORS = (
    r"push|push_back|extend|pop|clear|insert|remove|remove_at|put|put_checked|put_or_panic|add|set|swap|sort"
    r"|append|append_many|truncate|reserve|resize|as_cstr|get_or_insert|get_or_insert_with|discard"
    r"|reverse|fill|push_front|pop_front|retain|drain"
)
# Source audit of table-backed receiver calls in src/semantic found these built-in
# read-only conversions/lookups. Any other unresolved receiver method is treated as
# an effectful call below; source-defined methods still use their formal modes.
READ_ONLY_TABLE_METHODS = {"get", "as_sview"}
READ_ONLY_TABLE_CALLS = {"sview_len", "sview_at"}
BUILTIN_NUMERIC_CAST_METHODS = {
    "i8", "i16", "i32", "i64", "u8", "u16", "u32", "u64",
    "isize", "usize", "int", "uintptr", "char", "f32", "f64",
}
BORROWED_NAME_PREFIX = r"(?:(?:\(\s*)|(?:&\s*))*"
NON_CALL_KEYWORDS = {
    "if", "elif", "else", "while", "for", "match", "can", "catch", "and", "or", "not",
    "return", "mutable", "where", "assert", "ensure", "implies",
}
# Source-language intrinsics without ordinary source definitions. Keep this list
# narrow: an unresolved free call is an unknown effect unless explicitly known pure.
PURE_FREE_CALLS = {"sview", "sview_len", "sview_at", "getenv"}
DEF_RE = re.compile(r"^(\s*)def (\w+)(?:\[[^\]]*\])?\((.*?)\)\s*(?:->|:)")
EXTERN_FUNC_RE = re.compile(r"^\s*extern\s+(\w+)\s*\(")
TABLE_DECL_RE = re.compile(r"\b(\w+)\s*:\s*(?:lmut\s+|mutable\s+|heap\s+)*SymbolTable\b")
GLOBAL_RE = re.compile(r"^\s*global\s+mutable\s+(\w+)(?:\s*:\s*([^#=\n]*))?")
TYPE_ALIAS_RE = re.compile(r"^\s*type\s+(\w+)(?:\[[^\]\n]*\])?\s*=\s*([^#\n]+)")
STRUCT_RE = re.compile(r"^(\s*)struct\s+(\w+)(?:\[[^\]\n]*\])?\s*:\s*$")
STRUCT_FIELD_RE = re.compile(r"^\s+(\w+)\s*:\s*([^#=\n]+)")
CONST_ENUM_RE = re.compile(r"^\s*const\s+enum\s+(\w+)\b")
ENUM_RE = re.compile(r"^(\s*)(?:const\s+)?enum\s+(\w+)\b.*:\s*$")
ENUM_VARIANT_RE = re.compile(r"^\s+([A-Z]\w*)\b")
CALL_RE = re.compile(r"\b([A-Za-z_]\w*)[ \t]*(?:\[[^\]\n]*\])?[ \t]*\(")
PAR_RUN_RE = re.compile(
    r"^([ \t]*table <- par_pass_run\(file, &loop_view, flags, table, )"
    r"(shared_pool, )?(\d+), (\d+)\)([ \t]+can[ \t]+[^\n]+)?[ \t]*$"
)
PAR_RUN_ANY_RE = re.compile(r"\bpar_pass_run\s*\(")
PAR_PASS_ARM_RE = re.compile(r"^([ \t]*)(if|elif) pass_id == (\d+):[ \t]*$")
PAR_PASS_ARM_ANY_RE = re.compile(r"\bpass_id\s*==")


def elisa_files():
    for base, _dirs, files in os.walk(SRC):
        for name in sorted(files):
            if name.endswith(".elisa"):
                yield os.path.join(base, name)


def type_expression_is_mutable_ref(type_expression, aliases, alias_cache=None):
    """Resolve source type aliases enough to detect a mutable reference spelling."""
    if re.search(r"\bmutable\b[^&]*&", type_expression):
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
            if re.search(r"\bmutable\b[^&]*&", aliased_type):
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


def parse_functions():
    """name -> list of (file, params text, body lines)."""
    defs = collections.defaultdict(list)
    globals_ = set()
    global_types = collections.defaultdict(list)
    type_aliases = collections.defaultdict(list)
    table_field_types = {}
    struct_field_types = collections.defaultdict(list)
    enum_variants = collections.defaultdict(set)
    for path in elisa_files():
        current = None
        indent = -1
        current_struct = None
        current_enum = None
        for line in open(path, encoding="utf-8"):
            enum = ENUM_RE.match(line)
            if enum:
                current_enum = {"indent": len(enum.group(1)), "name": enum.group(2)}
            elif current_enum is not None:
                stripped = line.strip()
                line_indent = len(line) - len(line.lstrip())
                if stripped and not stripped.startswith("#") and line_indent <= current_enum["indent"]:
                    current_enum = None
                elif stripped and not stripped.startswith("#") and line_indent == current_enum["indent"] + 4:
                    variant = ENUM_VARIANT_RE.match(line)
                    if variant:
                        enum_variants[current_enum["name"]].add(variant.group(1))
            const_enum = CONST_ENUM_RE.match(line)
            if const_enum:
                # Const enums have a scalar representation and no payload storage.
                struct_field_types[const_enum.group(1)].append([])
            struct = STRUCT_RE.match(line)
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
                    struct_field = STRUCT_FIELD_RE.match(line)
                    if struct_field:
                        field_name, field_type = struct_field.group(1), struct_field.group(2).strip()
                        current_struct["fields"][field_name] = field_type
                        if current_struct["name"] == "SymbolTable":
                            table_field_types[field_name] = field_type
            g = GLOBAL_RE.match(line)
            if g:
                globals_.add(g.group(1))
                if g.group(2):
                    global_types[g.group(1)].append(g.group(2).strip())
            type_alias = TYPE_ALIAS_RE.match(line)
            if type_alias:
                type_aliases[type_alias.group(1)].append(type_alias.group(2).strip())
            external = EXTERN_FUNC_RE.match(line)
            if external:
                defs[external.group(1)].append(
                    {"file": path, "params": "", "body": [], "external": True}
                )
            m = DEF_RE.match(line)
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
            type_expression_is_mutable_ref(expression, type_aliases, alias_cache)
            for expression in type_expressions
        )
    }
    return (
        defs, globals_, mutable_ref_globals, type_aliases, table_field_types,
        struct_field_types, enum_variants,
    )


def strip_comments(text):
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


def mask_string_literals(text):
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


def par_run_calls(lines, offset=0):
    """Parse every par_pass_run call in a line sequence, rejecting partial matches."""
    calls, errors = [], []
    for index, line in enumerate(lines):
        code = strip_comments(line)
        if not PAR_RUN_ANY_RE.search(code):
            continue
        match = PAR_RUN_RE.fullmatch(code)
        if match is None:
            errors.append(offset + index + 1)
            continue
        calls.append({"line": offset + index, "match": match,
                      "start": int(match.group(3)), "count": int(match.group(4))})
    return calls, errors


def normalized_par_run_line(line, match):
    """Add the pool parameter to a valid generated call, preserving effects and indentation."""
    return (match.group(1) + "shared_pool, " + match.group(3) + ", " + match.group(4) + ")"
            + (match.group(5) or ""))


def parse_parallel_dispatch(source):
    """Return dispatcher arms as (id, pass name, args, condition), plus structural errors."""
    lines = source.splitlines()
    definition = next((i for i, line in enumerate(lines)
                       if re.match(r"^[ \t]*def par_pass_call\(", line)), None)
    if definition is None:
        return [], ["semantic_parallel_passes.elisa: missing par_pass_call dispatcher"]

    def_indent = len(lines[definition]) - len(lines[definition].lstrip())
    end = definition + 1
    while end < len(lines):
        line = lines[end]
        if line.strip() and not line.lstrip().startswith("#") and len(line) - len(line.lstrip()) <= def_indent:
            break
        end += 1

    arms, errors = [], []
    for index in range(definition + 1, end):
        code = strip_comments(lines[index]).strip()
        if not PAR_PASS_ARM_ANY_RE.search(code):
            continue
        match = PAR_PASS_ARM_RE.fullmatch(lines[index])
        if match is None:
            errors.append("semantic_parallel_passes.elisa:%d: malformed pass_id arm" % (index + 1))
            continue
        arms.append((index, len(match.group(1)), match.group(2), int(match.group(3))))

    records = []
    for arm_index, (line_index, arm_indent, arm_kind, pass_id) in enumerate(arms):
        expected_kind = "if" if arm_index == 0 else "elif"
        if arm_kind != expected_kind:
            errors.append("semantic_parallel_passes.elisa:%d: expected %s for pass_id %d" %
                          (line_index + 1, expected_kind, pass_id))
        stop = arms[arm_index + 1][0] if arm_index + 1 < len(arms) else end
        body = []
        for index in range(line_index + 1, stop):
            code = strip_comments(lines[index]).strip()
            if code:
                body.append((index, len(lines[index]) - len(lines[index].lstrip()), code))
        if len(body) != 1 or body[0][1] <= arm_indent:
            errors.append("semantic_parallel_passes.elisa:%d: pass_id %d must have exactly one body statement" %
                          (line_index + 1, pass_id))
            continue
        body_index, _indent, statement = body[0]
        parsed = parse_table_call_statement(statement)
        if parsed is None:
            errors.append("semantic_parallel_passes.elisa:%d: unrecognized dispatcher call for pass_id %d" %
                          (body_index + 1, pass_id))
            continue
        records.append({"id": pass_id, "name": parsed["name"], "args": parsed["args"],
                        "condition": parsed["cond"]})

    table_calls = [line for line in lines[definition:end]
                   if re.match(r"^[ \t]*table <- \w+\(", strip_comments(line))]
    if len(table_calls) != len(records):
        errors.append("semantic_parallel_passes.elisa: dispatcher table calls do not map one-to-one to pass_id arms")

    return records, errors


AST_VARIANT_RE = re.compile(r"(?<![\w.:])(?:Ast::)?(Expr|Stmt|Decl|Pattern|Node)\.([A-Z]\w*)\b")


def match_arm_body(line):
    """For a `match` arm line (one or more `|`-joined variant patterns, binders and nested
    patterns included, then `:`), the text after the `:` (a one-line arm's value); None
    for any other line."""
    rest = line.strip()
    while True:
        m = re.match(r"(?:Ast::)?(?:Expr|Stmt|Decl|Pattern|Node)\.[A-Z]\w*", rest)
        if not m:
            return None
        rest = rest[m.end():]
        if rest.startswith("("):
            depth = 0
            for j, c in enumerate(rest):
                depth += c == "("
                depth -= c == ")"
                if depth == 0:
                    break
            rest = rest[j + 1:]
        rest = rest.lstrip()
        if rest.startswith("|"):
            rest = rest[1:].lstrip()
            continue
        return rest[1:] if rest.startswith(":") else None


def ast_constructions(text):
    """AST node constructions in a body: a variant of the AST hierarchy used as a VALUE, not as
    a `match` arm pattern or an `is` test. Building a node grows the AST store, which the worker
    threads share; stage0 rejects the same thing in the seed (a submitted worker may only read)."""
    found = []
    for line in text.split("\n"):
        arm_value = match_arm_body(line)
        if arm_value is not None:
            line = arm_value
        for m in AST_VARIANT_RE.finditer(line):
            before = line[:m.start()]
            if re.search(r"\bis\s+(?:not\s+)?$", before):
                continue
            found.append("%s.%s" % (m.group(1), m.group(2)))
    return found


def split_top_level_arguments(text):
    """Split a call's arguments without splitting nested expressions or string literals."""
    if not text.strip():
        return []
    out = []
    start = 0
    parens = brackets = braces = 0
    quote = None
    escaped = False
    for index, char in enumerate(text):
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in "\"'":
            quote = char
        elif char == "(":
            parens += 1
        elif char == ")":
            parens -= 1
        elif char == "[":
            brackets += 1
        elif char == "]":
            brackets -= 1
        elif char == "{":
            braces += 1
        elif char == "}":
            braces -= 1
        elif char == "," and parens == 0 and brackets == 0 and braces == 0:
            out.append(text[start:index].strip())
            start = index + 1
    out.append(text[start:].strip())
    return out


def receiver_before_call(text, call_start):
    """Return the receiver expression immediately before a method-call name."""
    dot = call_start - 1
    while dot >= 0 and text[dot].isspace():
        dot -= 1
    if dot < 0 or text[dot] != ".":
        return None
    end = dot
    cursor = dot - 1
    expected_open = []
    closing_to_open = {")": "(", "]": "[", "}": "{"}
    opening = set(closing_to_open.values())
    boundaries = set(",;=<>!?+-*/%")
    while cursor >= 0:
        char = text[cursor]
        if char in "\"'":
            quote = char
            cursor -= 1
            while cursor >= 0:
                if text[cursor] == quote:
                    backslashes = 0
                    escape_cursor = cursor - 1
                    while escape_cursor >= 0 and text[escape_cursor] == "\\":
                        backslashes += 1
                        escape_cursor -= 1
                    if backslashes % 2 == 0:
                        break
                cursor -= 1
            if cursor < 0:
                return None
        elif char in closing_to_open:
            expected_open.append(closing_to_open[char])
        elif char in opening:
            if expected_open:
                if char != expected_open[-1]:
                    return None
                expected_open.pop()
            elif char == "[":
                # The call is inside an unfinished index expression, such as
                # `table.items[index.usize()]`; its receiver is `index`, not the
                # table path to the left of the opening bracket.
                break
            # At depth zero this is the start of the receiver's grouped expression.
        elif not expected_open:
            if char in boundaries:
                break
            if char.isspace():
                # Permit whitespace around field access, but stop before the prior
                # statement/expression (for example `return (table.field).push`).
                left = cursor - 1
                while left >= 0 and text[left].isspace() and text[left] != "\n":
                    left -= 1
                right = cursor + 1
                while right < end and text[right].isspace():
                    right += 1
                if (left < 0 or text[left] != ".") and (right >= end or text[right] != "."):
                    break
        cursor -= 1
    if expected_open:
        return None
    receiver = text[cursor + 1:end].strip()
    return receiver or None


def matching_delimiter(text, start):
    """Find the close for a bracket/parenthesis/brace group, or return None."""
    closing_to_open = {")": "(", "]": "[", "}": "{"}
    stack = []
    quote = None
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in "\"'":
            quote = char
        elif char in "([{":
            stack.append(char)
        elif char in closing_to_open:
            if not stack or stack.pop() != closing_to_open[char]:
                return None
            if not stack:
                return index
    return None


def global_path_is_invoked(text, end):
    """Whether a global-rooted callable/member/index expression is invoked here."""
    cursor = end
    while cursor < len(text) and text[cursor].isspace():
        cursor += 1
    while cursor < len(text):
        if text[cursor] == ".":
            cursor += 1
            while cursor < len(text) and text[cursor].isspace():
                cursor += 1
            member = re.match(r"\w+", text[cursor:])
            if member is None:
                return False
            cursor += member.end()
        elif text[cursor] == "[":
            close = matching_delimiter(text, cursor)
            if close is None:
                return False
            cursor = close + 1
        elif text[cursor] == ")":
            while cursor < len(text) and text[cursor] == ")":
                cursor += 1
        elif text[cursor] == "(":
            return True
        else:
            return False
        while cursor < len(text) and text[cursor].isspace():
            cursor += 1
    return False


def global_path_write_tail(text, end):
    """Return the first character after a global-rooted place or mutator receiver."""
    cursor = end
    while cursor < len(text) and text[cursor].isspace():
        cursor += 1
    while cursor < len(text):
        if text[cursor] == ".":
            member_start = cursor + 1
            while member_start < len(text) and text[member_start].isspace():
                member_start += 1
            member = re.match(r"\w+", text[member_start:])
            if member is None:
                return cursor
            member_end = member_start + member.end()
            after_member = member_end
            while after_member < len(text) and text[after_member].isspace():
                after_member += 1
            if re.fullmatch(MUTATORS, member.group(0)) and after_member < len(text) and text[after_member] == "(":
                return cursor
            cursor = member_end
        elif text[cursor] == "[":
            close = matching_delimiter(text, cursor)
            if close is None:
                return cursor
            cursor = close + 1
        elif text[cursor] == ")":
            # A global can be the entire parenthesized receiver/place: `(global)[i]`
            # and `(global) <- value` are both valid Elisa expressions.
            cursor += 1
        else:
            return cursor
        while cursor < len(text) and text[cursor].isspace():
            cursor += 1
    return cursor


def call_sites(text):
    """Yield (callee, receiver, argument strings) for calls in stripped source text."""
    for match in CALL_RE.finditer(text):
        line_start = text.rfind("\n", 0, match.start()) + 1
        if re.search(r"\bdef\s+$", text[line_start:match.start()]):
            continue
        open_paren = match.end() - 1
        depth = 1
        quote = None
        escaped = False
        for index in range(open_paren + 1, len(text)):
            char = text[index]
            if quote is not None:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    quote = None
                continue
            if char in "\"'":
                quote = char
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    arguments = text[open_paren + 1:index]
                    receiver = receiver_before_call(text, match.start())
                    yield match.group(1), receiver, split_top_level_arguments(arguments)
                    break


def local_table_aliases(text, tables):
    """Track simple local aliases and borrows of whole SymbolTables."""
    if not tables:
        return set()
    bare_name = BORROWED_NAME_PREFIX + r"(\w+)(?:\s*\))*"
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


def local_global_aliases(text, globals_, mutable_ref_globals):
    """Track simple local aliases of mutable globals and their nested fields."""
    if not globals_:
        return set(), set()
    global_names = "(?:" + "|".join(sorted(map(re.escape, globals_))) + ")"
    global_path = r"(?P<global_root>" + global_names + r")(?:(?:\s*\.\s*\w+)|(?:\s*\[[^\]\n]*\]))*"
    alias_path = r"(\w+)(?:(?:\s*\.\s*\w+)|(?:\s*\[[^\]\n]*\]))*"
    borrowed_prefix = r"(?:\(\s*)*&\s*(?:\(\s*)*"
    assignment = re.compile(
        r"^\s*(\w+)\s*(?::[^=\n]+)?\s*(?:<-|=)\s*"
        + BORROWED_NAME_PREFIX + global_path + r"(?:\s*\))*\s*$",
        re.MULTILINE,
    )
    borrowed_global_assignment = re.compile(
        r"^\s*(\w+)\s*(?::[^=\n]+)?\s*(?:<-|=)\s*"
        + borrowed_prefix + global_path + r"(?:\s*\))*\s*$",
        re.MULTILINE,
    )
    alias_assignment = re.compile(
        r"^\s*(\w+)\s*(?::[^=\n]+)?\s*(?:<-|=)\s*"
        + BORROWED_NAME_PREFIX + alias_path + r"(?:\s*\))*\s*$",
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


COPY_VALUE_TYPE_NAMES = {
    "i8", "i16", "i32", "i64", "u8", "u16", "u32", "u64",
    "isize", "usize", "int", "f32", "f64", "bool", "char", "sview",
}


def type_is_copy_value(type_expression, aliases, structs, seen=frozenset()):
    """Whether a type is safely copied, using an iterative alias/struct walk.

    Deep generated alias chains are common enough to avoid Python recursion here.
    The walk is O(V + E), memoized by terminal type name, and cycles fail closed.
    """
    def classify(expression):
        expression = expression.strip()
        while expression.startswith("(") and matching_delimiter(expression, 0) == len(expression) - 1:
            expression = expression[1:-1].strip()
        while expression.endswith("?"):
            expression = expression[:-1].rstrip()
        if "&" in expression:
            # Copying an immutable reference cannot mutate its referent. A mutable
            # reference alias remains tainted even when reached through a type alias.
            return ("value", expression.endswith("&") and not
                    type_expression_is_mutable_ref(expression, aliases))
        expression = re.sub(r"^(?:(?:mutable|static|heap|stack)\s+)+", "", expression)
        if "[" in expression or "{" in expression or "," in expression:
            return "invalid", None
        if not re.fullmatch(r"(?:\w+::)*\w+", expression):
            return "invalid", None
        name = expression.rsplit("::", 1)[-1]
        if name in COPY_VALUE_TYPE_NAMES:
            return "value", True
        return "name", name

    kind, root = classify(type_expression)
    if kind == "value":
        return root
    if kind == "invalid":
        return False

    memo = {}
    active = set(seen)
    frames = []

    def push(name):
        if name in memo:
            return
        if name in active:
            return
        active.add(name)
        candidates = aliases.get(name, ())
        if candidates:
            children = list(candidates)
        else:
            struct_candidates = structs.get(name, ())
            if not struct_candidates:
                memo[name] = False
                active.remove(name)
                return
            # A const enum has an empty field list and therefore copies by value.
            children = [
                field_type
                for fields in struct_candidates
                for field_type in (fields.values() if isinstance(fields, dict) else fields)
            ]
        frames.append([name, children, 0, True])

    push(root)
    while frames:
        name, children, index, result = frames[-1]
        if not result:
            memo[name] = False
            active.remove(name)
            frames.pop()
            continue
        if index >= len(children):
            memo[name] = True
            active.remove(name)
            frames.pop()
            continue

        child_kind, child = classify(children[index])
        frames[-1][2] += 1
        if child_kind == "value":
            if not child:
                frames[-1][3] = False
        elif child_kind == "invalid" or child in active or child in seen:
            # Unknown types and recursive cycles are conservatively non-copy.
            frames[-1][3] = False
        elif child in memo:
            if not memo[child]:
                frames[-1][3] = False
        else:
            push(child)

    return memo.get(root, False)


def local_table_field_aliases(text, tables, table_field_types, type_aliases, struct_field_types):
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
        + BORROWED_NAME_PREFIX
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
        expression_type = table_field_expression_type(
            rhs, tables, table_field_types, type_aliases, struct_field_types
        )
        declared_is_copy = bool(
            declared_type
            and type_is_copy_value(declared_type, type_aliases, struct_field_types)
        )
        expression_is_copy = bool(
            expression_type
            and type_is_copy_value(expression_type, type_aliases, struct_field_types)
        )
        source_is_copy = (
            declared_is_copy and (not expression_type or expression_is_copy)
            if declared_type
            else expression_is_copy
            or bool(source_type and type_is_copy_value(source_type, type_aliases, struct_field_types))
        )
        if source_is_copy:
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
            if type_is_copy_value(
                local_types.get(target_name, ""), type_aliases, struct_field_types
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


def argument_is_table_field_or_alias(argument, tables, aliases):
    if tables:
        table_names = "(?:" + "|".join(sorted(map(re.escape, tables))) + ")"
        if re.search(r"\b" + table_names + r"\s*(?:\.\s*\w+|\[[^\]\n]*\])", argument):
            return True
    return any(re.search(r"\b" + re.escape(alias) + r"\b", argument) for alias in aliases)


def table_field_expression_type(argument, tables, table_field_types, type_aliases, struct_field_types):
    """Resolve a simple table-field path to its value type, including indexed elements."""
    expression = argument.strip()
    if expression.startswith("&"):
        return ""
    while expression.startswith("(") and matching_delimiter(expression, 0) == len(expression) - 1:
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
            close = matching_delimiter(expression, cursor)
            if close is None:
                return ""
            container_type = re.sub(r"^(?:(?:mutable|static|heap|stack)\s+)+", "", current_type.strip())
            container_name = re.match(r"(?:\w+::)*([\w]+)\s*\[", container_type)
            if container_name is None:
                return ""
            type_open = container_type.find("[")
            type_close = matching_delimiter(container_type, type_open)
            if type_close is None:
                return ""
            type_args = split_top_level_arguments(container_type[type_open + 1:type_close])
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


def local_path_expression_type(expression, text, struct_field_types):
    """Resolve a simple local or local-struct-field type from its declaration."""
    path = re.fullmatch(r"\s*(\w+)((?:\s*\.\s*\w+)*)\s*", expression)
    if path is None:
        return ""
    local_types = {
        match.group(1): match.group(2).strip()
        for match in re.finditer(
            r"^[ \t]*(\w+)[ \t]*:[ \t]*(.+?)[ \t]*(?:<-|=(?!=))", text, re.MULTILINE
        )
    }
    header = DEF_RE.match(text)
    if header:
        for formal in split_top_level_arguments(header.group(3)):
            match = re.match(r"\s*(\w+)\s*:\s*(.+?)\s*(?:=(?!=).*)?$", formal)
            if match:
                local_types[match.group(1)] = match.group(2).strip()
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


def is_builtin_darray_type(type_expression, aliases, seen=frozenset()):
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
        is_builtin_darray_type(candidate, aliases, seen | {name})
        for candidate in candidates
    )


def is_builtin_scalar_type(type_expression, aliases, seen=frozenset()):
    expression = re.sub(
        r"^(?:(?:mutable|static|heap|stack)\s+)+", "", type_expression.strip()
    )
    if not re.fullmatch(r"(?:\w+::)*\w+", expression):
        return False
    name = expression.rsplit("::", 1)[-1]
    if name in COPY_VALUE_TYPE_NAMES | {"uintptr"}:
        return True
    if name in seen:
        return False
    candidates = aliases.get(name, ())
    return bool(candidates) and all(
        is_builtin_scalar_type(candidate, aliases, seen | {name})
        for candidate in candidates
    )


def function_return_type(definition):
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


def type_equivalents(type_expression, aliases):
    """Return unambiguous spelling paths for a simple source type/alias."""
    def normalize(expression):
        expression = expression.strip()
        while expression.startswith("(") and matching_delimiter(expression, 0) == len(expression) - 1:
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


def matching_cast_candidate_indexes(candidates, source_type, target_type, aliases):
    """Match scalar cast hooks by source and target type; unknown signatures fail closed."""
    source_names = type_equivalents(source_type, aliases)
    target_names = type_equivalents(target_type, aliases)
    selected = []
    for index, candidate in enumerate(candidates):
        formals = split_top_level_arguments(candidate.get("params", ""))
        if len(formals) != 1 or not source_names or not target_names:
            selected.append(index)
            continue
        formal = formals[0].split(":", 1)
        if len(formal) != 2:
            selected.append(index)
            continue
        parameter_type = re.split(r"\s*=(?!=)", formal[1], maxsplit=1)[0].strip()
        returned_type = function_return_type(candidate)
        parameter_names = type_equivalents(parameter_type, aliases)
        returned_names = type_equivalents(returned_type, aliases)
        if not parameter_names or not returned_names:
            selected.append(index)
        elif source_names & parameter_names and target_names & returned_names:
            selected.append(index)
    return selected


def receiver_expression_type(
    receiver, text, tables, table_field_types, aliases, structs, definitions
):
    """Infer the receiver type from local/table paths, literals, or a source call."""
    expression = receiver.strip()
    value_type = table_field_expression_type(
        expression, tables, table_field_types, aliases, structs
    )
    if not value_type:
        value_type = local_path_expression_type(expression, text, structs)
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
        if matching_delimiter(expression, opening) == len(expression) - 1:
            returns = {
                function_return_type(candidate)
                for candidate in definitions.get(call.group(1), ())
                if function_return_type(candidate)
            }
            if len(returns) == 1:
                return next(iter(returns))
    return ""


def receiver_method_is_known_intrinsic(
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

    receiver_type = receiver_expression_type(
        receiver, text, tables, table_field_types, aliases, structs, definitions
    )
    if not receiver_type:
        return False

    if callee in BUILTIN_NUMERIC_CAST_METHODS | {"char", "int"}:
        terminal = receiver_type.rsplit("::", 1)[-1].rstrip("&?").strip()
        return is_builtin_scalar_type(receiver_type, aliases) or any(
            fields == [] for fields in structs.get(terminal, ())
        )

    container = re.sub(
        r"^(?:(?:mutable|lmut|static|heap|stack)\s+)+", "", receiver_type.strip()
    ).rstrip("&?").strip()
    container_match = re.match(r"(?:\w+::)?(darray|array|dict|map|set|sview)\s*(?:\[|$)", container)
    is_container = bool(container_match) or is_builtin_darray_type(receiver_type, aliases)
    if is_container and (
        re.fullmatch(MUTATORS, callee)
        or callee in READ_ONLY_TABLE_METHODS | READ_ONLY_TABLE_CALLS
    ):
        return True
    return False


def specialized_cast_definitions(definitions, candidate):
    """Build only the source call closure needed to summarize one cast overload."""
    subset = {"__cast__": [candidate]}
    pending = [candidate]
    seen_names = {"__cast__"}
    nested_cast = False
    while pending:
        definition = pending.pop()
        text = mask_string_literals(strip_comments("".join(definition.get("body", ()))))
        for callee, receiver, _arguments in call_sites(text):
            if callee == "__cast__" or (receiver and callee in BUILTIN_NUMERIC_CAST_METHODS):
                nested_cast = True
                continue
            if callee in definitions and callee not in seen_names:
                seen_names.add(callee)
                subset[callee] = definitions[callee]
                pending.extend(definitions[callee])
    return subset, nested_cast


def argument_is_whole_table(argument, tables, aliases):
    """Whether an argument is a bare SymbolTable value or alias (possibly borrowed)."""
    expression = argument.strip()
    while expression.startswith("&"):
        expression = expression[1:].strip()
    while expression.startswith("(") and matching_delimiter(expression, 0) == len(expression) - 1:
        expression = expression[1:-1].strip()
    return bool(re.fullmatch(r"\w+", expression) and expression in tables | aliases)


def argument_is_table_backed(argument, tables, table_aliases, field_aliases):
    return (
        argument_is_whole_table(argument, tables, table_aliases)
        or argument_is_table_field_or_alias(argument, tables, field_aliases)
    )


def is_diagnostics_receiver(receiver, tables, diagnostic_aliases):
    """Recognize only a direct diagnostics field or its already-tracked local alias."""
    expression = receiver.strip()
    while expression.startswith("(") and matching_delimiter(expression, 0) == len(expression) - 1:
        expression = expression[1:-1].strip()
    if expression in diagnostic_aliases:
        return True
    match = re.fullmatch(r"(\w+)\s*\.\s*diagnostics", expression)
    return bool(match and match.group(1) in tables)


def mutable_actual_indexes(arguments, candidates):
    """Return actual positions that could reach mutable formals at a callsite."""
    if not candidates:
        return set(range(len(arguments)))
    possibly_mutable = set()
    for candidate in candidates:
        if candidate.get("external"):
            return set(range(len(arguments)))
        formals = split_top_level_arguments(candidate["params"])
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


def argument_global_names(argument, globals_, aliases):
    """Return mutable globals named directly or through a simple local alias."""
    names = {name for name in globals_ if re.search(r"\b" + re.escape(name) + r"\b", argument)}
    if any(re.search(r"\b" + re.escape(alias) + r"\b", argument) for alias in aliases):
        # Alias provenance is intentionally collapsed: any write through an alias
        # already disqualifies the defining pass, and mutable calls must do the same.
        names.add("aliased-global")
    return names


def call_may_mutate_table_field(
    arguments, candidates, tables, aliases, table_field_types=None, type_aliases=None,
    struct_field_types=None, allow_copied_values=False, builtin_value_push=False,
):
    """Conservatively match tainted actuals to mutable formals across overloads."""
    table_field_types = table_field_types or {}
    type_aliases = type_aliases or {}
    struct_field_types = struct_field_types or {}
    possibly_mutable = mutable_actual_indexes(arguments, candidates)
    tainted = []
    for index, argument in enumerate(arguments):
        is_tainted = argument_is_table_field_or_alias(argument, tables, aliases)
        if is_tainted and allow_copied_values:
            value_type = table_field_expression_type(
                argument, tables, table_field_types, type_aliases, struct_field_types
            )
            formal_is_by_value = bool(candidates) and index not in possibly_mutable
            if value_type and type_is_copy_value(value_type, type_aliases, struct_field_types) and (
                formal_is_by_value or builtin_value_push
            ):
                is_tainted = False
        tainted.append(is_tainted)
    return any(is_tainted and index in possibly_mutable for index, is_tainted in enumerate(tainted))


def analyze(
    defs, globals_, mutable_ref_globals, type_aliases, table_field_types, struct_field_types,
    enum_variants=None, _build_cast_nodes=True,
):
    """Per definition name: (writes, reads_diagnostics, callees)."""
    glob_re = re.compile(r"\b(" + "|".join(sorted(map(re.escape, globals_))) + r")\b") if globals_ else None
    info = {}
    cast_nodes = {}
    enum_variants = enum_variants or {}
    for name, bodies in defs.items():
        writes, reads_diag, callees = set(), False, set()
        for d in bodies:
            text = strip_comments("".join(d["body"]))
            code_text = mask_string_literals(text)
            handled_cast_sites = set()
            tables = set(TABLE_DECL_RE.findall(d["params"])) | set(TABLE_DECL_RE.findall(text))
            table_aliases = local_table_aliases(text, tables)
            tables.update(table_aliases)
            global_aliases, borrowed_global_aliases = local_global_aliases(
                text, globals_, mutable_ref_globals
            )
            field_aliases, diagnostic_aliases, borrowed_field_aliases = local_table_field_aliases(
                text, tables, table_field_types, type_aliases, struct_field_types
            )
            for t in sorted(tables):
                te = re.escape(t)
                for m in re.finditer(te + r"\.(\w+)(?:(?:\.\w+)|(?:\[[^\]\n]*\]))*\s*<-", text):
                    if m.group(1) != "diagnostics":
                        writes.add(m.group(1))
                for m in re.finditer(te + r"\.(\w+)(?:(?:\.\w+)|(?:\[[^\]\n]*\]))*\.(?:" + MUTATORS + r")\(", text):
                    if m.group(1) != "diagnostics":
                        writes.add(m.group(1))
                for m in re.finditer(r"\bin\s+" + te + r"\.(\w+)(?:(?:\.\w+)|(?:\[[^\]\n]*\]))*\s*:", text):
                    if m.group(1) != "diagnostics":
                        writes.add("in:" + m.group(1))
                for m in re.finditer(r"&\s*" + te + r"\.(\w+)", text):
                    writes.add("ref:" + m.group(1))
                # Only an in-place push extends diagnostics. A replacement can discard
                # earlier sequential results, and every other use reads them.
                for m in re.finditer(r"\b" + te + r"\.diagnostics\b", text):
                    after = text[m.end():]
                    before = text[:m.start(0)]
                    if re.match(r"\s*<-", after):
                        if re.match(
                            r"\s*<-\s*" + te + r"\.diagnostics\s*\.\s*push\s*\(",
                            after,
                        ):
                            continue
                        writes.add("diagnostics-replace")
                        continue
                    if re.match(r"\s*\.\s*push\s*\(", after) and re.search(
                        te + r"\.diagnostics\s*<-\s*$", before
                    ):
                        continue
                    reads_diag = True
            # Returning a table or one of its mutable fields lets callers carry the
            # alias beyond this function's local analysis. Mark that source helper as
            # effectful so every caller's audited closure fails closed. Scalar field
            # copies remain safe to return.
            for returned in re.finditer(r"\breturn\s+([^\n]+)", text):
                expression = returned.group(1).strip().rstrip(";").strip()
                if argument_is_whole_table(expression, tables, table_aliases):
                    writes.add("returned-whole-table-alias")
                    continue
                unwrapped = expression
                while unwrapped.startswith("(") and matching_delimiter(unwrapped, 0) == len(unwrapped) - 1:
                    unwrapped = unwrapped[1:-1].strip()
                borrowed = unwrapped.startswith("&")
                if borrowed:
                    unwrapped = unwrapped[1:].strip()
                    while unwrapped.startswith("(") and matching_delimiter(unwrapped, 0) == len(unwrapped) - 1:
                        unwrapped = unwrapped[1:-1].strip()
                field_path = re.fullmatch(
                    r"(\w+)((?:\s*\.\s*\w+|\s*\[[^\]\n]*\])+)", unwrapped
                )
                direct_field = bool(field_path and field_path.group(1) in tables)
                direct_alias = bool(
                    re.fullmatch(r"\w+", unwrapped)
                    and unwrapped in field_aliases | diagnostic_aliases
                )
                if direct_field or direct_alias:
                    value_type = table_field_expression_type(
                        unwrapped,
                        tables,
                        table_field_types,
                        type_aliases,
                        struct_field_types,
                    )
                    if borrowed or direct_alias or not value_type or not type_is_copy_value(
                        value_type, type_aliases, struct_field_types
                    ):
                        writes.add("returned-table-field-alias")
            if glob_re is not None:
                for m in glob_re.finditer(text):
                    lead = text[max(0, m.start() - 2):m.start()]
                    allocates = re.search(r"\bin\s+$", text[max(0, m.start() - 4):m.start()]) is not None
                    tail_end = global_path_write_tail(text, m.end())
                    tail = text[tail_end:]
                    assigns_path = re.match(r"\s*<-", tail) is not None
                    mutates_path = re.match(r"\s*\.\s*(?:" + MUTATORS + r")\s*\(", tail) is not None
                    if allocates or assigns_path or mutates_path or "&" in lead:
                        writes.add("global:" + m.group(1))
            for alias in sorted(global_aliases):
                ae = re.escape(alias)
                alias_part = r"(?:\s*\.\s*\w+|\s*\[[^\]\n]*\])"
                alias_path = r"\b" + ae + alias_part + r"*"
                if alias in borrowed_global_aliases and re.search(r"\b" + ae + r"\s*<-", text):
                    writes.add("global-alias:" + alias)
                if re.search(r"\b" + ae + alias_part + r"+\s*<-", text):
                    writes.add("global-alias:" + alias)
                if re.search(alias_path + r"\.(?:" + MUTATORS + r")\(", text):
                    writes.add("global-alias:" + alias)
                if re.search(r"\bin\s+" + alias_path + r"\s*:", text) or re.search(r"&\s*" + alias_path, text):
                    writes.add("global-alias:" + alias)
            for site in ast_constructions(text):
                writes.add("ast:" + site)
            # A local diagnostics alias can be inspected or can replace/clear diagnostics
            # from earlier sequential passes. Treat any such alias as a dependency on the
            # accumulated diagnostics stream instead of trying to infer its use mode.
            if diagnostic_aliases:
                reads_diag = True
            for alias in sorted(field_aliases):
                ae = re.escape(alias)
                alias_part = r"(?:\.\w+|\[[^\]\n]*\])"
                alias_path = r"\b" + ae + alias_part + r"*"
                if alias in borrowed_field_aliases and re.search(r"\b" + ae + r"\s*<-", text):
                    writes.add("alias:" + alias)
                if re.search(r"\b" + ae + alias_part + r"+\s*<-", text):
                    writes.add("alias:" + alias)
                if re.search(alias_path + r"\.(?:" + MUTATORS + r")\(", text):
                    writes.add("alias:" + alias)
                if re.search(r"\bin\s+" + alias_path + r"\s*:", text) or re.search(r"&\s*" + alias_path, text):
                    writes.add("alias:" + alias)
            for m in CALL_RE.finditer(code_text):
                callee = m.group(1)
                if callee in defs and callee != name:
                    callees.add(callee)
                if any(candidate.get("external") for candidate in defs.get(callee, ())):
                    writes.add("external-call:" + callee)
                if callee in globals_ or callee in global_aliases:
                    writes.add("global-callable:" + callee)
            for callee, receiver, arguments in call_sites(code_text):
                if (
                    receiver is None
                    and not defs.get(callee)
                    and callee not in NON_CALL_KEYWORDS
                    and callee not in PURE_FREE_CALLS
                ):
                    writes.add("unknown-call:" + callee)
                elif receiver is not None and callee in BUILTIN_NUMERIC_CAST_METHODS:
                    receiver_type = receiver_expression_type(
                        receiver,
                        text,
                        tables,
                        table_field_types,
                        type_aliases,
                        struct_field_types,
                        defs,
                    )
                    cast_candidates = defs.get("__cast__", ())
                    selected_cast_indexes = matching_cast_candidate_indexes(
                        cast_candidates, receiver_type, callee, type_aliases
                    ) if cast_candidates else []
                    selected_casts = [cast_candidates[index] for index in selected_cast_indexes]
                    if selected_casts:
                        if _build_cast_nodes:
                            for index, candidate in zip(selected_cast_indexes, selected_casts):
                                node = "__cast__@" + str(index)
                                callees.add(node)
                                cast_nodes[node] = candidate
                        else:
                            callees.add("__cast__")
                        if any(candidate.get("external") for candidate in selected_casts):
                            writes.add("external-call:__cast__")
                        if mutable_actual_indexes([receiver], selected_casts) and (
                            argument_is_table_backed(receiver, tables, table_aliases, field_aliases)
                            or argument_global_names(receiver, globals_, global_aliases)
                        ):
                            writes.add("mutable-or-unknown-table-field-argument:" + callee)
                        handled_cast_sites.add((callee, receiver))
                    elif (
                        receiver_type
                        and (
                            is_builtin_scalar_type(receiver_type, type_aliases)
                            or any(
                                fields == []
                                for fields in struct_field_types.get(
                                    receiver_type.rsplit("::", 1)[-1].rstrip("&?").strip(), ()
                                )
                            )
                        )
                    ) or (
                        (table_receiver_type := table_field_expression_type(
                            receiver,
                            tables,
                            table_field_types,
                            type_aliases,
                            struct_field_types,
                        ))
                        and type_is_copy_value(
                            table_receiver_type,
                            type_aliases,
                            struct_field_types,
                        )
                    ):
                        # With no matching user hook, scalar/const-enum conversions
                        # are built-in. A table-field receiver with a statically Copy
                        # value type is also safe to pass through this conversion: it
                        # cannot expose a mutable table alias. Exact __cast__ overloads
                        # were handled above using their selected-effect summaries.
                        handled_cast_sites.add((callee, receiver))
                elif (
                    receiver is not None
                    and callee not in NON_CALL_KEYWORDS
                    and not defs.get(callee)
                    and not (
                        callee == "push"
                        and is_diagnostics_receiver(receiver, tables, diagnostic_aliases)
                    )
                    and not receiver_method_is_known_intrinsic(
                        receiver,
                        callee,
                        text,
                        tables,
                        table_field_types,
                        type_aliases,
                        struct_field_types,
                        defs,
                        enum_variants,
                    )
                ):
                    writes.add("unknown-receiver-call:" + callee)
            # Reject calls through global function values, including nested indexing
            # and parenthesized callables which the name-only CALL_RE cannot resolve.
            for callable_name in globals_ | global_aliases:
                for match in re.finditer(r"\b" + re.escape(callable_name) + r"\b", text):
                    if global_path_is_invoked(text, match.end()):
                        writes.add("global-callable:" + callable_name)
            # A table field can be mutated through a helper's mutable container parameter
            # or a user method's mutable receiver without the helper receiving a
            # SymbolTable. The direct table-field checks above cannot see that alias, so
            # fail closed for such calls. The same applies when a local simply aliases a
            # table field. This intentionally accepts some false positives: those passes
            # run serially until the helper exposes an append-only contract.
            has_table_field_actual = bool(tables) and re.search(
                r"\b(?:" + "|".join(sorted(map(re.escape, tables))) + r")\b", text
            )
            has_alias_actual = bool(field_aliases)
            has_global_actual = bool(globals_) and glob_re.search(text)
            if has_table_field_actual or has_alias_actual or has_global_actual or global_aliases:
                for callee, receiver, arguments in call_sites(code_text):
                    if callee in NON_CALL_KEYWORDS:
                        continue
                    if callee in READ_ONLY_TABLE_CALLS:
                        continue
                    candidates = defs.get(callee)
                    actuals = list(arguments)
                    diagnostic_append = (
                        callee == "push"
                        and receiver is not None
                        and is_diagnostics_receiver(receiver, tables, diagnostic_aliases)
                    )
                    if diagnostic_append:
                        continue
                    if receiver is not None and (callee, receiver) in handled_cast_sites:
                        continue
                    table_receiver = bool(
                        receiver and argument_is_table_backed(
                            receiver, tables, table_aliases, field_aliases
                        )
                    )
                    derived_table_receiver = bool(
                        receiver
                        and not table_receiver
                        and any(
                            argument_is_table_backed(argument, tables, table_aliases, field_aliases)
                            for _inner_callee, _inner_receiver, inner_arguments in call_sites(receiver)
                            for argument in inner_arguments
                        )
                    )
                    global_receiver_names = (
                        argument_global_names(receiver, globals_, global_aliases)
                        if receiver else set()
                    )
                    if global_receiver_names:
                        # A method on shared global state can return a mutable alias even
                        # when its formal receiver is immutable. Without return-effect
                        # summaries, keep the caller out of parallel batches.
                        writes.add("global-receiver-call:" + callee)
                    if table_receiver and re.fullmatch(MUTATORS, callee):
                        writes.add("mutable-or-unknown-table-field-argument:" + callee)
                    if derived_table_receiver and (
                        re.fullmatch(MUTATORS, callee)
                        or not candidates
                        or callee not in READ_ONLY_TABLE_METHODS
                    ):
                        writes.add("mutable-or-unknown-table-field-argument:" + callee)
                    if (
                        receiver
                        and not diagnostic_append
                        and (
                            table_receiver or bool(global_receiver_names)
                        )
                        and (
                            global_receiver_names
                            or candidates
                            or re.fullmatch(MUTATORS, callee)
                            or callee not in READ_ONLY_TABLE_METHODS
                        )
                    ):
                        # Source-defined receiver methods are checked against their
                        # explicit first formal. Built-in mutators and unresolved
                        # methods have no source signature here, so conservatively
                        # treat the table-backed receiver as an argument to an
                        # unknown mutable effect. Known read-only built-ins are the
                        # narrow exception that preserves parallelism for lookups.
                        actuals.insert(0, receiver)
                    if call_may_mutate_table_field(
                        actuals,
                        candidates,
                        tables,
                        field_aliases,
                        table_field_types,
                        type_aliases,
                        struct_field_types,
                        allow_copied_values=bool(
                            receiver and not table_receiver and callee == "push"
                        ),
                        builtin_value_push=bool(
                            receiver
                            and not table_receiver
                            and callee == "push"
                            and not candidates
                            and is_builtin_darray_type(
                                local_path_expression_type(receiver, text, struct_field_types),
                                type_aliases,
                            )
                        ),
                    ):
                        writes.add("mutable-or-unknown-table-field-argument:" + callee)
                    if any(
                        argument_is_whole_table(argument, tables, table_aliases)
                        for argument in actuals
                    ) and (
                        not candidates
                        or any(candidate.get("external") for candidate in candidates)
                    ):
                        writes.add("unknown-or-external-whole-table-argument:" + callee)
                    mutable_actuals = mutable_actual_indexes(actuals, candidates)
                    for index, argument in enumerate(actuals):
                        if index in mutable_actuals:
                            writes.update(
                                "mutable-global-argument:" + name
                                for name in argument_global_names(argument, globals_, global_aliases)
                            )
        info[name] = (writes, reads_diag, callees)
    if _build_cast_nodes:
        for node, candidate in cast_nodes.items():
            specialized_defs, nested_cast = specialized_cast_definitions(defs, candidate)
            specialized_info = analyze(
                specialized_defs,
                globals_,
                mutable_ref_globals,
                type_aliases,
                table_field_types,
                struct_field_types,
                enum_variants,
                _build_cast_nodes=False,
            )
            writes, reads_diag, callees = specialized_info.get("__cast__", (set(), False, set()))
            if nested_cast:
                writes = set(writes) | {"unknown-nested-cast"}
            info[node] = (writes, reads_diag, callees)
    return info


def closure_facts(info, root):
    seen, stack = set(), [root]
    while stack:
        x = stack.pop()
        if x in seen or x not in info:
            continue
        seen.add(x)
        stack.extend(info[x][2])
    writes = set().union(*(info[x][0] for x in seen)) if seen else set()
    reads = any(info[x][1] for x in seen)
    return writes, reads


def append_only(info, name):
    writes, reads = closure_facts(info, name)
    return not writes and not reads, writes, reads


def pipeline_statements():
    """(line index, indent, pass name, args, cond) for each `table <- pass(...)` statement in
    check_full_into_pipeline, plus the function's parameter names."""
    lines = open(API, encoding="utf-8").read().split("\n")
    start = next(i for i, l in enumerate(lines) if re.match(r"\s*def " + PIPELINE + r"\(", l))
    params = [p.split(":")[0].strip() for p in DEF_RE.match(lines[start]).group(3).split(",")]
    indent = len(lines[start]) - len(lines[start].lstrip())
    end = start + 1
    while end < len(lines) and (not lines[end].strip() or len(lines[end]) - len(lines[end].lstrip()) > indent):
        end += 1
    return lines, start, end, params


TABLE_CALL_PREFIX_RE = re.compile(r"^([ \t]*)table <- (\w+)\(")
TIMER_RE = re.compile(r'^\s*PhaseTimer::minor\("[^"]*"\)$')


def parse_table_call_statement(line):
    """Parse one table-rebinding call, including balanced args and trailing `if`/`can` clauses."""
    code = strip_comments(line)
    prefix = TABLE_CALL_PREFIX_RE.match(code)
    if prefix is None:
        return None

    open_paren = prefix.end() - 1
    depth = 0
    quote = None
    escaped = False
    close_paren = None
    for index in range(open_paren, len(code)):
        char = code[index]
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in "\"'":
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                close_paren = index
                break
    if close_paren is None:
        return None

    suffix = code[close_paren + 1:].strip()
    markers = []
    paren_depth = bracket_depth = brace_depth = 0
    quote = None
    escaped = False
    for index, char in enumerate(suffix):
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in "\"'":
            quote = char
            continue
        if paren_depth == 0 and bracket_depth == 0 and brace_depth == 0:
            if (index == 0 or suffix[index - 1].isspace()) and suffix.startswith("if ", index):
                markers.append((index, "if", 3))
            elif (index == 0 or suffix[index - 1].isspace()) and suffix.startswith("can ", index):
                markers.append((index, "can", 4))
        if char == "(":
            paren_depth += 1
        elif char == ")":
            paren_depth -= 1
        elif char == "[":
            bracket_depth += 1
        elif char == "]":
            bracket_depth -= 1
        elif char == "{":
            brace_depth += 1
        elif char == "}":
            brace_depth -= 1

    if suffix and (not markers or markers[0][0] != 0 or len({kind for _, kind, _ in markers}) != len(markers)):
        return None
    condition = None
    for marker_index, kind, token_len in markers:
        next_index = next((other_index for other_index, _, _ in markers if other_index > marker_index), len(suffix))
        value = suffix[marker_index + token_len:next_index].strip()
        if not value:
            return None
        if kind == "if":
            condition = value

    return {
        "indent": prefix.group(1),
        "name": prefix.group(2),
        "args": code[open_paren + 1:close_paren],
        "cond": condition,
        "suffix": suffix,
    }


def eligible_args(args, cond, flags):
    allowed = {"file", "loop_view", "table", "not", "and", "or"} | set(flags)
    text = args + " " + (cond or "")
    if "(" in text or "[" in text or '"' in text:
        return False
    for tok in re.findall(r"[A-Za-z_]\w*(?:\.\w+)*", text):
        if tok.split(".")[0] not in allowed:
            return False
    return True


def plan_runs(info):
    lines, start, end, params = pipeline_statements()
    flags = [p for p in params if p not in PIPELINE_CONTEXT]
    stmts = []
    i = start + 1
    while i < end:
        parsed = parse_table_call_statement(lines[i])
        if parsed:
            name, args, cond = parsed["name"], parsed["args"], parsed["cond"]
            ok, _, _ = append_only(info, name)
            timer = i + 1 < end and TIMER_RE.match(lines[i + 1])
            stmts.append({"line": i, "indent": parsed["indent"], "name": name, "args": args,
                          "cond": cond, "suffix": parsed["suffix"],
                          "ok": ok and eligible_args(args, cond, flags) and bool(timer), "timer": bool(timer)})
        i += 1
    runs, current = [], []
    for s in stmts:
        if current and (s["ok"] and s["line"] == current[-1]["line"] + 2 and s["indent"] == current[-1]["indent"]):
            current.append(s)
            continue
        if len(current) >= MIN_RUN:
            runs.append(current)
        current = [s] if s["ok"] else []
    if len(current) >= MIN_RUN:
        runs.append(current)
    return lines, flags, stmts, runs


def has_mixed_generated_and_sequential_runs(lines, start, end, runs):
    return bool(runs) and any(PAR_RUN_ANY_RE.search(strip_comments(line)) for line in lines[start:end])


def emit(info):
    lines, flags, _stmts, runs = plan_runs(info)
    _lines, start, end, _params = pipeline_statements()
    all_generated_calls, malformed_lines = par_run_calls(lines)
    if malformed_lines:
        locations = ", ".join(str(line) for line in malformed_lines)
        raise ValueError("par_pass_run call does not match the generated call shape at semantic_api.elisa line(s) " + locations)
    generated_calls = [call for call in all_generated_calls if start <= call["line"] < end]
    if len(generated_calls) != len(all_generated_calls):
        raise ValueError("par_pass_run call found outside check_full_into_pipeline")
    has_generated_runs = bool(generated_calls)
    if has_mixed_generated_and_sequential_runs(lines, start, end, runs):
        raise ValueError("mixed generated par_pass_run calls and sequential eligible runs; restore a fully sequential pipeline before regenerating")
    # The checked-in API is already generated. Keep --write idempotent on that form too:
    # refresh its call and flag shapes, but retain the audited pass dispatcher below.
    if has_generated_runs:
        out = list(lines)
        for call in generated_calls:
            out[call["line"]] = normalized_par_run_line(out[call["line"]], call["match"])
        initializer = "flags: ParPassFlags = ParPassFlags{%s}" % ", ".join("%s: %s" % (flag, flag) for flag in flags)
        for i, line in enumerate(out):
            if re.match(r"\s*flags: ParPassFlags\s*=\s*ParPassFlags\{", line):
                indent = line[:len(line) - len(line.lstrip())]
                out[i] = indent + initializer
        return out, flags, [], []
    out = list(lines)
    calls = []
    pass_id = 0
    for k, run in enumerate(runs):
        first = pass_id
        for s in run:
            calls.append((pass_id, s))
            pass_id += 1
        head = run[0]
        new = [head["indent"] + "# Append-only passes %d..%d, run concurrently (semantic_parallel.elisa)." % (first, pass_id - 1),
               head["indent"] + "table <- par_pass_run(file, &loop_view, flags, table, shared_pool, %d, %d)" % (first, len(run)),
               head["indent"] + 'PhaseTimer::minor("sem:par_run_%d")' % k]
        for s in run:
            out[s["line"]] = None
            out[s["line"] + 1] = None
        out[head["line"]] = new
    # The flags the passes read, built once where loop_view is.
    view_line = next(i for i in range(start, end) if re.match(r"\s*loop_view: Ast::File = ", lines[i]))
    view_indent = lines[view_line][:len(lines[view_line]) - len(lines[view_line].lstrip())]
    fields = ", ".join("%s: %s" % (f, f) for f in flags)
    out[view_line] = [lines[view_line], view_indent + "flags: ParPassFlags = ParPassFlags{%s}" % fields]
    flat = []
    for item in out:
        if item is None:
            continue
        flat.extend(item if isinstance(item, list) else [item])
    return flat, flags, calls, runs


def passes_source(flags, calls, max_batch):
    head = """# Stage1 semantic layer — the passes semantic_parallel.elisa may run concurrently, by id.
# GENERATED by scripts/semantic_parallel_gen.py --write from the sequential pipeline in
# semantic_api.elisa (check_full_into_pipeline); `--check` audits every pass below for append-only behavior.
# Ids follow pipeline order, which is the order par_pass_run splices diagnostics in.
#
# Continues semantic_api.elisa.

extend Semantic:
    private:
"""
    _lines, start, _end, _params = pipeline_statements()
    types = dict((p.split(":", 1)[0].strip(), p.split(":", 1)[1].strip()) for p in DEF_RE.match(_lines[start]).group(3).split(","))
    body = ["        # Largest generated batch; the shared semantic pool is capped to this size.",
            "        const PAR_PASS_MAX_BATCH: usize = %d" % max_batch,
            "",
            "        # check_full_into_pipeline's flags, for the passes' arguments and conditions.",
            "        struct ParPassFlags:"]
    body += ["            %s: %s" % (f, types[f]) for f in flags]
    body += ["",
            "        def par_pass_call(pass_id: u32, file: Ast::File&, loop_view: Ast::File&, flags: ParPassFlags, table: lmut SymbolTable) -> void:",
            "            can Memory.Allocate, Abort.Panic:"]
    for n, (pid, s) in enumerate(calls):
        args = re.sub(r"\b(" + "|".join(flags) + r")\b", r"flags.\1", s["args"]) if flags else s["args"]
        suffix = s.get("suffix", "")
        if suffix and flags:
            suffix = re.sub(r"\b(" + "|".join(flags) + r")\b", r"flags.\1", suffix)
        kw = "if" if n == 0 else "elif"
        body.append("                %s pass_id == %d:" % (kw, pid))
        body.append("                    table <- %s(%s)%s" % (s["name"], args, (" " + suffix) if suffix else ""))
    return head + "\n".join(body) + "\n"


def refresh_max_batch(source, max_batch):
    """Update only the generated pool bound while preserving an existing pass dispatcher."""
    line = "        const PAR_PASS_MAX_BATCH: usize = %d" % max_batch
    pattern = re.compile(r"^[ \t]*const PAR_PASS_MAX_BATCH: usize = \d+[ \t]*$")
    lines = source.splitlines()
    for index, existing in enumerate(lines):
        if pattern.fullmatch(existing):
            lines[index] = line
            next_line = index + 1
            while next_line < len(lines) and not lines[next_line].strip():
                next_line += 1
            lines[index + 1:next_line] = [""]
            return "\n".join(lines) + ("\n" if source.endswith("\n") else "")
    private = next((i for i, existing in enumerate(lines) if re.fullmatch(r"[ \t]*private:[ \t]*", existing)), None)
    if private is None:
        raise ValueError("cannot find private section in generated semantic pass file")
    lines[private + 1:private + 1] = [line, ""]
    return "\n".join(lines) + ("\n" if source.endswith("\n") else "")


def refresh_pass_flags(source, flags):
    """Refresh the flag record shape without regenerating its audited dispatch body."""
    _lines, start, _end, _params = pipeline_statements()
    types = dict((p.split(":", 1)[0].strip(), p.split(":", 1)[1].strip())
                 for p in DEF_RE.match(_lines[start]).group(3).split(","))
    fields = "\n".join("            %s: %s" % (flag, types[flag]) for flag in flags)
    pattern = re.compile(r"(^        struct ParPassFlags:\n)(?:^[ \t]+\w+: [^\n]*\n)*", re.M)
    updated, count = pattern.subn(lambda m: m.group(1) + fields + "\n", source, count=1)
    if count != 1:
        raise ValueError("cannot find ParPassFlags in generated semantic pass file")
    return updated


def generated_parallel_errors(info):
    """Validate generated pipeline ranges against the dispatcher's ordered pass IDs."""
    api = open(API, encoding="utf-8").read()
    passes = open(PASSES, encoding="utf-8").read()
    parallel = open(os.path.join(SRC, "semantic", "semantic_parallel.elisa"), encoding="utf-8").read()
    errors = []
    api_lines = api.splitlines()
    all_calls, malformed_lines = par_run_calls(api_lines)
    for line_number in malformed_lines:
        errors.append("semantic_api.elisa:%d: par_pass_run call does not match the generated call shape" % line_number)
    lines, start, end, _params = pipeline_statements()
    _lines, _flags, _stmts, sequential_runs = plan_runs(info)
    pipeline_calls, _pipeline_malformed = par_run_calls(lines[start:end], start)
    if has_mixed_generated_and_sequential_runs(lines, start, end, sequential_runs):
        errors.append("semantic_api.elisa: mixed generated batches and sequential eligible runs; regenerate from a fully sequential pipeline")
    pipeline_line_numbers = set(range(start, end))
    outside_calls = [call for call in all_calls if call["line"] not in pipeline_line_numbers]
    if outside_calls:
        errors.append("semantic_api.elisa: par_pass_run call found outside check_full_into_pipeline")
    if not pipeline_calls:
        errors.append("semantic_api.elisa: no generated par_pass_run calls found")
    if any(call["match"].group(2) is None for call in pipeline_calls):
        errors.append("semantic_api.elisa: generated par_pass_run call is missing shared_pool")
    counts = [call["count"] for call in pipeline_calls]
    max_batch = max(counts, default=1)
    bound = re.search(r"^\s*const PAR_PASS_MAX_BATCH: usize = (\d+)\s*$", passes, re.M)
    if bound is None:
        errors.append("semantic_parallel_passes.elisa: missing PAR_PASS_MAX_BATCH")
    elif int(bound.group(1)) != max_batch:
        errors.append("semantic_parallel_passes.elisa: PAR_PASS_MAX_BATCH does not match the largest run")

    pipeline_ids = []
    for call in pipeline_calls:
        if call["count"] <= 0:
            errors.append("semantic_api.elisa:%d: generated par_pass_run count must be positive" % (call["line"] + 1))
            continue
        if call["start"] < 0:
            errors.append("semantic_api.elisa:%d: generated par_pass_run start must not be negative" % (call["line"] + 1))
        pipeline_ids.extend(range(call["start"], call["start"] + call["count"]))
    if pipeline_ids != list(range(len(pipeline_ids))):
        errors.append("semantic_api.elisa: generated pass ranges must cover IDs once, in pipeline order, starting at 0")

    dispatch, dispatch_errors = parse_parallel_dispatch(passes)
    errors.extend(dispatch_errors)
    dispatch_ids = [record["id"] for record in dispatch]
    if dispatch_ids != pipeline_ids:
        errors.append("semantic_parallel_passes.elisa: dispatcher pass IDs/order do not match semantic_api.elisa ranges")
    if len({record["id"] for record in dispatch}) != len(dispatch):
        errors.append("semantic_parallel_passes.elisa: duplicate dispatcher pass ID")
    # Names, arguments, and conditions are parsed as one record per ID. The generated pipeline
    # retains only batch ranges, so only IDs and their order can be independently compared here.
    for record in dispatch:
        if not record["name"] or not record["args"].strip():
            errors.append("semantic_parallel_passes.elisa: incomplete dispatcher mapping for pass_id %d" % record["id"])

    _lines, _start, _end, params = pipeline_statements()
    expected_flags = [p for p in params if p not in PIPELINE_CONTEXT]
    flag_struct = re.search(r"struct ParPassFlags:\n((?:\s{12}\w+: [^\n]+\n)+)", passes)
    actual_flags = re.findall(r"^\s{12}(\w+):", flag_struct.group(1), re.M) if flag_struct else []
    if actual_flags != expected_flags:
        errors.append("semantic_parallel_passes.elisa: ParPassFlags does not match pipeline scalar flags")
    flag_init = re.search(r"^\s*flags: ParPassFlags\s*=\s*ParPassFlags\{([^}]+)\}", api, re.M)
    initialized_flags = re.findall(r"\b(\w+):", flag_init.group(1)) if flag_init else []
    if initialized_flags != expected_flags:
        errors.append("semantic_api.elisa: ParPassFlags initializer does not match pipeline scalar flags")
    if not re.search(r"def par_pass_run\([^\n]*shared_pool: mutable ThreadPool&", parallel):
        errors.append("semantic_parallel.elisa: par_pass_run does not accept the shared pool")
    return errors


def listed_passes():
    if not os.path.exists(PASSES):
        return []
    return re.findall(r"table <- (\w+)\(", open(PASSES, encoding="utf-8").read())


def main(argv):
    mode = argv[1] if len(argv) > 1 else "--check"
    (
        defs, globals_, mutable_ref_globals, type_aliases, table_field_types,
        struct_field_types, enum_variants,
    ) = parse_functions()
    info = analyze(
        defs, globals_, mutable_ref_globals, type_aliases, table_field_types,
        struct_field_types, enum_variants,
    )
    if mode == "--check":
        bad = []
        bad.extend(generated_parallel_errors(info))
        for name in listed_passes():
            ok, writes, reads = append_only(info, name)
            if not ok:
                bad.append("%s: writes %s%s" % (name, sorted(writes), " reads diagnostics" if reads else ""))
        if bad:
            print("semantic_parallel_gen: passes run concurrently that are NOT append-only:")
            for b in bad:
                print("  " + b)
            return 1
        from semantic_parallel_diagnostic_audit import main as audit_diagnostic_ownership
        try:
            audit_diagnostic_ownership()
        except AssertionError as error:
            print("semantic_parallel_gen: " + str(error))
            return 1
        print("semantic_parallel_gen: %d concurrent passes, all append-only" % len(listed_passes()))
        return 0
    if mode == "--report":
        _lines, _flags, stmts, runs = plan_runs(info)
        in_run = {s["line"] for r in runs for s in r}
        for s in stmts:
            ok, writes, reads = append_only(info, s["name"])
            tag = "RUN " if s["line"] in in_run else ("ok  " if ok else "seq ")
            print(tag, s["name"], "" if ok else sorted(writes)[:6], "reads-diag" if reads else "")
        print("runs", len(runs), "passes in runs", sum(len(r) for r in runs), "of", len(stmts))
        return 0
    if mode == "--write":
        try:
            flat, flags, calls, runs = emit(info)
        except ValueError as error:
            print("semantic_parallel_gen: refusing --write: " + str(error))
            return 1
        open(API, "w", encoding="utf-8").write("\n".join(flat))
        generated_counts = [int(m.group(4)) for line in flat for m in [PAR_RUN_RE.search(line)] if m]
        if calls or not generated_counts:
            max_batch = max((len(run) for run in runs), default=1)
            open(PASSES, "w", encoding="utf-8").write(passes_source(flags, calls, max_batch))
        else:
            max_batch = max(generated_counts)
            current = open(PASSES, encoding="utf-8").read()
            current = refresh_max_batch(current, max_batch)
            open(PASSES, "w", encoding="utf-8").write(refresh_pass_flags(current, flags))
        print("semantic_parallel_gen: %d runs, %d passes; flags %s" % (len(runs), len(calls), flags))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
