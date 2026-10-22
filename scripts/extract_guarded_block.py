#!/usr/bin/env python3
"""Move one returning, pattern-guarded block out of an oversized function.

The block starts at BLOCK_LINE with `if <name> is <Variant>(<binders>):` or a match arm
`<Variant>(<binders>):`, and its last statement is a `return`. The new function has the
original signature (renamed) and repeats the chain of enclosing pattern headers
(`if x is V(...)`, `match x:` + arm) down to the block, so the block moves at its original
indentation byte for byte; a FALLBACK return closes it. In the original, the block becomes
its own header with wildcard binders followed by `return NEW(<original args>)`.

Refuses when an enclosing header is not a pure pattern test of a parameter or binder, when
the block reads a local declared in an enclosing body, or when it does not end in `return`.

usage: extract_guarded_block.py FILE FUNCTION BLOCK_LINE NEW_NAME NEW_FILE FALLBACK [--allow-fallthrough]
  --allow-fallthrough: the block may fall through when everything after it is `_: pass`
  arms and the FALLBACK statement itself.
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


def wildcard(header):
    m = re.match(r"^(\s*)(if \w+ is )?([\w.:]+)\((.*)\):\s*$", header)
    if not m:
        raise SystemExit(f"block header has no binders: {header.strip()}")
    return f"{m.group(1)}{m.group(2) or ''}{m.group(3)}({', '.join('_' for _ in split_params(m.group(4)))}):"


def main():
    fallthrough = "--allow-fallthrough" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--allow-fallthrough"]
    path, fn, line, new_name, new_file, fallback = args[:6]
    path, new_file = Path(path), Path(new_file)
    L = path.read_text().split("\n")
    b = int(line) - 1
    d = next(i for i in range(b, -1, -1) if re.match(rf"\s*def {re.escape(fn)}\b", L[i]))
    bi = indent(L[b])
    e = b + 1
    while e < len(L) and (not L[e].strip() or indent(L[e]) > bi):
        e += 1
    while L[e - 1].strip() == "" or L[e - 1].lstrip().startswith("#"):
        e -= 1
    last = next(l for l in reversed(L[b + 1:e]) if l.strip() and indent(l) == bi + 4)
    if not last.strip().startswith("return"):
        if not fallthrough:
            raise SystemExit("block does not end in return")
        # falling through is equivalent only if the rest of the function is the fallback
        fend = next((i for i in range(e, len(L)) if L[i].strip() and indent(L[i]) <= indent(L[d])), len(L))
        rest = [l.strip() for l in L[e:fend] if l.strip() and not l.lstrip().startswith("#")]
        if any(r not in ("_:", "pass", fallback) for r in rest) or fallback not in rest:
            raise SystemExit(f"code after the block is not just the fallback: {rest[:4]}")
    first = next(i for i in range(d + 1, len(L)) if L[i].strip() and not L[i].lstrip().startswith("#"))
    body_indent = indent(L[first])
    pattern = bool(re.match(r"^\s*(if \w+ is )?[\w.:]+\(.*\):\s*$", L[b]))
    # enclosing chain
    chain, level, k = [], bi, b
    while level > body_indent:
        k = next(i for i in range(k - 1, d, -1) if L[i].strip() and not L[i].lstrip().startswith("#") and indent(L[i]) < level)
        level = indent(L[k])
        chain.append(k)
    chain.reverse()
    if pattern:
        for c in chain:
            st = L[c].strip()
            ok = re.match(r"^if \w+ is [\w.:]+\(.*\):$", st) or re.match(r"^match \w+:$", st) or re.match(r"^[\w.:]+\(.*\):$", st) or st == "_:"
            if not ok:
                raise SystemExit(f"enclosing header is not a pattern test: {st}")
    elif chain:
        raise SystemExit("a condition-guarded block must sit at function-body level")
    # locals declared in enclosing bodies before the block
    declared = {}
    for i in range(d + 1, b):
        m = re.match(r"^\s+([a-z_][a-z_0-9]*)\s*:\s*(?:mutable\s+)?([^=]*?)\s*=", L[i])
        if m and indent(L[i]) <= bi:
            declared[m.group(1)] = m.group(2)
    block_text = "\n".join(L[b:e])
    used = sorted(n for n in declared if re.search(rf"\b{n}\b", block_text))
    extra = []
    if used:
        if pattern:
            raise SystemExit(f"block reads enclosing locals: {used}")
        for n in used:
            if re.search(rf"\b{n}\s*<-", block_text) or re.search(rf"[&]{n}\b", block_text):
                raise SystemExit(f"block writes enclosing local {n}")
            extra.append((n, declared[n]))
    sig = L[d]
    head = re.match(rf"(\s*def ){re.escape(fn)}(\[[^\]]*\])?\((.*)\)(\s*->.*:)\s*$", sig)
    if not head:
        raise SystemExit("cannot parse signature")
    names = [p.split(":")[0].strip() for p in split_params(head.group(3))]
    extra_params = "".join(f", {n}: {t}" for n, t in extra)
    new_sig = f"{head.group(1)}{new_name}{head.group(2) or ''}({head.group(3)}{extra_params}){head.group(4)}"
    # keep a leading `can` block line if the body is wrapped in one
    pre = [L[first]] if L[first].strip().startswith("can ") and L[first].rstrip().endswith(":") else []
    if pre and first in chain:
        pre = []
    if pattern:
        closers = []
        for c in reversed(chain):
            if L[c].strip().startswith("match "):
                closers += [" " * (indent(L[c]) + 4) + "_:", " " * (indent(L[c]) + 8) + "pass"]
        func = [new_sig] + pre + [L[c] for c in chain] + L[b:e] + closers + [" " * (indent(pre[0]) + 4 if pre else body_indent) + fallback]
    else:
        shift = 4 - (4 if pre else 0)
        moved = [l[shift:] if l.strip() else l for l in L[b + 1:e]]
        func = [new_sig] + pre + moved + ([" " * (indent(pre[0]) + 4 if pre else body_indent) + fallback] if fallthrough else [])
    ext = next(l for l in reversed(L[:d]) if re.match(r"^(extend|module) ", l))
    ext = re.sub(r"^module ", "extend ", ext)
    lab = next((l for l in reversed(L[:d]) if re.match(r"^\s+(public|private):\s*$", l) and indent(l) == indent(sig) - 4), None)
    created = not new_file.exists()
    text = ([ext] + ([lab] if lab else []) if created else new_file.read_text().rstrip("\n").split("\n") + [""]) + func
    call = " " * (bi + 4) + f"return {new_name}({', '.join(names + [n for n, _ in extra])})"
    L[b:e] = [wildcard(L[b]) if pattern else L[b], call]
    path.write_text("\n".join(L))
    new_file.write_text("\n".join(text) + "\n")
    if created:
        for f in Path("src").rglob("*.elisa"):
            lines = f.read_text().split("\n")
            hit = False
            for k2 in range(len(lines) - 1, -1, -1):
                mm = re.match(r'^(\s*)include "([^"]+)"\s*$', lines[k2])
                if mm and (f.parent / mm.group(2)).resolve() == path.resolve():
                    rel = os.path.relpath(new_file.resolve(), f.parent.resolve())
                    lines.insert(k2 + 1, f'{mm.group(1)}include "{rel if rel.startswith(".") else "./" + rel}"')
                    hit = True
            if hit:
                f.write_text("\n".join(lines))
    print(f"{path}: moved {e - b} lines into {new_name} ({new_file})")


main()
