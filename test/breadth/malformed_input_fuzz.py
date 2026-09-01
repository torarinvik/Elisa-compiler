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

A mutant that COMPILES gets a second look: its IR is emitted and run through `opt -passes=verify`.
That is where the remaining defects of this class live — the frontend accepted the program, so
the backend emitted something for a shape nobody wrote on purpose, and invalid IR that happens
NOT to crash is otherwise invisible (the object path tolerates it; see llvm_verifier_smoke.sh).
It found `ret ptr` from an `-> i64` function, from returning a `fn` value that stage0 rejects
outright.
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
    # Non-IDENTIFIER junk after the def name: the signature-tail guard only caught Ident
    # heads, so `def f 9 -> 3` was consumed whole by parse_signature_clauses with no
    # diagnostic, became a phantom declaration-only `f`, and the later genuine `def f`
    # made a duplicate whose call site crashed the backend (found by the random sweep as
    # stepped_range_for.elisa#2).
    ("junk_signature_then_duplicate", "def g() -> i64:\n    return 1\ndef f 9 -> 3\ndef f() -> i64:\n    return 2\ndef main() -> i64:\n    return g() + f()\n"),
    # Not a crash — INVALID IR that the object path tolerated: `ret ptr` from an `-> i64`
    # function. stage0 says "return type expects i64, got fn(i64) -> i64".
    ("fn_value_returned_as_scalar", "def apply(f: fn(i64) -> i64, n: i64) -> i64:\n    return f\n"),
    # A left-nested `1 + 1 + 1 + ...` chain (adversarial, not anything real code writes) SIGSEGV'd
    # the backend: `expression_type` (codegen_scope.elisa) re-walked the whole remaining left
    # spine from scratch at EVERY one of the N levels of the emitter's own recursion into
    # `binary_left` — O(N^2) time, and the combined recursion depth also exceeded the default
    # ~8MB native stack. stage0 (and gen0 unoptimized) compile this instantly. Fixed by capping
    # `expression_type`'s own recursion depth (falls back to Unmodeled, the same answer a bare
    # literal already gives, past 200 levels — far deeper than any genuine expression) and by
    # linking the product binary with a 512MB stack (scripts/elisac_stage1.sh, build_drivers.sh,
    # self_host_gen2.sh). 5000 is comfortably past the depth that used to crash (~15000-20000)
    # while keeping this regression's own runtime short.
    ("deep_left_binary_chain", "def main() -> i64:\n    return " + "1" + " + 1" * 5000 + "\n"),
    # A chain of just 30 nested `not`s hung the compiler indefinitely (confirmed exponential:
    # n=25 took 0.7s, n=30 did not finish in 15s). Root cause: check_double_negation.elisa's
    # `walk_double_negation_expression` called itself on the SAME `operand` TWICE in the
    # `Expr.Unary` case — once before its own diagnostic checks, once again after — so a chain
    # of N nested unaries cost T(n) = 2*T(n-1) + O(1) = O(2^n). stage0 accepts arbitrarily deep
    # `not` chains instantly. Fixed by deleting the redundant second walk. 100 is comfortably
    # past the point that used to hang (n=30) while keeping this regression's own runtime short.
    ("deep_not_chain", "def main() -> i64:\n    b: bool = " + "not " * 100 + "true\n    return 0 if b else 1\n"),
]

OPT = os.path.join(os.path.dirname(os.environ.get("LLVM_CONFIG", "/opt/homebrew/opt/llvm/bin/llvm-config")), "opt")

def compile_rc(path, work):
    # A genuine HANG must come back as an ordinary (abnormal) return code, not an uncaught
    # TimeoutExpired — an uncaught exception here crashes this script instead of reporting the
    # hang as a failure, which is worse than useless for a harness whose whole job is "never
    # let a hang go undetected" (see the module docstring). -9 mimics a killed-by-signal exit
    # so `abnormal()` (rc < 0 or rc > 2) flags it exactly like a crash would.
    try:
        r = subprocess.run(["bash", WRAP, "-o", os.path.join(work, "out.o"), path],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           stdin=subprocess.DEVNULL, timeout=120)
        return r.returncode
    except subprocess.TimeoutExpired:
        return -9

def invalid_ir(path, work):
    """None when the IR is valid or unavailable; the verifier's first line when it is not."""
    if not os.path.exists(OPT):
        return None
    ll = os.path.join(work, "out.ll")
    r = subprocess.run(["bash", WRAP, "-emit", "llvm", "-o", ll, path],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       stdin=subprocess.DEVNULL, timeout=120)
    if r.returncode != 0:
        return None
    v = subprocess.run([OPT, "-passes=verify", "-disable-output", ll],
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=120)
    if v.returncode == 0:
        return None
    lines = v.stderr.decode().splitlines()
    return lines[0] if lines else "invalid IR"

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
        elif rc == 0:
            bad = invalid_ir(src, work)
            if bad:
                failures.append((f"{name} [invalid IR] {bad}", rc))
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
            elif rc == 0:
                bad = invalid_ir(src, work)
                if bad:
                    keep = os.path.join(work, f"invalid_{len(failures)}.elisa")
                    open(keep, "wb").write(open(src, "rb").read())
                    failures.append((f"{os.path.basename(seed)}#{k} [invalid IR] {bad} -> {keep}", rc))
    for name, rc in failures:
        print(f"  CRASH rc={rc}  {name}")
    print(f"malformed input: {checked} programs, {len(failures)} abnormal exits or invalid IR")
    return 1 if failures else 0

if __name__ == "__main__":
    sys.exit(main())
