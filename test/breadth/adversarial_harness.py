#!/usr/bin/env python3
"""The adversarial differential HARNESS: build one generated program with both compilers,
link it, run it, and classify the pair (match / mismatch / decline / permissive / timeout /
skip). The generated programs themselves live in the adv_gen_*.py modules.

Split out of adversarial_differential.py, which is still the entry point and still owns the
scope note about what this corpus structurally cannot cover."""

import itertools, os, subprocess, sys, tempfile, hashlib


ROOT = os.environ["REPO_ROOT"]

ELISA_CORE = os.environ.get(
    "ELISA_CORE", os.path.join(ROOT, "..", "..", "Go projects", "structpy-tree")
)

S0 = os.path.expanduser(
    os.environ.get("ELISACORE_BIN", os.path.join(ELISA_CORE, "compiler", "bin", "elisac"))
)

WRAP = os.path.join(ROOT, "scripts/elisac_stage1.sh")

RT = os.environ.get("ELISA_RUNTIME_OBJ",
                    os.path.join(ROOT, "build/runtime/elisacore_runtime.o"))

STD = os.path.join(ROOT, "elisacore_std/elisacore_runtime.elisa")

ENV = dict(os.environ)

# The stage0 selector is needed by this Python oracle, but it must not leak into the stage1
# wrapper. Stage1 is the implementation under test; inheriting ELISACORE_BIN/ELISA_CORE can
# accidentally re-enter bootstrap selection or make a local product depend on the oracle.
STAGE1_ENV = dict(ENV)

for _selector in ("ELISACORE_BIN", "ELISA_CORE", "REPO_ROOT"):
    STAGE1_ENV.pop(_selector, None)


def run(cmd, **kw):
    return subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                          stdin=subprocess.DEVNULL, **kw)


# The outcome of one compile+link+run attempt. These used to be a single `False`, which
# collapsed four different events — the compiler REFUSED the program, the link failed, the
# compile timed out, the program timed out — into one. A machine under memory pressure
# therefore manufactured DECLINE and PERMISSIVE rows for programs BOTH compilers accept and
# run correctly, and those buckets are ratcheted at zero, so load turned into a red gate
# pointing at an acceptance gap that did not exist. A timeout is not a decline.
OK, DECLINED, LINK_FAILED, TIMEOUT = "ok", "declined", "link", "timeout"



def _compile_budget(base, scale):
    """The compile budget for this attempt, capped so a genuine hang still ends."""
    return min(int(base * scale), 600)



def _attempt(src_path, work, tag, run_timeout, scale=1):
    obj = os.path.join(work, f"{tag}.o")
    exe = os.path.join(work, tag)
    try:
        if tag == "s0":
            r = run([S0, "-emit", "obj", "-o", obj, src_path], timeout=_compile_budget(90, scale))
        elif tag == "s1O2":
            r = run(["bash", WRAP, "-O2", "-o", obj, src_path], env=STAGE1_ENV,
                    timeout=_compile_budget(180, scale))
        else:
            r = run(["bash", WRAP, "-o", obj, src_path], env=STAGE1_ENV,
                    timeout=_compile_budget(90, scale))
    except subprocess.TimeoutExpired:
        return (TIMEOUT, None)
    if r.returncode != 0:
        return (DECLINED, None)
    # Same three link recipes the differential corpus uses, in the same order.
    for extra in ([RT], [], [RT, "-L/opt/homebrew/opt/llvm/lib", "-lLLVM"]):
        if run(["clang", "-Wl,-dead_strip", "-o", exe, obj] + extra).returncode == 0:
            break
    else:
        return (LINK_FAILED, None)
    try:
        p = subprocess.run([exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           stdin=subprocess.DEVNULL, timeout=run_timeout)
        return (OK, p.returncode)
    except subprocess.TimeoutExpired:
        return (TIMEOUT, None)



def build_and_run(src_path, work, tag):
    """Compile+link+run with one compiler. Returns (status, exit_code).

    `s1O2` is stage1 through the real `default<O2>` pass pipeline. Optimisation must never
    change an answer, and a miscompile that only appears optimised is invisible to every
    other check here — the module datalayout bug was exactly that shape.

    A timeout is RETRIED with a wider budget before it is believed. A genuine runaway loop
    never terminates, so it times out again and is still caught; a host that is swapping
    times out once and then behaves. Without the retry the gate reports whatever else the
    machine happened to be doing."""
    status, rc = _attempt(src_path, work, tag, 10)
    if status == TIMEOUT:
        # Widen BOTH budgets, not just the run. The retry used to keep the 90 s / 180 s
        # compile timeouts, so inside the gate — where hundreds of sibling compiles share the
        # host — a slow compile timed out twice and was reported as a TIMEOUT verdict; the
        # same 387 programs pass standalone. (Mac gate 2026-09-06: adversarial FAILed at
        # 1139 s in the gate, OK alone.)
        scale = int(os.environ.get("ELISA_TIMEOUT_ESCALATE", "6"))
        status, rc = _attempt(src_path, work, tag, 30, scale)
    return (status, rc)



def classify_program(item):
    """One program end to end: returns (bucket, name, rc0, rc1). Runs in a worker process
    (PARALLEL, Phase T 2026-09-06): programs are independent and each has its own work dir,
    so the ~387-program sweep fans out over ELISA_ADV_JOBS processes (default: core count)
    instead of one compile+link+run at a time."""
    name, src, work = item
    d = os.path.join(work, name)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "p.elisa")
    open(path, "w").write(src.lstrip("\n"))
    st0, rc0 = build_and_run(path, d, "s0")
    if st0 == TIMEOUT:
        # The ORACLE timed out. That says nothing about stage1 — exactly the reasoning
        # applied to a crashing oracle below. Treating it as "stage0 rejects it" is what
        # invented PERMISSIVE rows for programs stage0 accepts perfectly well.
        return ("SKIP", name, None, None)
    if st0 != OK:
        # stage0 REFUSED it. If stage1 builds and runs the same program, stage1 is more
        # PERMISSIVE than the reference compiler — a real divergence, and one no census
        # here can otherwise see: the decline census counts what stage1 REFUSES, never
        # what it wrongly ACCEPTS. Reported separately from SKIP so the two are not
        # conflated; a genuinely malformed generator program lands in SKIP.
        st1p, _ = build_and_run(path, d, "s1")
        return ("PERMISSIVE" if st1p == OK else "SKIP", name, None, None)
    # A CRASHING oracle cannot arbitrate. differential_corpus skips a stage0 timeout for
    # the same reason; a negative code is a signal (observed: -11 SIGSEGV on a program
    # returning a ref from a value function). Counting it as a mismatch cries wolf, and a
    # gate that cries wolf trains the next REAL wrong answer to be waved through.
    if rc0 is not None and rc0 < 0:
        return ("SKIP", name, rc0, None)
    st1, rc1 = build_and_run(path, d, "s1")
    if st1 == TIMEOUT:
        return ("TIMEOUT", name, rc0, None)
    if st1 != OK:
        return ("DECLINE", name, rc0, None)
    if rc0 != rc1:
        return ("MISMATCH", name, rc0, rc1)
    # Optimisation must not change the answer. Only checked once the -O0 answer already
    # agrees, so a row here always means "the pipeline changed a CORRECT answer".
    st2, rc2 = build_and_run(path, d, "s1O2")
    if st2 == TIMEOUT:
        return ("TIMEOUT", name, rc1, None)
    if st2 != OK:
        return ("O2_DECLINE", name, rc1, None)
    if rc2 != rc1:
        return ("O2_MISMATCH", name, rc1, rc2)
    return ("MATCH", name, rc0, rc1)



def main(generators):
    only = sys.argv[1] if len(sys.argv) > 1 else None
    results = {"MATCH": [], "MISMATCH": [], "O2_MISMATCH": [], "O2_DECLINE": [], "DECLINE": [], "PERMISSIVE": [], "TIMEOUT": [], "SKIP": []}
    work = tempfile.mkdtemp()
    progs = []
    for g in generators:
        if only and only not in g.__name__:
            continue
        progs.extend(g())
    import multiprocessing
    jobs = int(os.environ.get("ELISA_ADV_JOBS", "0") or 0) or int(os.environ.get("ELISA_JOBS", "0") or 0)
    if not jobs:
        jobs = os.cpu_count() or 4
        try:  # a container CPU quota beats the visible core count (test/parity/host_jobs.sh)
            quota, period = open("/sys/fs/cgroup/cpu.max").read().split()
            if quota != "max":
                jobs = min(jobs, max(1, -(-int(quota) // int(period))))
        except (OSError, ValueError):
            pass
    items = [(name, src, work) for name, src in progs]
    if jobs > 1 and len(items) > 1:
        with multiprocessing.Pool(processes=jobs) as pool:
            rows = list(pool.imap_unordered(classify_program, items))
    else:
        rows = [classify_program(item) for item in items]
    # Deterministic report whatever the scheduling: buckets in name order.
    for bucket, name, rc0, rc1 in sorted(rows, key=lambda r: r[1]):
        results[bucket].append((name, rc0, rc1))
    for k in ("MISMATCH", "O2_MISMATCH", "O2_DECLINE", "DECLINE", "PERMISSIVE", "TIMEOUT", "SKIP", "MATCH"):
        for name, rc0, rc1 in results[k]:
            if k == "MATCH":
                continue
            extra = f"  stage0={rc0} stage1={rc1}" if rc0 is not None else ""
            print(f"  {k:9s} {name}{extra}")
    print(f"\nadversarial: {len(progs)} programs — "
          f"{len(results['MATCH'])} match, {len(results['MISMATCH'])} MISMATCH, "
          f"{len(results['O2_MISMATCH'])} O2_MISMATCH, {len(results['O2_DECLINE'])} O2_DECLINE, "
          f"{len(results['DECLINE'])} declined, "
          f"{len(results['PERMISSIVE'])} PERMISSIVE (stage0 rejects, stage1 builds), "
          f"{len(results['TIMEOUT'])} TIMEOUT, "
          f"{len(results['SKIP'])} skipped")
    print(f"work dir: {work}")
    # RATCHET. All three of these are at zero and must stay there:
    #   MISMATCH   a silent wrong answer — the worst outcome there is
    #   DECLINE    stage0 built it, stage1 could not (an acceptance gap)
    #   PERMISSIVE stage0 rejects it, stage1 builds it (the direction no census can see)
    # SKIP is not ratcheted: it means the ORACLE could not arbitrate (stage0 rejects the
    # program, or crashes on it), which says nothing about stage1. Keep those few honest by
    # fixing the generator program rather than by tolerating the skip.
    # TIMEOUT is ratcheted too: a program that will not finish twice, with a widened budget,
    # is a runaway loop until proven otherwise. It is a SEPARATE bucket only so the report
    # names what happened — "timed out" sends you to the host or to a hang, "declined" sent
    # you hunting an acceptance gap that was never there.
    return 1 if results["MISMATCH"] or results["O2_MISMATCH"] or results["O2_DECLINE"] or results["DECLINE"] or results["PERMISSIVE"] or results["TIMEOUT"] else 0

