"""Syntax walk for the semantic parallel-pass audit."""
import collections
from functools import lru_cache
import os
import re
import sys


def parse_parallel_dispatch(_services, source):
    """Return dispatcher arms as (id, pass name, args, condition), plus structural errors."""
    lines = source.splitlines()
    definitions = []
    for index, line in enumerate(lines):
        match = re.match(
            r"^[ \t]*def (par_pass_call(?:_chunk_\d+)?)(?:\[[^\]\n]+\])?\(",
            line,
        )
        if match is not None:
            definitions.append((index, match.group(1)))
    if not definitions:
        return [], ["semantic_parallel_passes.elisa: missing par_pass_call dispatcher"]

    errors = []
    records = []
    for definition, _name in definitions:
        def_indent = len(lines[definition]) - len(lines[definition].lstrip())
        end = definition + 1
        while end < len(lines):
            line = lines[end]
            if line.strip() and not line.lstrip().startswith("#") and len(line) - len(line.lstrip()) <= def_indent:
                break
            end += 1

        arms = []
        for index in range(definition + 1, end):
            code = _services['strip_comments'](lines[index]).strip()
            if not _services['PAR_PASS_ARM_ANY_RE'].search(code):
                continue
            match = _services['PAR_PASS_ARM_RE'].fullmatch(lines[index])
            if match is None:
                errors.append("semantic_parallel_passes.elisa:%d: malformed pass_id arm" % (index + 1))
                continue
            arms.append((index, len(match.group(1)), match.group(2), int(match.group(3))))

        # The top-level wrapper has range checks and calls to the chunk helpers, but
        # no individual pass arms. Legacy generated files keep their arms directly
        # in par_pass_call, and are still accepted by this audit.
        if not arms:
            continue

        function_records = []
        for arm_index, (line_index, arm_indent, arm_kind, pass_id) in enumerate(arms):
            # Accept the legacy chain and the shallow independent-if dispatcher.
            # All later arms in one function must use the same form; mixed shapes remain an error.
            expected_kind = "if" if arm_index == 0 or len(arms) < 2 else arms[1][2]
            if arm_kind != expected_kind:
                errors.append("semantic_parallel_passes.elisa:%d: expected %s for pass_id %d" %
                              (line_index + 1, expected_kind, pass_id))
            stop = arms[arm_index + 1][0] if arm_index + 1 < len(arms) else end
            body = []
            for index in range(line_index + 1, stop):
                code = _services['strip_comments'](lines[index]).strip()
                if code:
                    body.append((index, len(lines[index]) - len(lines[index].lstrip()), code))
            statement = None
            scope = ""
            body_index = line_index
            if len(body) == 1 and body[0][1] > arm_indent:
                body_index, _indent, statement = body[0]
            elif (
                len(body) == 2
                and body[0][1] > arm_indent
                and re.fullmatch(r"can\b.*:", body[0][2])
                and body[1][1] > body[0][1]
            ):
                # Some dispatcher calls need an explicit local effect scope. Treat its
                # single nested table update as the arm's statement, while rejecting
                # scopes that contain multiple operations.
                body_index, _indent, statement = body[1]
                scope = body[0][2][:-1].strip()
            else:
                errors.append("semantic_parallel_passes.elisa:%d: pass_id %d must have exactly one body statement" %
                              (line_index + 1, pass_id))
                continue
            parsed = _services['parse_table_call_statement'](statement)
            if parsed is None:
                errors.append("semantic_parallel_passes.elisa:%d: unrecognized dispatcher call for pass_id %d" %
                              (body_index + 1, pass_id))
                continue
            function_records.append({"id": pass_id, "name": parsed["name"], "args": parsed["args"],
                                    "condition": parsed["cond"], "suffix": parsed["suffix"], "scope": scope})

        table_calls = [line for line in lines[definition:end]
                       if re.match(r"^[ \t]*table <- \w+\(", _services['strip_comments'](line))]
        if len(table_calls) != len(function_records):
            errors.append("semantic_parallel_passes.elisa: dispatcher table calls do not map one-to-one to pass_id arms")
        records.extend(function_records)

    return records, errors

def match_arm_body(_services, line):
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
        if rest.startswith("if "):
            # A guarded pattern still ends with the match-arm colon. Find that
            # colon outside nested expressions so constructors in the pattern or
            # guard are not mistaken for AST values built by the worker.
            depth = 0
            quote = None
            escaped = False
            for j, char in enumerate(rest):
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
                    depth += 1
                elif char in ")]}":
                    depth -= 1
                elif char == ":" and depth == 0:
                    return rest[j + 1:]
            return None
        return rest[1:] if rest.startswith(":") else None

def ast_constructions(_services, text):
    """AST node constructions in a body: a variant of the AST hierarchy used as a VALUE, not as
    a `match` arm pattern or an `is` test. Building a node grows the AST store, which the worker
    threads share; stage0 rejects the same thing in the seed (a submitted worker may only read)."""
    found = []
    for line in text.split("\n"):
        arm_value = _services['match_arm_body'](line)
        if arm_value is not None:
            line = arm_value
        for m in _services['AST_VARIANT_RE'].finditer(line):
            before = line[:m.start()]
            if re.search(r"\bis\s+(?:not\s+)?$", before):
                continue
            found.append("%s.%s" % (m.group(1), m.group(2)))
    return found

def split_top_level_arguments(_services, text):
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

def receiver_before_call(_services, text, call_start):
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

def matching_delimiter(_services, text, start):
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

def global_path_is_invoked(_services, text, end):
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
            close = _services['matching_delimiter'](text, cursor)
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

def global_path_write_tail(_services, text, end):
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
            if re.fullmatch(_services['MUTATORS'], member.group(0)) and after_member < len(text) and text[after_member] == "(":
                return cursor
            cursor = member_end
        elif text[cursor] == "[":
            close = _services['matching_delimiter'](text, cursor)
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

def call_sites(_services, text):
    """Yield (callee, receiver, argument strings) for calls in stripped source text."""
    for match in _services['CALL_RE'].finditer(text):
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
                    receiver = _services['receiver_before_call'](text, match.start())
                    yield match.group(1), receiver, _services['split_top_level_arguments'](arguments)
                    break
