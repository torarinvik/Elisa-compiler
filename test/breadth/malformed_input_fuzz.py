#!/usr/bin/env python3
"""Robustness sweep: a compiler must DIAGNOSE malformed input, never crash on it.

Every other harness in this repo feeds stage1 programs stage0 can build. Nothing asked what
happens on garbage — and the answer was a SIGTRAP inside LLVM's DataLayout, from IR the
verifier rejects (`store void <badref>`), on a program stage0 answers with one clean line.

Method: mutate real sources (truncate, delete a span, flip a byte to a structural character,
duplicate a span) with a FIXED seed, compile each with stage1, and require an ordinary exit.
Exit codes 0..2 are all fine — 0 compiled, 1 diagnosed, 2 declined; a negative code (a signal)
or anything above 2 is a crash. The mutants are not valid programs, so nothing here compares
ANSWERS; that is the differential suite's job.
"""
import os, random, subprocess, sys

ROOT = os.environ["REPO_ROOT"]
WRAP = os.path.join(ROOT, "scripts/elisac_stage1.sh")
MUTANTS_PER_SEED = int(os.environ.get("FUZZ_MUTANTS_PER_SEED", "4"))
random.seed(int(os.environ.get("FUZZ_SEED", "20260806")))

# Programs that CRASHED stage1 before this check existed. Kept explicitly so a regression is
# named rather than left to the random sweep to rediscover.
REGRESSIONS = [
    ("void_call_into_vardecl", "def compute()\n\ndef f() -> void:\n    x: i64 = compute()\n"),
    ("void_call_into_return", "def compute()\n\ndef f() -> i64:\n    return compute()\n"),
    ("void_call_into_push", "def compute()\n\ndef f() -> void:\n    xs: mutable darray[i64] = []\n    xs.push(compute())\n"),
    ("malformed_signature_then_call", "def compute() -rn 5\n\ndef f() -> void:\n    x: i64 = compute()\n"),
]

def compile_rc(path, work):
    r = subprocess.run(["bash", WRAP, "-o", os.path.join(work, "out.o"), path],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       stdin=subprocess.DEVNULL, timeout=120)
    return r.returncode

def abnormal(rc):
    return rc < 0 or rc > 2

def mutate(data):
    b = bytearray(data)
    if not b:
        return bytes(b)
    kind = random.randrange(4)
    if kind == 0:
        b = b[:random.randrange(1, len(b))]
    elif kind == 1:
        i = random.randrange(len(b)); j = min(len(b), i + random.randrange(1, 40))
        del b[i:j]
    elif kind == 2:
        i = random.randrange(len(b)); b[i] = ord(random.choice("():,[]{}\t \n|<-="))
    else:
        i = random.randrange(len(b)); j = min(len(b), i + random.randrange(1, 30))
        b[i:i] = b[i:j]
    return bytes(b)

def main():
    import tempfile
    work = tempfile.mkdtemp()
    src = os.path.join(work, "m.elisa")
    failures = []
    for name, text in REGRESSIONS:
        open(src, "w").write(text)
        rc = compile_rc(src, work)
        if abnormal(rc):
            failures.append((name, rc))
    seeds = []
    for d in ("test/repro", "test/fixtures/diagnostics"):
        p = os.path.join(ROOT, d)
        for f in sorted(os.listdir(p)):
            if f.endswith(".elisa"):
                seeds.append(os.path.join(p, f))
    checked = len(REGRESSIONS)
    for seed in seeds:
        data = open(seed, "rb").read()
        for k in range(MUTANTS_PER_SEED):
            open(src, "wb").write(mutate(data))
            checked += 1
            rc = compile_rc(src, work)
            if abnormal(rc):
                crash = os.path.join(work, f"crash_{len(failures)}.elisa")
                open(crash, "wb").write(open(src, "rb").read())
                failures.append((f"{os.path.basename(seed)}#{k} -> {crash}", rc))
    for name, rc in failures:
        print(f"  CRASH rc={rc}  {name}")
    print(f"malformed input: {checked} programs, {len(failures)} abnormal exits")
    return 1 if failures else 0

if __name__ == "__main__":
    sys.exit(main())
