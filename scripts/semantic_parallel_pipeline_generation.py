"""Pipeline generation for the semantic parallel-pass audit."""
import collections
from functools import lru_cache
import os
import re
import sys


def closure_facts(_services, info, root):
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

def append_only(_services, info, name):
    writes, reads = _services['closure_facts'](info, name)
    return not writes and not reads, writes, reads

def pipeline_statements(_services):
    """(line index, indent, pass name, args, cond) for each `table <- pass(...)` statement in
    check_full_into_pipeline, plus the function's parameter names."""
    lines = _services['read_pipeline_source'](_services['API'], annotated=True).split("\n")
    start = next(i for i, l in enumerate(lines) if re.match(r"\s*def " + _services['PIPELINE'] + r"(?:\[[^\]]*\])?\(", l))
    params = [p.split(":")[0].strip() for p in _services['DEF_RE'].match(lines[start]).group(3).split(",")]
    indent = len(lines[start]) - len(lines[start].lstrip())
    end = start + 1
    while end < len(lines) and (not lines[end].strip() or len(lines[end]) - len(lines[end].lstrip()) > indent):
        end += 1
    return lines, start, end, params

def parse_table_call_statement(_services, line):
    """Parse one table-rebinding call, including balanced args and trailing `if`/`can` clauses."""
    code = _services['strip_comments'](line)
    prefix = _services['TABLE_CALL_PREFIX_RE'].match(code)
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

def eligible_args(_services, args, cond, flags):
    allowed = {"file", "loop_view", "table", "not", "and", "or"} | set(flags)
    text = args + " " + (cond or "")
    if "(" in text or "[" in text or '"' in text:
        return False
    for tok in re.findall(r"[A-Za-z_]\w*(?:\.\w+)*", text):
        if tok.split(".")[0] not in allowed:
            return False
    return True

def plan_runs(_services, info):
    lines, start, end, params = _services['pipeline_statements']()
    flags = [p for p in params if p not in _services['PIPELINE_CONTEXT']]
    stmts = []
    i = start + 1
    while i < end:
        parsed = _services['parse_table_call_statement'](lines[i])
        if parsed:
            name, args, cond = parsed["name"], parsed["args"], parsed["cond"]
            ok, _, _ = _services['append_only'](info, name)
            timer = i + 1 < end and _services['TIMER_RE'].match(lines[i + 1])
            stmts.append({"line": i, "indent": parsed["indent"], "name": name, "args": args,
                          "cond": cond, "suffix": parsed["suffix"],
                          "ok": ok and _services['eligible_args'](args, cond, flags) and bool(timer), "timer": bool(timer)})
        i += 1
    runs, current = [], []
    for s in stmts:
        if current and (s["ok"] and s["line"] == current[-1]["line"] + 2 and s["indent"] == current[-1]["indent"]):
            current.append(s)
            continue
        if len(current) >= _services['MIN_RUN']:
            runs.append(current)
        current = [s] if s["ok"] else []
    if len(current) >= _services['MIN_RUN']:
        runs.append(current)
    return lines, flags, stmts, runs

def has_mixed_generated_and_sequential_runs(_services, lines, start, end, runs):
    return bool(runs) and any(_services['PAR_RUN_ANY_RE'].search(_services['strip_comments'](line)) for line in lines[start:end])

def emit(_services, info):
    lines, flags, _stmts, runs = _services['plan_runs'](info)
    _lines, start, end, _params = _services['pipeline_statements']()
    all_generated_calls, malformed_lines = _services['par_run_calls'](lines)
    if malformed_lines:
        locations = ", ".join(str(line) for line in malformed_lines)
        raise ValueError("par_pass_run call does not match the generated call shape at semantic_api.elisa line(s) " + locations)
    generated_calls = [call for call in all_generated_calls if start <= call["line"] < end]
    if len(generated_calls) != len(all_generated_calls):
        raise ValueError("par_pass_run call found outside check_full_into_pipeline")
    has_generated_runs = bool(generated_calls)
    if _services['has_mixed_generated_and_sequential_runs'](lines, start, end, runs):
        raise ValueError("mixed generated par_pass_run calls and sequential eligible runs; restore a fully sequential pipeline before regenerating")
    # The checked-in API is already generated. Keep --write idempotent on that form too:
    # refresh its call and flag shapes, but retain the audited pass dispatcher below.
    if has_generated_runs:
        dispatch, errors = _services['parse_parallel_dispatch'](open(_services['PASSES'], encoding="utf-8").read())
        if errors:
            raise ValueError("; ".join(errors))
        safe_ids = {record["id"] for record in dispatch if _services['append_only'](info, record["name"])[0]}
        out = list(lines)
        for call in generated_calls:
            match = call["match"]
            out[call["line"]] = "\n".join(
                match.group(1) + "table <- par_pass_run(file, flags, table, shared_pool, loop_view, "
                + str(first) + ", " + str(count) + ")" + (match.group(6) or "")
                for first, count in _services['split_parallel_range'](call["start"], call["count"], safe_ids)
            )
        initializer = "flags: ParPassFlags = ParPassFlags{%s}" % ", ".join("%s: %s" % (flag, flag) for flag in flags)
        for i, line in enumerate(out):
            if start <= i < end and re.match(r"\s*flags: ParPassFlags\s*=\s*ParPassFlags\{", line):
                indent = line[:len(line) - len(line.lstrip())]
                out[i] = indent + initializer
        out = [line for i, line in enumerate(out) if not (start <= i < end and re.match(r"\s*\w+:\s*mutable darray\[ParPassScratch\[", line))]
        return "\n".join(out).split("\n"), flags, [], []
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
               head["indent"] + "table <- par_pass_run(file, flags, table, shared_pool, loop_view, %d, %d)" % (first, len(run)),
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
    for i in range(start, end):
        if re.match(r"\s*\w+:\s*mutable darray\[ParPassScratch\[", lines[i]):
            out[i] = None
    flat = []
    for item in out:
        if item is None:
            continue
        flat.extend(item if isinstance(item, list) else [item])
    return flat, flags, calls, runs
