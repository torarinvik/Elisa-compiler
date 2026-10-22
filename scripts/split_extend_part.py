#!/usr/bin/env python3
"""Split an oversized `extend X:` part file into consecutive parts of at most LIMIT lines.

Pure code motion: whole members move, in their original order, into `<stem>_N.elisa`
files whose `include` lines go directly after the original's include, so every include
graph sees the same declaration order as before (region inference is order-sensitive).

A member's span starts at its leading comment/decorator block. A `public:`/`private:`
label belongs to the member after it, and each new part reopens the label in force.
Exits non-zero, touching nothing, on any file shape it does not understand.
"""
import re
import sys
from pathlib import Path

LIMIT = 600
ROOT = Path(__file__).resolve().parent.parent
LABEL = re.compile(r"^    (public|private):\s*$")


def fail(path, why):
    raise SystemExit(f"{path}: skipped: {why}")


def split(path: Path, dry: bool):
    lines = path.read_text().split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if len(lines) <= LIMIT:
        return []
    tops = [i for i, l in enumerate(lines) if l and not l.startswith((" ", "#"))]
    if len(tops) != 1 or not re.match(r"^extend [A-Za-z_][\w:]*:\s*$", lines[tops[0]]):
        fail(path, "not a single top-level `extend X:` block")
    ext = tops[0]
    header, extend_line = lines[:ext], lines[ext]
    body = lines[ext + 1:]
    # member starts: indent-8 lines that are not comments/decorators; walk back over them
    starts = []
    for i, l in enumerate(body):
        if l.startswith("        ") and not l.startswith("         ") and not l[8:].startswith(("#", "@")) and l.strip():
            j = i
            while j > 0 and body[j - 1].startswith("        ") and not body[j - 1].startswith("         ") and body[j - 1][8:].startswith(("#", "@")):
                j -= 1
            # a label line directly above belongs to this member
            while j > 0 and LABEL.match(body[j - 1]):
                j -= 1
            starts.append(j)
    if not starts:
        fail(path, "no members at indent 8")
    for l in body[:starts[0]]:
        if l.strip() and not LABEL.match(l) and not l.startswith("        #"):
            fail(path, f"unexpected line before first member: {l[:60]!r}")
    for l in body:
        if l.strip() and not l.startswith("    "):
            fail(path, f"unindented line in block: {l[:60]!r}")
    spans = [(s, e) for s, e in zip(starts, starts[1:] + [len(body)])]
    prefix = body[:starts[0]]

    def label_at(index):
        current = None
        for l in body[:index]:
            m = LABEL.match(l)
            if m:
                current = l
        return current

    parts, cur, cur_len = [], [], len(header) + 1 + len(prefix)
    for s, e in spans:
        size = e - s
        if cur and cur_len + size > LIMIT:
            parts.append(cur)
            cur, cur_len = [], 2
        cur.append((s, e))
        cur_len += size
    parts.append(cur)
    if len(parts) == 1:
        fail(path, "single member exceeds limit")
    oversized = [(s, e) for s, e in spans if e - s + 2 > LIMIT]

    outputs = []
    for n, part in enumerate(parts):
        s0, e0 = part[0][0], part[-1][1]
        chunk = body[s0:e0]
        if n == 0:
            text = header + [extend_line] + prefix + chunk
            out = path
        else:
            head = [extend_line]
            lab = label_at(s0)
            if lab and not LABEL.match(chunk[0]):
                head.append(lab)
            text = head + chunk
            out = path.with_name(f"{path.stem}_part{n + 1}.elisa")
            if out.exists():
                fail(path, f"{out.name} already exists")
        while text and text[-1] == "":
            text.pop()
        outputs.append((out, text))

    # verify: concatenated member text is the original body, byte for byte
    rebuilt = prefix + [l for part in parts for s, e in part for l in body[s:e]]
    if rebuilt != body:
        fail(path, "verification failed")

    rel = path.relative_to(ROOT)
    includers = []
    for f in (ROOT / "src").rglob("*.elisa"):
        for k, l in enumerate(f.read_text().split("\n")):
            m = re.match(r'^(\s*)include "([^"]+)"\s*$', l)
            if m and (f.parent / m.group(2)).resolve() == path.resolve():
                includers.append((f, k, m.group(1), m.group(2)))
    if not includers:
        fail(path, "no includer found")
    if dry:
        return outputs, oversized
    for out, text in outputs:
        out.write_text("\n".join(text) + "\n")
    for f, k, indent, spelled in includers:
        flines = f.read_text().split("\n")
        base = spelled[: -len(path.name)]
        new = [f'{indent}include "{base}{out.name}"' for out, _ in outputs[1:]]
        flines[k + 1:k + 1] = new
        f.write_text("\n".join(flines))
    return outputs, oversized


if __name__ == "__main__":
    dry = "--dry" in sys.argv
    for arg in [a for a in sys.argv[1:] if a != "--dry"]:
        try:
            outs, big = split(Path(arg).resolve(), dry)
        except SystemExit as e:
            print(e)
            continue
        sizes = ", ".join(str(len(t)) for _, t in outs)
        note = f"; {len(big)} member(s) over limit" if big else ""
        print(f"{arg}: {len(outs)} parts ({sizes}){note}")
