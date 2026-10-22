#!/usr/bin/env python3
"""Split an oversized Elisa source file into consecutive parts of at most LIMIT lines.

Pure code motion. The file is read as a sequence of items: top-level lines (includes,
`static if` blocks, flat `def`s, ...) and the members of each `extend X:` / `module X:`
block. Items keep their original order; part 1 ends with `include` lines for parts
2..N, so every include graph sees exactly the original declaration sequence (region
inference is order-sensitive, see docs on file splits).

A member's span starts at its leading comment/decorator block. A `public:`/`private:`
label belongs to the member after it. A part that starts inside a block reopens it with
`extend X:` (never `module X:`) plus the label in force. Items longer than LIMIT are
left whole; the caller must refactor them by hand. `_partN` names are placeholders:
rename each part after what it holds (and group 3+ parts into a `<stem>/` directory).
"""
import re
import sys
from pathlib import Path

LIMIT = 600


def indent(line):
    return len(line) - len(line.lstrip(" "))


def is_lead(line, at):
    # comment or decorator line at exactly indent `at`
    return line.strip() and indent(line) == at and line.lstrip().startswith(("#", "@"))


def items_of(lines):
    """Yield (lines, block_header, label_in_force) per movable item, in order."""
    items = []
    tops = [i for i, l in enumerate(lines) if l.strip() and indent(l) == 0 and not l.startswith(("#", "@"))]
    # walk each top-level start back over its comment/decorator lead
    starts = []
    for i in tops:
        j = i
        while j > 0 and is_lead(lines[j - 1], 0):
            j -= 1
        starts.append(j)
    if not starts:
        return None
    pre = lines[:starts[0]]
    bounds = list(zip(starts, starts[1:] + [len(lines)]))
    for (s, e), t in zip(bounds, tops):
        head = lines[t]
        m = re.match(r"^(extend|module) ([A-Za-z_][\w:]*):\s*$", head)
        if not m:
            items.append((lines[s:e], None, None))
            continue
        reopen = f"extend {m.group(2)}:"
        body = lines[t + 1:e]
        first = next((l for l in body if l.strip() and not l.lstrip().startswith(("#", "@")) and not re.match(r"^\s+(public|private):\s*$", l)), None)
        if first is None:
            items.append((lines[s:e], None, None))
            continue
        mi = indent(first)
        label_re = re.compile(rf"^ {{{mi - 4}}}(public|private):\s*$") if mi >= 8 else None
        mstarts = []
        for k, l in enumerate(body):
            if l.strip() and indent(l) == mi and not l.lstrip().startswith(("#", "@")):
                j = k
                while j > 0 and (is_lead(body[j - 1], mi) or (label_re and label_re.match(body[j - 1]))):
                    j -= 1
                mstarts.append(j)
        mstarts[0] = 0
        # the block header (and anything before the first member) travels with member 1
        label = None
        for a, b in zip(mstarts, mstarts[1:] + [len(body)]):
            chunk = body[a:b]
            if a == 0:
                chunk = lines[s:t + 1] + chunk
            items.append((chunk, reopen, label))
            for l in body[a:b]:
                if label_re and label_re.match(l):
                    label = l
    return pre, items


def split(path: Path, dry: bool):
    text = path.read_text()
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if len(lines) <= LIMIT:
        return None
    got = items_of(lines)
    if not got:
        raise SystemExit(f"{path}: skipped: no top-level items")
    pre, items = got
    if [l for c, _, _ in items for l in c] != lines[len(pre):]:
        raise SystemExit(f"{path}: skipped: item walk lost lines")
    parts, cur, size = [], [], len(pre)
    reserve = 0
    for item in items:
        chunk, reopen, label = item
        extra = 0 if not cur and not parts else (0 if cur else (1 if reopen else 0) + (1 if label else 0))
        if cur and size + len(chunk) > LIMIT - (1 if not parts else 0) - 8:
            parts.append(cur)
            cur, size = [], 0
        if not cur and parts:
            size += (1 if reopen and not chunk[0].startswith(("extend ", "module ")) and indent(chunk[0]) > 0 else 0)
            size += (1 if label and not re.match(r"^\s+(public|private):", chunk[0]) and indent(chunk[0]) > 0 else 0)
        cur.append(item)
        size += len(chunk)
    parts.append(cur)
    if len(parts) == 1:
        raise SystemExit(f"{path}: skipped: a single item exceeds the limit")
    names = [path] + [path.with_name(f"{path.stem}_part{n}.elisa") for n in range(2, len(parts) + 1)]
    for n in names[1:]:
        if n.exists():
            raise SystemExit(f"{path}: skipped: {n.name} exists")
    outputs = []
    for n, part in enumerate(parts):
        out = list(pre) if n == 0 else []
        chunk0, reopen, label = part[0]
        inside = indent(next(l for l in chunk0 if l.strip())) > 0
        if n > 0 and inside and reopen:
            out.append(reopen)
            if label and not re.match(r"^\s+(public|private):\s*$", chunk0[0]):
                out.append(label)
        for c, _, _ in part:
            out += c
        while out and out[-1] == "":
            out.pop()
        outputs.append(out)
    outputs[0] += [""] + [f'include "./{n.name}"' for n in names[1:]]
    big = [len(o) for o in outputs if len(o) > LIMIT]
    if not dry:
        for n, o in zip(names, outputs):
            n.write_text("\n".join(o) + "\n")
    return [len(o) for o in outputs], big


if __name__ == "__main__":
    dry = "--dry" in sys.argv
    for arg in [a for a in sys.argv[1:] if a != "--dry"]:
        try:
            r = split(Path(arg), dry)
        except SystemExit as e:
            print(e)
            continue
        if r:
            sizes, big = r
            print(f"{arg}: {len(sizes)} parts ({', '.join(map(str, sizes))})" + (f"; {len(big)} over limit" if big else ""))
