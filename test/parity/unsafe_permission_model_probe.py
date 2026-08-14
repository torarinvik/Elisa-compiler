#!/usr/bin/env python3
"""DESIGN ORACLE for a future `-emit unsafe`: how much of stage0's per-function permission
set is reconstructible WITHOUT porting its provers?

`-emit unsafe` reports, per function, the Unsafe.* capabilities it requires. Those are NOT
the declared `can[...]` effects: stage0 accumulates them during analysis and PROPAGATES them
through calls, so a function calling an extern holds Unsafe.RawExtern without declaring it.

This measures a candidate model against stage0 over the corpus:

    declared Unsafe.* effects (signature AND in-body `can`/grant sites)
  + externs contribute Unsafe.RawExtern
  + transitive closure over the call graph

The result that matters is not the exact-match count but the EXTRA count. A model that
over-claims invents capabilities a function does not need; a model that under-claims hides
them. For an audit whose output is a SAFETY claim, both are wrong, and under-claiming is the
worse direction — which is why the mode is not shipped on a partial model.

Last run (2026-08-14): exact=31 partial=9, EXTRA=0, missing only Unsafe.UncheckedIndex (3)
and Unsafe.BufferReinterpret (2). So the model is SOUND but incomplete, and the residue is
exactly the capabilities stage0 infers from a BOUNDS-PROVENNESS judgement rather than from a
declaration. Adding a syntactic "bare subscript => UncheckedIndex" rule was measured and
made it WORSE: it closed 7 but introduced 4 EXTRA.

    python3 test/parity/unsafe_permission_model_probe.py

Conclusion this encodes: finishing `-emit unsafe` means making stage1's EXISTING unproven-
index checks (check_strict_unsafe_ops_walk, check_fixed_index_range, check_assoc_index_bounds
— 27 sites) RECORD a per-function requirement, not only report a violation when ungranted.
The rest of the set falls out of the sound model above.
"""
import collections
import pathlib
import re
import subprocess

S0 = pathlib.Path.home() / ".elisac/elisac"
ROOT = pathlib.Path(__file__).resolve().parents[2]


def stage0_functions(src):
    proc = subprocess.run([str(S0), "-emit", "unsafe", str(src)],
                          capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if proc.returncode != 0:
        return None
    out, inside = {}, False
    for line in proc.stdout.splitlines():
        if line == "functions:":
            inside = True
            continue
        if inside:
            if not line.startswith("  "):
                break
            name, perms = line.strip().split(":", 1)
            out[name] = {x.strip() for x in perms.split(",")}
    return out


def reconstruct(text):
    declared = collections.defaultdict(set)
    bodies, cur = {}, None
    for line in text.split("\n"):
        extern = re.match(r"^extern\s+([A-Za-z_]\w*)\s*\(", line)
        if extern:
            declared[extern.group(1)].add("Unsafe.RawExtern")
            continue
        func = re.match(r"^def\s+([A-Za-z_]\w*)", line)
        if func:
            cur = func.group(1)
            bodies[cur] = []
            declared[cur] |= set(re.findall(r"Unsafe\.\w+", line))
            continue
        if cur is not None:
            if line and not line[0].isspace() and not line.startswith("#"):
                cur = None
                continue
            bodies[cur].append(line)
            declared[cur] |= set(re.findall(r"Unsafe\.\w+", line))
    perms = {name: set(caps) for name, caps in declared.items()}
    for name in bodies:
        perms.setdefault(name, set())
    calls = {f: set(re.findall(r"([A-Za-z_]\w*)\s*\(", "\n".join(b))) for f, b in bodies.items()}
    changed = True
    while changed:
        changed = False
        for caller, callees in calls.items():
            for callee in callees:
                if callee in perms and not perms[callee] <= perms[caller]:
                    perms[caller] |= perms[callee]
                    changed = True
    return {f: caps for f, caps in perms.items() if caps}


def main():
    exact = partial = 0
    missed, extra = collections.Counter(), collections.Counter()
    sources = sorted((ROOT / "test/repro").glob("*.elisa")) + \
        sorted((ROOT / "test/fixtures/ast").glob("*.elisa"))
    for src in sources:
        want = stage0_functions(src)
        if want is None:
            continue
        got = reconstruct(src.read_text())
        if got == want:
            exact += 1
            continue
        partial += 1
        for name, caps in want.items():
            for cap in caps - got.get(name, set()):
                missed[cap] += 1
        for name, caps in got.items():
            for cap in caps - want.get(name, set()):
                extra[cap] += 1
    print(f"exact={exact} partial={partial}")
    print("MISSED (stage0 has, model does not):", missed.most_common(6))
    print("EXTRA  (model has, stage0 does not):", extra.most_common(6))
    print("\nEXTRA must stay EMPTY: the model may be incomplete, never over-claiming.")
    return 1 if extra else 0


if __name__ == "__main__":
    raise SystemExit(main())
