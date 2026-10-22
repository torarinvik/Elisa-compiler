#!/usr/bin/env python3
"""Move the tail arms of an oversized `handled`-style match function into a new function.

Shape required (the diagnostic_message family):

    def f(<params>, handled: mutable bool&) -> void:
        can ...:
            handled <- true
            match <scrutinee>:
                <arms>
                _:
                    handled <- false

Arms from the first one past the cut move, unchanged and at unchanged indentation, into
`def <new_name>(<same params>)` in <new_file> (an `extend` part placed directly after
the source file in include order). The source's `_:` arm then delegates to it.

usage: split_match_arms.py FILE FUNCTION NEW_NAME NEW_FILE [KEEP_LINES]
"""
import re
import sys
from pathlib import Path


def indent(l):
    return len(l) - len(l.lstrip(" "))


def main():
    path, fn, new_name, new_file = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4])
    keep = int(sys.argv[5]) if len(sys.argv) > 5 else 560
    L = path.read_text().split("\n")
    d = next(i for i, l in enumerate(L) if re.match(rf"\s*def {re.escape(fn)}\(", l))
    di = indent(L[d])
    end = next((i for i in range(d + 1, len(L)) if L[i].strip() and indent(L[i]) <= di), len(L))
    while L[end - 1].strip() == "" or (indent(L[end - 1]) == di and L[end - 1].lstrip().startswith("#")):
        end -= 1
    m = next(i for i in range(d, end) if re.match(r"\s*match .*:\s*$", L[i]))
    ai = indent(L[m]) + 4
    arms = [i for i in range(m + 1, end) if L[i].strip() and indent(L[i]) == ai and not L[i].lstrip().startswith("#")]
    # walk each arm start back over its comment lead
    starts = []
    for a in arms:
        j = a
        while j - 1 > m and L[j - 1].strip() and indent(L[j - 1]) == ai and L[j - 1].lstrip().startswith("#"):
            j -= 1
        starts.append(j)
    if L[arms[-1]].strip() != "_:" or L[arms[-1] + 1].strip() != "handled <- false" or arms[-1] + 2 < end and any(l.strip() for l in L[arms[-1] + 2:end]):
        raise SystemExit("last arm is not `_: handled <- false`")
    wild = starts[-1]
    cut = next((s for s in starts if s - d > keep), None)
    if cut is None or cut >= wild:
        raise SystemExit("nothing to move")
    moved = L[cut:wild]
    header = L[d:m + 1]
    sig = header[0]
    new_sig = re.sub(rf"def {re.escape(fn)}\(", f"def {new_name}(", sig, count=1)
    params = re.search(r"\((.*)\)\s*->", sig).group(1)
    names = [p.split(":")[0].strip() for p in re.split(r",\s*(?![^\[\(]*[\]\)])", params)]
    call = f"{new_name}({', '.join(names)})"
    # file header: the extend line and visibility label in force at the function
    ext = next(l for l in reversed(L[:d]) if re.match(r"^(extend|module) ", l))
    ext = re.sub(r"^module ", "extend ", ext)
    lab = next((l for l in reversed(L[:d]) if re.match(r"^    (public|private):\s*$", l)), None)
    body = [ext] + ([lab] if lab else []) + [new_sig] + header[1:] + moved + L[wild:end]
    if new_file.exists():
        raise SystemExit(f"{new_file} exists")
    new_file.write_text("\n".join(body) + "\n")
    L[cut:end] = [" " * ai + "_:", " " * (ai + 4) + call]
    path.write_text("\n".join(L))
    # include the new file right after the source everywhere the source is included
    rel = Path(__import__("os").path.relpath(new_file, path.parent))
    for f in Path("src").rglob("*.elisa"):
        lines = f.read_text().split("\n")
        hit = False
        for k in range(len(lines) - 1, -1, -1):
            mm = re.match(r'^(\s*)include "([^"]+)"\s*$', lines[k])
            if mm and (f.parent / mm.group(2)).resolve() == path.resolve():
                target = __import__("os").path.relpath(new_file.resolve(), f.parent.resolve())
                lines.insert(k + 1, f'{mm.group(1)}include "./{target}"')
                hit = True
        if hit:
            f.write_text("\n".join(lines))
    print(f"{path}: moved {len(moved)} lines into {new_name} ({new_file})")


main()
