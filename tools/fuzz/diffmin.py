#!/usr/bin/env python3
"""Line-level delta minimizer for a difffuzz MISMATCH: keeps "stage0 and stage1 both build and
run the program, and their (exit code, stdout) differ".

  diffmin.py --s0 ELISAC --s1 ELISAC_STAGE1 --rt RUNTIME.o --hooks profile_hooks.c PROG.elisa [OUT]
  --mode permissive : keep "stage0 rejects, stage1 -O0 builds" instead.
In permissive mode it also tries replacing each integer literal with 0/1 after the line pass.
(Not in mismatch mode: a literal rewrite can turn the generator's `% 7 + 8` divisor into a
division by zero, and an undefined program "mismatches" for free.)
"""
import argparse, os, re, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import difffuzz
import gen_progs


def main():
    ap = argparse.ArgumentParser()
    for k in ("s0", "s1", "rt", "hooks"):
        ap.add_argument("--" + k, required=True)
    ap.add_argument("--mode", default="mismatch", choices=["mismatch", "permissive"])
    ap.add_argument("prog"); ap.add_argument("out", nargs="?")
    a = ap.parse_args()
    difffuzz.A = a
    wd = tempfile.mkdtemp(prefix="dmin.")

    def bad(lines):
        p = os.path.join(wd, "m.elisa")
        open(p, "w").write("\n".join(lines) + "\n")
        r0 = difffuzz.build_run("s0", p, wd)
        if a.mode == "permissive":
            return r0["verdict"] == "reject" and difffuzz.build_run("s1", p, wd)["verdict"] == "ok"
        if r0["verdict"] != "ok" or r0["rc"] == "timeout" or (isinstance(r0["rc"], int) and r0["rc"] < 0):
            return False
        r1 = difffuzz.build_run("s1", p, wd)
        if r1["verdict"] != "ok" or r1["rc"] == "timeout":
            return False
        return (r0["rc"], r0["out"]) != (r1["rc"], r1["out"])

    text = open(a.prog).read()
    # The generator's printing prelude is never a suspect: deleting `digits.push(0)` from `pr`
    # turns every printed 0 into an empty line, which still "mismatches" and sends triage after
    # a bug that is not there. Keep it fixed and minimize the rest.
    fixed = []
    if text.startswith(gen_progs.PRELUDE):
        fixed = gen_progs.PRELUDE.rstrip("\n").split("\n")
        text = text[len(gen_progs.PRELUDE):]
    lines = text.strip("\n").split("\n")
    bad_rest = bad
    bad = lambda rest: bad_rest(fixed + rest)
    if not bad(lines):
        print("not reproducible"); return 1
    chunk = max(1, len(lines) // 2)
    while chunk >= 1:
        i, changed = 0, False
        while i < len(lines):
            cand = lines[:i] + lines[i + chunk:]
            if cand and bad(cand):
                lines, changed = cand, True
            else:
                i += chunk
        if not changed:
            chunk //= 2
    for i in range(len(lines) if a.mode == "permissive" else 0):
        for m in list(re.finditer(r"(?<![\w.])\d+(?![\w.])", lines[i]))[::-1]:
            for rep in ("0", "1"):
                if m.group(0) == rep:
                    continue
                cand = list(lines)
                cand[i] = cand[i][:m.start()] + rep + cand[i][m.end():]
                if bad(cand):
                    lines = cand
                    break
    text = "\n".join(fixed + lines) + "\n"
    if a.out:
        open(a.out, "w").write(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
