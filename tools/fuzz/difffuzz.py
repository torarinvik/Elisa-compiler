#!/usr/bin/env python3
"""Runtime differential driver for gen_progs.py programs: stage0 vs stage1 (-O0 and -O2).

For each generated seed:
  s0   : stage0 `-emit obj` (its default -O3), linked with the stage1 runtime object
  s1   : stage1 `-O0`, s1O2 : stage1 `-O2`
Every product is run; stdout + exit code are compared. Classes:
  MATCH, MISMATCH (both accept, different output: a miscompile somewhere),
  PERMISSIVE (stage0 rejects, stage1 accepts), S1_REJECT (stage0 accepts, stage1 rejects),
  BOTH_REJECT (usually a generator bug: inspect the diagnostics), CRASH (a compiler signal),
  RUN_TIMEOUT.
Anything but MATCH is copied to <out>/<class>/p<seed>/ with the source, diagnostics and outputs.

  difffuzz.py --s0 ELISAC --s1 ELISAC_STAGE1 --rt RUNTIME.o --hooks profile_hooks.c \
               --out DIR --start N --count K [--jobs J]
Needs the Linux environment of tools/remote (clang shim first on PATH, ELISA_HOST_LINUX=1 ...).
Default --jobs is (nproc - loadavg) / 2, so a shared box keeps half its idle cores.
"""
import argparse, collections, json, multiprocessing as mp, os, shutil, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gen_progs

A = None


def sh(cmd, timeout):
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                           timeout=timeout)
        return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        return "timeout", "", ""


def build_run(tag, src, work):
    obj, exe = os.path.join(work, tag + ".o"), os.path.join(work, tag)
    if tag == "s0":
        cmd = [A.s0, "-emit", "obj", "-o", obj, src]
    else:
        cmd = [A.s1, "-O2" if tag == "s1O2" else "-O0", "-o", obj, src]
    rc, out, err = sh(cmd, 300)
    diag = out + err
    if rc != 0:
        return {"verdict": "reject" if isinstance(rc, int) and 0 < rc < 128 else f"crash:{rc}", "diag": diag}
    rc, o2, e2 = sh(["clang", "-o", exe, obj, A.rt, A.hooks], 120)
    if rc != 0:
        return {"verdict": "link", "diag": diag + o2 + e2}
    rc, out, err = sh([exe], 20)
    return {"verdict": "ok", "diag": diag, "rc": rc, "out": out}


def one(seed):
    work = tempfile.mkdtemp(prefix=f"p{seed}-", dir=A.tmp)
    src = os.path.join(work, f"p{seed}.elisa")
    open(src, "w").write(gen_progs.generate(seed))
    res = {t: build_run(t, src, work) for t in ("s0", "s1", "s1O2")}
    v = {t: r["verdict"] for t, r in res.items()}
    if any(x.startswith("crash") for x in v.values()):
        cls = "CRASH"
    elif v["s0"] == "ok" and v["s1"] == "ok" and v["s1O2"] == "ok":
        outs = {(res[t]["rc"], res[t]["out"]) for t in res}
        if any(res[t]["rc"] == "timeout" for t in res):
            cls = "RUN_TIMEOUT"
        else:
            cls = "MATCH" if len(outs) == 1 else "MISMATCH"
    elif v["s0"] == "reject" and "ok" in (v["s1"], v["s1O2"]):
        cls = "PERMISSIVE"
    elif v["s0"] == "ok" and v["s1"] != "ok":
        cls = "S1_REJECT"
    elif v["s0"] != "ok" and v["s1"] != "ok":
        cls = "BOTH_REJECT"
    else:
        cls = "OTHER"
    if cls != "MATCH":
        d = os.path.join(A.out, cls, f"p{seed}")
        os.makedirs(d, exist_ok=True)
        shutil.copy(src, d)
        json.dump(res, open(os.path.join(d, "result.json"), "w"), indent=1)
    shutil.rmtree(work, ignore_errors=True)
    return seed, cls


def main():
    global A
    ap = argparse.ArgumentParser()
    for k in ("s0", "s1", "rt", "hooks", "out"):
        ap.add_argument("--" + k, required=True)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--count", type=int, default=100)
    ap.add_argument("--jobs", type=int, default=0)
    A = ap.parse_args()
    A.tmp = os.path.join(A.out, "tmp")
    os.makedirs(A.tmp, exist_ok=True)
    jobs = A.jobs or max(1, int((os.cpu_count() - os.getloadavg()[0]) / 2))
    counts = collections.Counter()
    with mp.Pool(jobs) as pool, open(os.path.join(A.out, "results.tsv"), "a") as log:
        for seed, cls in pool.imap_unordered(one, range(A.start, A.start + A.count)):
            counts[cls] += 1
            log.write(f"{seed}\t{cls}\n"); log.flush()
    print(dict(counts))


if __name__ == "__main__":
    main()
