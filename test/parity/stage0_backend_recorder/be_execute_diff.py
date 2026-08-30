#!/usr/bin/env python3
"""EXECUTION oracle over stage0's backend corpus.

The corpus is a LOWERING suite: 286 of its 287 sources have no `def main()`, so
stage0's own tests only ever check that IR is produced. Nothing runs them. That
leaves every construct in the corpus verified by shape, not by behaviour -- and a
miscompile that emits well-formed IR with the wrong semantics is invisible to the
strict replay, which counts a file covered whenever stage1 declines no function.

This harness closes that gap. For each corpus source it synthesises a driver:

    <original source>
    def main() -> i64:
        return <call to one zero-arg function, cast to i64>

then builds with BOTH compilers, links, runs, and compares exit codes. Same
observation channel as test/breadth/adversarial_differential.py -- the process
exit status -- because the corpus programs have no print facility.

One driver per function, not per file: an unsupported cast on one function then
costs only that function instead of poisoning every other function in the file.

Outcomes:
  MATCH      both built and ran, same exit code
  MISMATCH   both ran, DIFFERENT exit codes   <- silent wrong answer, the finding
  S1_FAIL    stage0 built+ran, stage1 could not build   <- a coverage gap
  SKIP       stage0 itself could not build+run it -- no oracle exists, not a result

SKIP is not a failure of stage1. Many corpus programs are not runnable at all
(they return refs into freed arenas, need effect handlers, or abort by design).
Only cases where stage0 produces a running binary can adjudicate anything.
"""
import base64, subprocess, sys, os, re, tempfile, pathlib, collections, json

S = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("REPO_ROOT", os.path.abspath(os.path.join(S, "..", "..", "..")))
S0 = os.environ.get("ELISACORE_BIN", os.path.abspath(os.path.join(
    REPO, "..", "..", "Go projects", "structpy-tree", "compiler", "bin", "elisac")))
WRAP = os.path.join(REPO, "scripts", "elisac_stage1.sh")
RT = os.path.join(REPO, "build", "runtime", "elisacore_runtime.o")
ORACLE = sys.argv[1] if len(sys.argv) > 1 else "/tmp/be_oracle.tsv"
ONLY = sys.argv[2] if len(sys.argv) > 2 else None

# Return types we know how to funnel into an i64 exit code. Anything else is not
# attempted -- a wrong cast would produce a bogus MISMATCH, which is far worse
# than a missed case.
INT_RETS = {"i64", "int", "i32", "u32", "usize", "u8", "u16", "i8", "i16", "isize", "u64"}


def driver_expr(ret):
    """The expression that reduces a call to `f()` to an i64, or None if we can't."""
    ret = ret.strip()
    if ret in INT_RETS:
        return "f_UT().i64()"
    if ret == "bool":
        return "1.i64() if f_UT() else 0.i64()"
    if ret == "char":
        return "f_UT().u8().i64()"
    return None


def run(cmd, **kw):
    return subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                          stdin=subprocess.DEVNULL, **kw)


def build_and_run(src_path, work, tag):
    """Returns (built_and_ran, exit_code). Mirrors adversarial_differential.py."""
    obj = os.path.join(work, f"{tag}.o")
    exe = os.path.join(work, tag)
    if tag == "s0":
        r = run([S0, "-emit", "obj", "-o", obj, src_path], timeout=90)
    elif tag == "s1O2":
        r = run(["bash", WRAP, "-O2", "-o", obj, src_path], timeout=180)
    else:
        r = run(["bash", WRAP, "-o", obj, src_path], timeout=90)
    if r.returncode != 0:
        return (False, None)
    for extra in ([RT], [], [RT, "-L/opt/homebrew/opt/llvm/lib", "-lLLVM"]):
        if run(["clang", "-Wl,-dead_strip", "-o", exe, obj] + extra).returncode == 0:
            break
    else:
        return (False, None)
    try:
        p = subprocess.run([exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           stdin=subprocess.DEVNULL, timeout=10)
        return (True, p.returncode)
    except subprocess.TimeoutExpired:
        return (False, None)


# Three argument tuples per function, so a function whose result does not vary with
# its input is still distinguishable. A single probe value would let a
# constant-returning miscompile read as a clean MATCH -- that is exactly how
# stage0's nested-or-pattern bug (always 24) stayed hidden until the input varied.
ARG_SETS = [
    {"int": ["7", "3", "11", "5"], "bool": ["true", "false", "true", "false"],
     "f64": ["2.5", "4.0", "1.5", "3.25"], "char": ["'a'", "'b'", "'c'", "'d'"]},
    {"int": ["23", "19", "2", "31"], "bool": ["false", "true", "false", "true"],
     "f64": ["8.75", "0.5", "6.0", "2.0"], "char": ["'x'", "'y'", "'z'", "'w'"]},
    {"int": ["101", "53", "97", "13"], "bool": ["true", "true", "false", "false"],
     "f64": ["12.5", "3.5", "9.25", "7.0"], "char": ["'m'", "'n'", "'p'", "'q'"]},
]
INT_PARAMS = INT_RETS
WEIGHTS = [1, 3, 7]


def arg_literal(ty, which, pos):
    """A literal of type `ty` from tuple `which` at parameter position `pos`.

    Values are all non-zero so a function that divides or takes a modulo of a
    parameter does not trap on one compiler's build and not the other's."""
    bank = ARG_SETS[which]
    slot = pos % 4
    if ty in INT_PARAMS:
        return bank["int"][slot]
    if ty == "bool":
        return bank["bool"][slot]
    if ty in ("f64", "f32"):
        return bank["f64"][slot]
    if ty == "char":
        return bank["char"][slot]
    return None


def param_types(args):
    """Parsed parameter types, or None if any parameter is not a plain scalar."""
    if not args.strip():
        return []
    out = []
    for a in args.split(","):
        if ":" not in a:
            return None
        t = a.split(":", 1)[1].strip()
        if t not in INT_PARAMS and t not in ("bool", "f64", "f32", "char"):
            return None
        out.append(t)
    return out


def candidates(src):
    """Functions we can both call and observe.

    Zero-arg, or every parameter a plain scalar we can synthesise a literal for.
    `error[...]` / `can[...]` returns need a handler at the call site, so calling
    them from a bare main would change what is being tested."""
    out = []
    for m in re.finditer(r'^def (\w+)\(([^)]*)\)\s*->\s*([^:\n]+):', src, re.M):
        name, args, ret = m.group(1), m.group(2), m.group(3).strip()
        if "error[" in ret or "can[" in ret or "&" in ret:
            continue
        if not driver_expr(ret):
            continue
        tys = param_types(args)
        if tys is None:
            continue
        calls = []
        for which in range(len(ARG_SETS)):
            lits = [arg_literal(t, which, i) for i, t in enumerate(tys)]
            if any(l is None for l in lits):
                calls = []
                break
            calls.append(f"{name}({', '.join(lits)})")
            if not tys:
                break  # zero-arg: one call is all there is
        if calls:
            out.append((name, ret, calls))
    return out


def main():
    rows = {}
    for line in open(ORACLE):
        p = line.rstrip("\n").split("\t")
        if len(p) < 5 or int(p[1]) != 1:
            continue
        rows.setdefault((int(p[2]), base64.b64decode(p[3]).decode()),
                        base64.b64decode(p[0]).decode())

    work = tempfile.mkdtemp()
    res = collections.Counter()
    mismatches, s1fails = [], []
    total_fn = 0

    items = sorted(rows.items(), key=lambda kv: kv[1])
    for (opt, src), fname in items:
        if ONLY and ONLY not in fname:
            continue
        if re.search(r'^def main\(', src, re.M):
            res["has_own_main"] += 1
            continue
        for name, ret, calls in candidates(src):
            total_fn += 1
            # Weight each call differently so a permutation of the results -- not just
            # a change in their sum -- still moves the exit code.
            terms = []
            for i, c in enumerate(calls):
                terms.append(f"({driver_expr(ret).replace('f_UT()', c)}) * {WEIGHTS[i]}.i64()")
            prog = src + ("\n\ndef main() -> i64:\n    return ("
                          + " + ".join(terms) + ") % 251.i64()\n")
            f = os.path.join(work, "case.elisa")
            pathlib.Path(f).write_text(prog)

            ok0, rc0 = build_and_run(f, work, "s0")
            if not ok0:
                res["SKIP"] += 1
                continue
            ok1, rc1 = build_and_run(f, work, "s1")
            if not ok1:
                res["S1_FAIL"] += 1
                s1fails.append(f"{fname}::{name} -> {ret}")
                continue
            if rc0 != rc1:
                res["MISMATCH"] += 1
                mismatches.append(f"{fname}::{name} -> {ret}  stage0={rc0} stage1={rc1}")
            else:
                res["MATCH"] += 1
        if total_fn and total_fn % 25 == 0:
            print(f"  ...{total_fn} fns  match={res['MATCH']} mism={res['MISMATCH']} "
                  f"s1fail={res['S1_FAIL']} skip={res['SKIP']}", file=sys.stderr)

    print(f"\n=== EXECUTION DIFF: {total_fn} candidate functions from {len(rows)} sources ===")
    print(f"  MATCH    {res['MATCH']}")
    print(f"  MISMATCH {res['MISMATCH']}   <- silent wrong answers")
    print(f"  S1_FAIL  {res['S1_FAIL']}    <- stage0 ran it, stage1 could not build it")
    print(f"  SKIP     {res['SKIP']}       <- stage0 could not build+run; no oracle")
    for m in mismatches:
        print(f"  MISMATCH {m}")
    for m in s1fails[:30]:
        print(f"  S1_FAIL  {m}")
    json.dump({"match": res["MATCH"], "mismatch": res["MISMATCH"],
               "s1_fail": res["S1_FAIL"], "skip": res["SKIP"],
               "mismatches": mismatches, "s1_fails": s1fails},
              open(os.path.join(S, "execute_result.json"), "w"), indent=1)
    return 1 if res["MISMATCH"] else 0


if __name__ == "__main__":
    sys.exit(main())
