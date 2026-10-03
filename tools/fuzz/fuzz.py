#!/usr/bin/env python3
"""Differential mutation fuzzer: stage0 (oracle) vs stage1, plus execution of stage1 products.

For each mutant program:
  * stage0 verdict: `-emit obj`, and `-emit obj -Wstrict`; a reject in EITHER counts as reject;
  * stage1 verdict: `-emit obj` (a "declined" message is a backend decline, not a verdict);
  * when stage1 accepts: build `-emit exe` at -O0 and -O2 and run each with and without the
    munmap guard (guard.so, LD_PRELOAD). Any signal, timeout or exit-code disagreement among
    the four runs is an execution anomaly.
Classes (see classify()): s1_hole[_exec], s1_overstrict, s1_decline, s1_crash, s0_crash,
exec_anomaly (both accept, product misbehaves). Findings are deduped on a signature built
from the class and normalised first diagnostics; one representative per signature is kept
under <out>/findings/<class>/<sig>/ and every result is appended to <out>/results.jsonl.

Seeds: every *.elisa under the given seed dirs that defines `def main` (the .neg/.pos
fixtures and test/fuzz_findings). Mutation operators are line-level and indentation-aware;
`pad` inserts an allocation after an owner declaration (fixture rule: the arena tail grows
in place and hides stale reads unless something is allocated after the owner).

  fuzz.py --s0 ELISAC --s1 ELISAC_STAGE1 --guard guard.so --out DIR [--jobs N] [--iters N] SEEDDIR...
Environment for stage1 (ELISA_RUNTIME_OBJ, ELISA_CLANG, PATH with the clang shim) is inherited.
"""
import argparse, fcntl, hashlib, json, multiprocessing as mp, os, random, re, shutil, signal, subprocess, sys, tempfile, time

GROW_OPS = ["{x}.push({n})", "{x}.push({n})\n{ind}{x}.push({n})", "{x}.clear()", "{x} <- [{n}, {n}]",
            "{x}.extend([{n}, {n}, {n}])"]
PAD = "pad{k}: mutable darray[i64] = [{n}, {n}, {n}, {n}]"


def load_seeds(dirs):
    seeds = []
    for d in dirs:
        for root, _, files in os.walk(d):
            for f in files:
                if f.endswith(".elisa"):
                    p = os.path.join(root, f)
                    try:
                        s = open(p, encoding="utf-8").read()
                    except (OSError, UnicodeDecodeError):
                        continue
                    if "def main" in s and len(s) < 6000 and "include " not in s:
                        seeds.append((p, s))
    return seeds


def indent_of(line):
    return len(line) - len(line.lstrip(" "))


def body_lines(lines):
    """Indices of statement lines inside function bodies (indented, not comments/blank)."""
    return [i for i, l in enumerate(lines) if l.strip() and indent_of(l) >= 4 and not l.strip().startswith("#")]


DECL_RE = re.compile(r"^\s*(\w+)\s*:\s*(mutable\s+)?(darray\[[^\]]+\]|dstr)\b")
NAME_RE = re.compile(r"\b[a-z_]\w*\b")
INT_RE = re.compile(r"\b\d+\b")


def mutate(src, rng, donors):
    lines = src.split("\n")
    body = body_lines(lines)
    if not body:
        return src, "none"
    op = rng.choice(["swap", "dup", "delete", "int", "grow", "grow", "pad", "splice", "region", "loop",
                     "ident", "move", "ref", "pad"])
    i = rng.choice(body)
    ind = " " * indent_of(lines[i])
    owners = [m.group(1) for m in (DECL_RE.match(l) for l in lines) if m and m.group(2)]
    if op == "swap":
        j = i + 1
        if j < len(lines) and indent_of(lines[j]) == indent_of(lines[i]) and lines[j].strip():
            lines[i], lines[j] = lines[j], lines[i]
    elif op == "dup":
        lines.insert(i + 1, lines[i])
    elif op == "delete":
        if not lines[i].rstrip().endswith(":"):
            del lines[i]
    elif op == "int":
        lines[i] = INT_RE.sub(lambda m: str(rng.choice([0, 1, 2, 7, 41, 65, 255, 4096])) if rng.random() < .5 else m.group(0), lines[i])
    elif op == "grow" and owners:
        x = rng.choice(owners); n = rng.choice([1, 9, 66])
        stmt = rng.choice(GROW_OPS).format(x=x, n=n, ind=ind)
        if not lines[i].rstrip().endswith(":"):
            lines.insert(i + 1, ind + stmt)
    elif op == "pad":
        decl = [k for k in body if DECL_RE.match(lines[k])]
        if decl:
            k = rng.choice(decl)
            lines.insert(k + 1, " " * indent_of(lines[k]) + PAD.format(k=rng.randrange(1000), n=rng.choice([7, 13])))
    elif op == "splice" and donors:
        dl = donors[rng.randrange(len(donors))][1].split("\n")
        cand = [l for l in (dl[k] for k in body_lines(dl)) if not l.rstrip().endswith(":")]
        if cand and not lines[i].rstrip().endswith(":"):
            lines.insert(i + 1, ind + rng.choice(cand).strip())
    elif op in ("region", "loop") and not lines[i].rstrip().endswith(":"):
        head = "region rz%d(4096):" % rng.randrange(100) if op == "region" else "for zk in 0..<%d:" % rng.choice([1, 2, 3])
        lines[i:i + 1] = [ind + head, ind + "    " + lines[i].strip()]
    elif op == "ident":
        names = sorted(set(NAME_RE.findall("\n".join(lines[k] for k in body))) - {"mutable", "return", "for", "in", "if", "else", "def", "while", "and", "or", "not", "move", "region"})
        here = NAME_RE.findall(lines[i])
        if names and here:
            a = rng.choice(here); b = rng.choice(names)
            lines[i] = re.sub(r"\b%s\b" % re.escape(a), b, lines[i], count=1)
    elif op == "move" and owners:
        x = rng.choice(owners)
        lines[i] = re.sub(r"(?<![\w.&])%s\b(?!\s*[:<.\[])" % re.escape(x), "move " + x, lines[i], count=1)
    elif op == "ref" and owners:
        x = rng.choice(owners)
        if not lines[i].rstrip().endswith(":"):
            lines.insert(i + 1, ind + "rr%d: i64& = &%s[0]" % (rng.randrange(100), x))
    return "\n".join(lines), op


def run(cmd, timeout, env=None, cwd=None):
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout, env=env, cwd=cwd)
        return p.returncode, p.stdout.decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        return "timeout", ""


def first_error(text):
    lines = [l.strip() for l in text.splitlines() if l.strip() and "warning:" not in l]
    for l in lines:
        if ".elisa:" in l or "error" in l.lower() or "panic" in l.lower() or "declined" in l:
            return l
    return lines[0] if lines else ""


def norm(msg):
    msg = re.sub(r"^.*?\.elisa:\d+(:\d+)?:?\s*", "", msg)
    msg = re.sub(r"'[^']*'|`[^`]*`|\"[^\"]*\"", "Q", msg)
    msg = re.sub(r"\b\d+\b", "N", msg)
    return msg[:120]


def compile_verdict(rc, out, obj):
    if rc == "timeout":
        return "timeout"
    if isinstance(rc, int) and (rc < 0 or rc >= 128 or "panic:" in out or "goroutine " in out):
        return "crash"
    if rc == 0 and os.path.exists(obj) and os.path.getsize(obj) > 0:
        return "accept"
    if "declined" in out:
        return "decline"
    return "reject"


def evaluate(cfg, path, wd):
    r = {}
    obj = os.path.join(wd, "s0.o")
    rc, out = run([cfg["s0"], "-emit", "obj", "-o", obj, path], cfg["ctimeout"], cwd=wd)
    r["s0"] = compile_verdict(rc, out, obj); r["s0_msg"] = first_error(out)
    if r["s0"] == "accept":
        obj2 = os.path.join(wd, "s0s.o")
        rc, out = run([cfg["s0"], "-Wstrict", "-emit", "obj", "-o", obj2, path], cfg["ctimeout"], cwd=wd)
        v = compile_verdict(rc, out, obj2)
        if v != "accept":
            r["s0"] = "strict_" + v; r["s0_msg"] = first_error(out)
    obj = os.path.join(wd, "s1.o")
    rc, out = run([cfg["s1"], "-emit", "obj", "-o", obj, path], cfg["ctimeout"], cwd=wd)
    r["s1"] = compile_verdict(rc, out, obj); r["s1_msg"] = first_error(out)
    r["exec"] = {}
    if r["s1"] == "accept":
        for opt in ("-O0", "-O2"):
            # Not `-emit exe`: stage1's link step writes its callback-fallback .c with macOS
            # open() flags (1537 = O_WRONLY|O_CREAT|O_TRUNC on Darwin, no O_CREAT on Linux), so
            # it exits 8 on Linux. Emit the object and link it the same way ourselves.
            exe = os.path.join(wd, "p" + opt); o = exe + ".o"
            rc, out = run([cfg["s1"], "-emit", "obj", opt, "-o", o, path], cfg["ctimeout"], cwd=wd)
            if rc == 0:
                rc, out = run([cfg["cc"], "-fno-builtin", "-Wl,-dead_strip", "-o", exe, o, cfg["runtime"],
                               cfg["fallback"]], cfg["ctimeout"], cwd=wd)
            if rc != 0 or not os.path.exists(exe):
                r["exec"][opt] = "build_fail"
                continue
            for g in ("plain", "guard"):
                env = dict(os.environ)
                if g == "guard":
                    env["LD_PRELOAD"] = cfg["guard"]
                rc, _ = run([exe], cfg["rtimeout"], env=env, cwd=wd)
                r["exec"][opt + "/" + g] = rc
    return r


def exec_anomaly(ex):
    vals = list(ex.values())
    if not vals:
        return ""
    bad = [k for k, v in ex.items() if v == "timeout" or v == "build_fail" or (isinstance(v, int) and v < 0)]
    if bad:
        return "fault:" + ",".join(sorted(bad))
    if len(set(vals)) > 1:
        return "diverge"
    return ""


def classify(r):
    s0, s1 = r["s0"], r["s1"]
    an = exec_anomaly(r["exec"])
    if s1 in ("crash", "timeout"):
        return "s1_crash", an
    if s0 in ("crash", "timeout", "strict_crash"):
        return "s0_crash", an
    s0_acc = s0 == "accept"
    if s1 == "accept" and not s0_acc:
        return ("s1_hole_exec" if an else "s1_hole"), an
    if s1 == "decline" and s0_acc:
        return "s1_decline", an
    if s1 == "reject" and s0_acc:
        return "s1_overstrict", an
    if s1 == "accept" and s0_acc and an:
        return "exec_anomaly", an
    return "", an


def signature(cls, r, an):
    key = "|".join([cls, norm(r.get("s0_msg", "")), norm(r.get("s1_msg", "")), an.split(":")[0]])
    return hashlib.sha1(key.encode()).hexdigest()[:12], key


def wait_for_idle_gates(lock):
    """Gates have priority: while any remote_gate run holds the host's active.lock (shared),
    an exclusive non-blocking probe fails and this worker sleeps before its next program."""
    if not lock:
        return
    while True:
        try:
            fd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o644)
        except OSError:
            return
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(fd, fcntl.LOCK_UN)
            return
        except OSError:
            time.sleep(15)
        finally:
            os.close(fd)


def worker(args):
    cfg, wid, iters, seed_base = args
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    rng = random.Random(seed_base * 1000 + wid)
    seeds = load_seeds(cfg["seeds"])
    out = cfg["out"]
    wd = tempfile.mkdtemp(prefix="w%d." % wid, dir=os.path.join(out, "tmp"))
    res = open(os.path.join(out, "results.jsonl"), "a")
    n = 0
    while iters <= 0 or n < iters:
        wait_for_idle_gates(cfg.get("pause_lock"))
        n += 1
        sp, src = rng.choice(seeds)
        ops = []
        for _ in range(rng.choice([1, 1, 2, 2, 3, 4])):
            src, op = mutate(src, rng, seeds)
            ops.append(op)
        for f in os.listdir(wd):
            os.unlink(os.path.join(wd, f))
        path = os.path.join(wd, "fz.elisa")
        open(path, "w").write(src)
        t = time.time()
        r = evaluate(cfg, path, wd)
        cls, an = classify(r)
        rec = {"t": round(time.time() - t, 2), "seed": os.path.relpath(sp, cfg["seed_root"]), "ops": ops, "cls": cls, **r}
        if cls:
            sig, key = signature(cls, r, an)
            rec["sig"] = sig
            d = os.path.join(out, "findings", cls, sig)
            try:
                os.makedirs(d)          # first writer wins: one representative per signature
                open(os.path.join(d, "prog.elisa"), "w").write(src)
                json.dump({**rec, "key": key}, open(os.path.join(d, "info.json"), "w"), indent=1)
            except FileExistsError:
                with open(os.path.join(d, "count"), "a") as c:
                    c.write("1")
        res.write(json.dumps(rec) + "\n"); res.flush()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--s0", required=True); ap.add_argument("--s1", required=True)
    ap.add_argument("--guard", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--jobs", type=int, default=8); ap.add_argument("--iters", type=int, default=0)
    ap.add_argument("--pause-lock", default="", help="pause while another process holds this lock")
    ap.add_argument("--rng", type=int, default=int(time.time()))
    ap.add_argument("--ctimeout", type=int, default=60); ap.add_argument("--rtimeout", type=int, default=5)
    ap.add_argument("seeds", nargs="+")
    a = ap.parse_args()
    os.makedirs(os.path.join(a.out, "tmp"), exist_ok=True)
    os.makedirs(os.path.join(a.out, "findings"), exist_ok=True)
    cfg = {"s0": a.s0, "s1": a.s1, "guard": os.path.abspath(a.guard), "out": os.path.abspath(a.out),
           "seeds": a.seeds, "seed_root": os.path.commonpath([os.path.abspath(s) for s in a.seeds]),
           "ctimeout": a.ctimeout, "rtimeout": a.rtimeout, "pause_lock": a.pause_lock,
           "cc": os.environ.get("ELISA_CLANG", "clang"), "runtime": os.environ["ELISA_RUNTIME_OBJ"],
           "fallback": os.path.join(os.path.dirname(os.path.abspath(__file__)), "callback_fallback.c")}
    n = len(load_seeds(a.seeds))
    print("fuzz: %d seeds, %d jobs, out=%s" % (n, a.jobs, a.out), flush=True)
    if n == 0:
        sys.exit(2)
    with mp.Pool(a.jobs) as pool:
        pool.map(worker, [(cfg, w, a.iters, a.rng) for w in range(a.jobs)], chunksize=1)


if __name__ == "__main__":
    main()
