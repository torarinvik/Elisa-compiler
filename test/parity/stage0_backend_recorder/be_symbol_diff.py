#!/usr/bin/env python3
"""SYMBOL oracle: do both compilers export the SAME symbols?

The two existing harnesses cannot see a missing symbol:

  * the strict census counts a file covered when stage1 declines no function — a function
    never ATTEMPTED declines nothing, so the census reports success;
  * the execution oracle runs the program, and a corpus program never links against a C
    caller, so an unreferenced missing export is never touched.

That blind spot hid `export fn vec2i_add(...) = vec_add_i32` producing no symbol at all:
stage0's object exported _ctx_seed/_vec2i_add/_vec2i_keep_left, stage1's exported only the
first, and the census called the file covered.

This compiles each corpus source with BOTH compilers AT -O0 and diffs the exported
(external, defined) symbol sets from `nm -gU`.

The matched -O0 matters: stage0's `-emit obj` defaults to -O3, stage1's to -O0, and at -O3
stage0 internalizes and strips unreferenced functions. Comparing the two DEFAULTS reports
269 of 277 files as divergent, which is an artifact of the level rather than a difference
in what the compilers export.

Outcomes:
  MATCH        identical exported symbol sets
  MISSING      stage0 exports symbols stage1 does not   <- the finding
  EXTRA        stage1 exports symbols stage0 does not   <- also a divergence
  SKIP         one of the two could not produce an object; no comparison is possible

SKIP is not a stage1 failure. Many corpus files are rejected by stage0's own CLI (internal
carrier types), and nothing can be compared when only one side produced an object.
"""
import base64, collections, json, os, pathlib, re, subprocess, sys, tempfile

S = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("REPO_ROOT", os.path.abspath(os.path.join(S, "..", "..", "..")))
S0 = os.environ.get("ELISACORE_BIN", os.path.abspath(os.path.join(
    REPO, "..", "..", "Go projects", "structpy-tree", "compiler", "bin", "elisac")))
WRAP = os.path.join(REPO, "scripts", "elisac_stage1.sh")
ORACLE = sys.argv[1] if len(sys.argv) > 1 else "/tmp/be_oracle.tsv"
ONLY = sys.argv[2] if len(sys.argv) > 2 else None


def run(cmd, **kw):
    return subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                          stdin=subprocess.DEVNULL, **kw)


def exported_symbols(obj_path):
    """External DEFINED symbols, as `nm -gU` reports them. None when nm fails."""
    try:
        proc = subprocess.run(["nm", "-gU", obj_path], capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        return None
    if proc.returncode != 0:
        return None
    names = set()
    for line in proc.stdout.splitlines():
        parts = line.split()
        # "<addr> <type> <name>" for a defined symbol.
        if len(parts) >= 3:
            names.add(parts[-1])
    return names


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
    missing_report, extra_report = [], []

    for (opt, src), fname in sorted(rows.items(), key=lambda kv: kv[1]):
        if ONLY and ONLY not in fname:
            continue
        source = os.path.join(work, "case.elisa")
        pathlib.Path(source).write_text(src)
        s0_obj = os.path.join(work, "s0.o")
        s1_obj = os.path.join(work, "s1.o")
        for path in (s0_obj, s1_obj):
            if os.path.exists(path):
                os.remove(path)

        # -O0 ON BOTH SIDES. stage0's `-emit obj` DEFAULTS TO -O3, stage1's to -O0, and at
        # -O3 stage0's optimizer internalizes and strips unreferenced functions. Comparing
        # the two defaults reported 269 of 277 files as divergent — an artifact of the
        # mismatched level, not a finding. Matching the level is what makes the comparison
        # mean anything.
        if run([S0, "-O0", "-emit", "obj", "-o", s0_obj, source], timeout=90).returncode != 0:
            res["SKIP"] += 1
            continue
        if run(["bash", WRAP, "-O0", "-o", s1_obj, source], cwd=REPO, timeout=120).returncode != 0:
            res["SKIP"] += 1
            continue

        s0_syms = exported_symbols(s0_obj)
        s1_syms = exported_symbols(s1_obj)
        if s0_syms is None or s1_syms is None:
            res["SKIP"] += 1
            continue

        missing = sorted(s0_syms - s1_syms)
        extra = sorted(s1_syms - s0_syms)
        if missing:
            res["MISSING"] += 1
            missing_report.append(f"{fname}: {', '.join(missing[:6])}")
        if extra:
            res["EXTRA"] += 1
            extra_report.append(f"{fname}: {', '.join(extra[:6])}")
        if not missing and not extra:
            res["MATCH"] += 1

    print(f"\n=== SYMBOL DIFF: {res['MATCH'] + res['MISSING'] + res['EXTRA']} comparable of {len(rows)} sources ===")
    print(f"  MATCH   {res['MATCH']}")
    print(f"  MISSING {res['MISSING']}   <- stage0 exports it, stage1 does not")
    print(f"  EXTRA   {res['EXTRA']}     <- stage1 exports it, stage0 does not")
    print(f"  SKIP    {res['SKIP']}      <- one side produced no object; nothing to compare")
    for entry in missing_report[:25]:
        print(f"  MISSING {entry}")
    for entry in extra_report[:25]:
        print(f"  EXTRA   {entry}")
    json.dump({"match": res["MATCH"], "missing": res["MISSING"], "extra": res["EXTRA"],
               "skip": res["SKIP"], "missing_files": missing_report, "extra_files": extra_report},
              open(os.path.join(S, "symbol_result.json"), "w"), indent=1)
    return 1 if res["MISSING"] else 0


if __name__ == "__main__":
    sys.exit(main())
