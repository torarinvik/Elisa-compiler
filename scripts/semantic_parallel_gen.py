#!/usr/bin/env python3
"""Audit and generate the concurrent runs of append-only semantic passes (round 8).

A semantic pass may run on a worker thread over a frozen SymbolTable only if it is
APPEND-ONLY: through every function it can reach, the only SymbolTable field it writes is
`diagnostics`, it never reads earlier diagnostics, and it writes no mutable global. This script
proves that from the source, conservatively:

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
MUTATORS = r"push|extend|pop|clear|insert|remove|truncate|reserve|resize|set|swap|sort|append"
DEF_RE = re.compile(r"^(\s*)def (\w+)(?:\[[^\]]*\])?\((.*?)\)\s*(?:->|:)")
TABLE_DECL_RE = re.compile(r"\b(\w+)\s*:\s*(?:lmut\s+|mutable\s+|heap\s+)*SymbolTable\b")
GLOBAL_RE = re.compile(r"^\s*global\s+mutable\s+(\w+)")
CALL_RE = re.compile(r"\b(\w+)\s*(?:\[[^\]\n]*\])?\(")
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


def parse_functions():
    """name -> list of (file, params text, body lines)."""
    defs = collections.defaultdict(list)
    globals_ = set()
    for path in elisa_files():
        current = None
        indent = -1
        for line in open(path, encoding="utf-8"):
            g = GLOBAL_RE.match(line)
            if g:
                globals_.add(g.group(1))
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
    return defs, globals_


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


def analyze(defs, globals_):
    """Per definition name: (writes, reads_diagnostics, callees)."""
    glob_re = re.compile(r"\b(" + "|".join(sorted(map(re.escape, globals_))) + r")\b") if globals_ else None
    info = {}
    for name, bodies in defs.items():
        writes, reads_diag, callees = set(), False, set()
        for d in bodies:
            text = strip_comments("".join(d["body"]))
            tables = set(TABLE_DECL_RE.findall(d["params"])) | set(TABLE_DECL_RE.findall(text))
            for t in sorted(tables):
                te = re.escape(t)
                for m in re.finditer(te + r"\.(\w+)(?:\[[^\]\n]*\])?(?:\.\w+)*\s*<-", text):
                    if m.group(1) != "diagnostics":
                        writes.add(m.group(1))
                for m in re.finditer(te + r"\.(\w+)(?:\.\w+)*\.(?:" + MUTATORS + r")\(", text):
                    if m.group(1) != "diagnostics":
                        writes.add(m.group(1))
                for m in re.finditer(r"\bin\s+" + te + r"\.(\w+)\s*:", text):
                    if m.group(1) != "diagnostics":
                        writes.add("in:" + m.group(1))
                for m in re.finditer(r"&\s*" + te + r"\.(\w+)", text):
                    writes.add("ref:" + m.group(1))
                # Any diagnostics use that is not the append idiom `t.diagnostics <- t.diagnostics.push(`.
                for m in re.finditer(r"\b" + te + r"\.diagnostics\b(.{0,3})", text):
                    after = text[m.end(0) - len(m.group(1)):]
                    before = text[:m.start(0)]
                    if re.match(r"\s*<-", after):
                        continue
                    if re.match(r"\.push\(", after) and re.search(te + r"\.diagnostics\s*<-\s*$", before):
                        continue
                    reads_diag = True
            if glob_re is not None:
                for m in glob_re.finditer(text):
                    rest = text[m.end():m.end() + 4]
                    lead = text[max(0, m.start() - 2):m.start()]
                    allocates = re.search(r"\bin\s+$", text[max(0, m.start() - 4):m.start()]) is not None
                    if allocates or re.match(r"\s*<-", rest) or re.match(r"(?:\[[^\]]*\])?\.\w+\s*<-", text[m.end():m.end() + 40]) or "&" in lead:
                        writes.add("global:" + m.group(1))
            for site in ast_constructions(text):
                writes.add("ast:" + site)
            for m in CALL_RE.finditer(text):
                callee = m.group(1)
                if callee in defs and callee != name:
                    callees.add(callee)
        info[name] = (writes, reads_diag, callees)
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
# semantic_api.elisa (check_full_into_pipeline); `--check` proves every pass below append-only.
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
    defs, globals_ = parse_functions()
    info = analyze(defs, globals_)
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
