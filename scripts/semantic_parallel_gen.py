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

Passes run in `check_full_into` (semantic_api.elisa) as `table <- pass(ARGS) [if COND]`. A
maximal run of consecutive append-only passes whose ARGS/COND use only `file`, `loop_view`,
`table` and the function's scalar flags becomes one `par_pass_run` call; the passes go into
semantic_parallel_passes.elisa by id, in pipeline order (the splice order).

  semantic_parallel_gen.py --check      verify every pass in semantic_parallel_passes.elisa
                                        (exit 1 naming each one that is not append-only)
  semantic_parallel_gen.py --write      rewrite semantic_api.elisa runs + the passes file
                                        (input: the sequential pipeline; idempotent on it)
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
PIPELINE = "check_full_into"
MIN_RUN = 2
MUTATORS = r"push|extend|pop|clear|insert|remove|truncate|reserve|resize|set|swap|sort|append"
DEF_RE = re.compile(r"^(\s*)def (\w+)(?:\[[^\]]*\])?\((.*?)\)\s*(?:->|:)")
TABLE_DECL_RE = re.compile(r"\b(\w+)\s*:\s*(?:lmut\s+|mutable\s+|heap\s+)*SymbolTable\b")
GLOBAL_RE = re.compile(r"^\s*global\s+mutable\s+(\w+)")
CALL_RE = re.compile(r"\b(\w+)\s*(?:\[[^\]\n]*\])?\(")


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
    check_full_into, plus the function's parameter names."""
    lines = open(API, encoding="utf-8").read().split("\n")
    start = next(i for i, l in enumerate(lines) if re.match(r"\s*def " + PIPELINE + r"\(", l))
    params = [p.split(":")[0].strip() for p in DEF_RE.match(lines[start]).group(3).split(",")]
    indent = len(lines[start]) - len(lines[start].lstrip())
    end = start + 1
    while end < len(lines) and (not lines[end].strip() or len(lines[end]) - len(lines[end].lstrip()) > indent):
        end += 1
    return lines, start, end, params


STMT_RE = re.compile(r"^(\s*)table <- (\w+)\((.*)\)(?: if (.+))?$")
TIMER_RE = re.compile(r'^\s*PhaseTimer::minor\("[^"]*"\)$')


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
    flags = [p for p in params if p not in ("file", "table")]
    stmts = []
    i = start + 1
    while i < end:
        m = STMT_RE.match(lines[i])
        if m:
            name, args, cond = m.group(2), m.group(3), m.group(4)
            ok, _, _ = append_only(info, name)
            timer = i + 1 < end and TIMER_RE.match(lines[i + 1])
            stmts.append({"line": i, "indent": m.group(1), "name": name, "args": args, "cond": cond,
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


def emit(info):
    lines, flags, _stmts, runs = plan_runs(info)
    _lines, start, end, _params = pipeline_statements()
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
               head["indent"] + "table <- par_pass_run(file, &loop_view, flags, table, %d, %d)" % (first, len(run)),
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


def passes_source(flags, calls):
    head = """# Stage1 semantic layer — the passes semantic_parallel.elisa may run concurrently, by id.
# GENERATED by scripts/semantic_parallel_gen.py --write from the sequential pipeline in
# semantic_api.elisa (check_full_into); `--check` proves every pass below append-only.
# Ids follow pipeline order, which is the order par_pass_run splices diagnostics in.
#
# Continues semantic_api.elisa.

extend Semantic:
    private:
"""
    _lines, start, _end, _params = pipeline_statements()
    types = dict((p.split(":", 1)[0].strip(), p.split(":", 1)[1].strip()) for p in DEF_RE.match(_lines[start]).group(3).split(","))
    body = ["        # check_full_into's flags, for the passes' arguments and conditions.",
            "        struct ParPassFlags:"]
    body += ["            %s: %s" % (f, types[f]) for f in flags]
    body += ["",
            "        def par_pass_call(pass_id: u32, file: Ast::File&, loop_view: Ast::File&, flags: ParPassFlags, table: lmut SymbolTable) -> void:",
            "            can Memory.Allocate, Abort.Panic:"]
    for n, (pid, s) in enumerate(calls):
        args = re.sub(r"\b(" + "|".join(flags) + r")\b", r"flags.\1", s["args"]) if flags else s["args"]
        cond = s["cond"]
        if cond:
            cond = re.sub(r"\b(" + "|".join(flags) + r")\b", r"flags.\1", cond)
        kw = "if" if n == 0 else "elif"
        body.append("                %s pass_id == %d:" % (kw, pid))
        body.append("                    table <- %s(%s)%s" % (s["name"], args, (" if " + cond) if cond else ""))
    return head + "\n".join(body) + "\n"


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
        for name in listed_passes():
            ok, writes, reads = append_only(info, name)
            if not ok:
                bad.append("%s: writes %s%s" % (name, sorted(writes), " reads diagnostics" if reads else ""))
        if bad:
            print("semantic_parallel_gen: passes run concurrently that are NOT append-only:")
            for b in bad:
                print("  " + b)
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
        flat, flags, calls, runs = emit(info)
        open(API, "w", encoding="utf-8").write("\n".join(flat))
        open(PASSES, "w", encoding="utf-8").write(passes_source(flags, calls))
        print("semantic_parallel_gen: %d runs, %d passes; flags %s" % (len(runs), len(calls), flags))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
