#!/usr/bin/env python3
"""Move one returning `match` arm out of an oversized function into its own function.

The new function takes the original parameters plus the arm's scrutinee and re-matches it:

    def NEW[<same region params>](<scrutinee>: <TYPE>, <original params>) -> <same return>:
        match <scrutinee>:
            <arm header, unchanged>
                <arm body, dedented>
            _:
                pass
        <fallback>

The arm body must end every path in `return` (the fallback is only reached for other
variants, which the caller never sends). In the original the arm becomes
`<Variant>(_, ...): return NEW(<scrutinee>, <original args>)`. Indentation inside the body
is shifted uniformly, so nothing else changes. The new function goes into NEW_FILE, which
is included directly after FILE wherever FILE is included.

usage: extract_match_arm.py FILE FUNCTION ARM_LINE SCRUTINEE_TYPE NEW_NAME NEW_FILE FALLBACK
  ARM_LINE: 1-based line of the arm header (e.g. `Expr.Call(a, b):`)
  FALLBACK: statement closing the new function, e.g. "return EmitStatus.Declined"
"""
import os
import re
import sys
from pathlib import Path


def indent(l):
    return len(l) - len(l.lstrip(" "))


def split_params(text):
    out, depth, cur = [], 0, ""
    for ch in text:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def main():
    path, fn, arm_line, stype, new_name, new_file, fallback = sys.argv[1:8]
    path, new_file = Path(path), Path(new_file)
    L = path.read_text().split("\n")
    a = int(arm_line) - 1
    d = next(i for i in range(a, -1, -1) if re.match(rf"\s*def {re.escape(fn)}\b", L[i]))
    sig = L[d]
    ai = indent(L[a])
    m = next(i for i in range(a - 1, d, -1) if indent(L[i]) == ai - 4 and L[i].strip().startswith("match "))
    scrutinee = re.match(r"\s*match (.*):\s*$", L[m]).group(1)
    if not re.fullmatch(r"[a-z_][a-z_0-9]*", scrutinee):
        raise SystemExit(f"scrutinee {scrutinee!r} is not a plain name")
    e = a + 1
    while e < len(L) and (not L[e].strip() or indent(L[e]) > ai):
        e += 1
    while L[e - 1].strip() == "":
        e -= 1
    # parameters: generics `[...]` then `(...)`
    head = re.match(rf"(\s*def ){re.escape(fn)}(\[[^\]]*\])?\((.*)\)(\s*->.*:)\s*$", sig)
    if not head:
        raise SystemExit("cannot parse signature")
    params = split_params(head.group(3))
    names = [p.split(":")[0].strip() for p in params]
    new_sig = f"{head.group(1)}{new_name}{head.group(2) or ''}({scrutinee}: {stype}, {', '.join(params)}){head.group(4)}"
    body_indent = indent(L[d + 1])
    shift = ai - (body_indent + 4)
    moved = []
    for l in L[a:e]:
        if l.strip():
            if indent(l) < shift:
                raise SystemExit("line shallower than shift")
            moved.append(l[shift:])
        else:
            moved.append(l)
    arm_header = L[a].strip()
    binders = re.match(r"([\w.:]+)\((.*)\):$", arm_header)
    if not binders:
        raise SystemExit("arm header has no binders")
    wild = f"{binders.group(1)}({', '.join('_' for _ in split_params(binders.group(2)))}):"
    pad = " " * body_indent
    func = [new_sig, f"{pad}match {scrutinee}:"] + moved + [f"{pad}    _:", f"{pad}        pass", f"{pad}{fallback}"]
    ext = next(l for l in reversed(L[:d]) if re.match(r"^(extend|module) ", l))
    ext = re.sub(r"^module ", "extend ", ext)
    lab = next((l for l in reversed(L[:d]) if re.match(r"^\s+(public|private):\s*$", l) and indent(l) == indent(sig) - 4), None)
    if new_file.exists():
        text = new_file.read_text().rstrip("\n").split("\n") + [""] + func
    else:
        text = [ext] + ([lab] if lab else []) + func
    call = f"return {new_name}({scrutinee}, {', '.join(names)})"
    L[a:e] = [" " * ai + wild, " " * (ai + 4) + call]
    path.write_text("\n".join(L))
    created = not new_file.exists()
    new_file.write_text("\n".join(text) + "\n")
    if created:
        for f in Path("src").rglob("*.elisa"):
            lines = f.read_text().split("\n")
            hit = False
            for k in range(len(lines) - 1, -1, -1):
                mm = re.match(r'^(\s*)include "([^"]+)"\s*$', lines[k])
                if mm and (f.parent / mm.group(2)).resolve() == path.resolve():
                    rel = os.path.relpath(new_file.resolve(), f.parent.resolve())
                    lines.insert(k + 1, f'{mm.group(1)}include "./{rel}"' if not rel.startswith(".") else f'{mm.group(1)}include "{rel}"')
                    hit = True
            if hit:
                f.write_text("\n".join(lines))
    print(f"{path}: moved {e - a} lines into {new_name}")


main()
