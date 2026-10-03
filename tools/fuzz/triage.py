#!/usr/bin/env python3
"""Summarise a fuzz output dir: throughput, verdict mix, and deduped findings per class.

  triage.py OUT_DIR [--show CLASS]    (--show prints each representative program of CLASS)
"""
import collections, json, os, sys


def main():
    out = sys.argv[1]
    show = sys.argv[sys.argv.index("--show") + 1] if "--show" in sys.argv else None
    n = 0; secs = 0.0; mix = collections.Counter(); cls = collections.Counter()
    first = last = None
    try:
        with open(os.path.join(out, "results.jsonl")) as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                n += 1; secs += r.get("t", 0)
                mix[(r["s0"], r["s1"])] += 1
                if r.get("cls"):
                    cls[r["cls"]] += 1
    except FileNotFoundError:
        pass
    print("programs: %d  (mean %.1fs each)" % (n, secs / n if n else 0))
    print("verdicts (s0, s1):", ", ".join("%s/%s=%d" % (a, b, c) for (a, b), c in mix.most_common(8)))
    root = os.path.join(out, "findings")
    for c in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        sigs = sorted(os.listdir(os.path.join(root, c)))
        print("\n== %s: %d hits, %d distinct" % (c, cls[c], len(sigs)))
        rows = []
        for s in sigs:
            d = os.path.join(root, c, s)
            info = json.load(open(os.path.join(d, "info.json")))
            hits = 1 + len(open(os.path.join(d, "count")).read()) if os.path.exists(os.path.join(d, "count")) else 1
            rows.append((hits, s, info))
        for hits, s, info in sorted(rows, key=lambda x: -x[0])[:25]:
            print("  %4d  %s  seed=%s ops=%s exec=%s" % (hits, s, info["seed"], ",".join(info["ops"]), info.get("exec") or "-"))
            print("        s0[%s] %s" % (info["s0"], info["s0_msg"][:110]))
            print("        s1[%s] %s" % (info["s1"], info["s1_msg"][:110]))
            if show == c:
                p = os.path.join(root, c, s, "min.elisa")
                p = p if os.path.exists(p) else os.path.join(root, c, s, "prog.elisa")
                print("".join("        | " + l for l in open(p).readlines()))


if __name__ == "__main__":
    main()
