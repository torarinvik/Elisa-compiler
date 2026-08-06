#!/usr/bin/env python3
"""Compile-time regression guard: stage1 compiling its OWN 117k-line source.

Nothing measured compile time before this. That is not a theoretical gap — a change that made
`sview(base, start, end)` clamp against `strlen` put a full-source scan in the lexer's
identifier path, `parse_report` went 30s -> 76s, and the only symptom anywhere was the
differential corpus reporting "2 declines exceeds baseline 1", because a timeout is counted as
a DECLINE. A slowdown looked like an acceptance regression.

What it records is a RATIO, not seconds: stage1 compiling its own source, over `clang -O2` on
a fixed C file that never changes with this repository. The gate runs six checks at a time, so
an absolute number measured there is worthless — a past session built a whole optimisation plan
on timings that were 500x distorted by exactly that. Even CPU time is not immune (measured 15.4s
idle and 26.8s while the gate ran, a 1.7x swing), so the yardstick has to be inside the same
run. Contention scales both terms and cancels.

Threshold is deliberately loose — this is a guard against a 2x-class regression, not a
benchmark. Ratio variance on an idle machine is about +/-4%. Under load the ratio FALLS (clang
suffers more from contention than stage1 does: measured 36.5 idle, 25.9 with four competing
compiles), so a busy machine can only MASK a regression here, never invent one. That is the
direction a gate check should fail in.
"""
import os, pathlib, re, resource, subprocess, sys, tempfile

ROOT = pathlib.Path(os.environ["REPO_ROOT"])
BIN = pathlib.Path(os.environ.get("ELISA_STAGE1_BIN", ROOT / "bin" / "elisac-stage1"))
BASELINE = ROOT / "test" / "fixtures" / "compile_cpu.baseline"
REFERENCE_C = ROOT / "test" / "fixtures" / "compile_cpu_reference.c"
LIMIT = float(os.environ.get("COMPILE_CPU_LIMIT", "1.5"))

include_re = re.compile(r'^[ \t]*(?:#\s*)?include[ \t]+"([^"]+)"[ \t]*$')

def flatten(path, seen, out):
    ap = path.resolve()
    if ap in seen:
        return
    seen.add(ap)
    for line in path.read_text(encoding="utf-8").splitlines(keepends=True):
        m = include_re.match(line.rstrip("\n"))
        if m:
            flatten(path.parent / m.group(1), seen, out)
        else:
            out.append(line)

def child_cpu():
    r = resource.getrusage(resource.RUSAGE_CHILDREN)
    return r.ru_utime + r.ru_stime

def main():
    out = []
    flatten(ROOT / "src" / "driver" / "elisac.elisa", set(), out)
    source = "".join(out)
    work = tempfile.mkdtemp()
    payload = (os.path.join(work, "out.o") + "\n" + source).encode()
    # The yardstick, measured in this same run and on this same machine state.
    reference = None
    for _ in range(2):
        before = child_cpu()
        r = subprocess.run(["clang", "-O2", "-c", str(REFERENCE_C), "-o", os.path.join(work, "ref.o")],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=600)
        used = child_cpu() - before
        if r.returncode != 0:
            print("compile_cpu SKIP: clang could not build the reference workload")
            return 0
        reference = used if reference is None else min(reference, used)
    if reference <= 0:
        print("compile_cpu SKIP: reference workload measured as zero")
        return 0
    # Two runs, keep the FASTER: one slow sample from a scheduling hiccup should not fail a
    # guard whose whole point is catching a systematic change.
    best = None
    for _ in range(2):
        before = child_cpu()
        r = subprocess.run([str(BIN)], input=payload, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=900)
        used = child_cpu() - before
        if r.returncode != 0:
            print(f"compile_cpu FAILED: stage1 exited {r.returncode} on its own source")
            return 1
        best = used if best is None else min(best, used)
    measured = best / reference
    if not BASELINE.exists():
        BASELINE.write_text(f"{measured:.1f}\n")
        print(f"compile_cpu: recorded baseline {measured:.1f} (stage1 CPU / clang CPU)")
        return 0
    baseline = float(BASELINE.read_text().strip())
    ratio = measured / baseline
    print(f"compile_cpu: {measured:.1f} stage1/clang vs baseline {baseline:.1f} ({ratio:.2f}x); "
          f"stage1 {best:.1f}s CPU, reference {reference:.2f}s")
    if ratio > LIMIT:
        print(f"compile_cpu FAILED: {ratio:.2f}x the baseline (limit {LIMIT:.2f}x). "
              f"Investigate before re-baselining — a slowdown here shows up elsewhere as a "
              f"phantom DECLINE.")
        return 1
    if ratio < 0.5:
        print(f"compile_cpu: {ratio:.2f}x — if the machine was idle this is a real improvement; "
              f"re-record the baseline (rm {BASELINE.relative_to(ROOT)} and re-run on an idle "
              f"machine) so the guard stays tight.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
