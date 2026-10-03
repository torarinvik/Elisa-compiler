#!/usr/bin/env python3
"""Line-level delta minimizer for a fuzz finding: keeps the finding's class and signature.

  minimize.py --s0 ELISAC --s1 ELISAC_STAGE1 --guard guard.so FINDING_DIR
Reads FINDING_DIR/prog.elisa + info.json, writes FINDING_DIR/min.elisa.
Removes chunks of lines (halving), then single lines, re-evaluating with fuzz.evaluate.
"""
import argparse, json, os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fuzz


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--s0", required=True); ap.add_argument("--s1", required=True)
    ap.add_argument("--guard", required=True); ap.add_argument("finding")
    a = ap.parse_args()
    info = json.load(open(os.path.join(a.finding, "info.json")))
    cfg = {"s0": a.s0, "s1": a.s1, "guard": os.path.abspath(a.guard), "ctimeout": 60, "rtimeout": 5,
           "cc": os.environ.get("ELISA_CLANG", "clang"), "runtime": os.environ["ELISA_RUNTIME_OBJ"],
           "fallback": os.path.join(os.path.dirname(os.path.abspath(__file__)), "callback_fallback.c")}
    wd = tempfile.mkdtemp(prefix="min.")

    def same(lines):
        p = os.path.join(wd, "m.elisa")
        open(p, "w").write("\n".join(lines))
        r = fuzz.evaluate(cfg, p, wd)
        cls, an = fuzz.classify(r)
        return cls == info["cls"] and fuzz.signature(cls, r, an)[0] == info["sig"]

    lines = open(os.path.join(a.finding, "prog.elisa")).read().split("\n")
    if not same(lines):
        print("not reproducible; leaving as is"); return 1
    chunk = max(1, len(lines) // 2)
    while chunk >= 1:
        i = 0; changed = False
        while i < len(lines):
            cand = lines[:i] + lines[i + chunk:]
            if cand and same(cand):
                lines = cand; changed = True
            else:
                i += chunk
        if not changed:
            chunk //= 2
    open(os.path.join(a.finding, "min.elisa"), "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
