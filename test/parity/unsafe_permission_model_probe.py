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

Last run (2026-08-14): **exact=40 partial=0, MISSED=0, EXTRA=0** — complete on the corpus.

    python3 test/parity/unsafe_permission_model_probe.py

The full rule set, each rule decidable from the AST and declared types (NO prover):

  1. declared Unsafe.* effects, from the signature AND in-body grant sites
  2. externs contribute Unsafe.RawExtern
  3. TRANSITIVE CLOSURE over the call graph
  4. a bare subscript on a RUNTIME-LENGTH container (darray) needs Unsafe.UncheckedIndex,
     except when
       - the index is a loop variable bounded by `for i in 0..<container.count`, which
         proves it against the container's own length, or
       - the subscript has an index FALLBACK (`xs[i] else v`) or is a `get` form
  5. `(&xs[0]).cast[T]` needs Unsafe.BufferReinterpret

Getting here took three wrong turns, all corrected by measurement, and they are the reason
this file exists:

  * declared-only scored 30/56 and UNDER-reported — withdrawn.
  * a crude "any bare subscript" rule over-claimed (4 EXTRA) while closing only 7 of 10.
    The fix was making the rule TYPE-DIRECTED (runtime-length containers only), not broader.
  * skipping any line containing `else` conflated an index fallback with a TERNARY else and
    lost three files. stage1's AST settles that exactly — Expr.Index carries its own
    Fallback — so the disambiguation is free in the real implementation.

Rule 4's carve-out was found from a single counterexample (region_param_arena.elisa::prune,
`for i in 0..<boxes.count: boxes[i]`). Expect more such idioms outside this corpus: keep
EXTRA at zero and add carve-outs, never widen the rule to chase a MISS.
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
    bodies, header_of, cur = {}, {}, None
    for line in text.split("\n"):
        extern = re.match(r"^extern\s+([A-Za-z_]\w*)\s*\(", line)
        if extern:
            declared[extern.group(1)].add("Unsafe.RawExtern")
            continue
        func = re.match(r"^def\s+([A-Za-z_]\w*)", line)
        if func:
            cur = func.group(1)
            bodies[cur] = []
            header_of[cur] = line
            declared[cur] |= set(re.findall(r"Unsafe\.\w+", line))
            continue
        if cur is not None:
            if line and not line[0].isspace() and not line.startswith("#"):
                cur = None
                continue
            bodies[cur].append(line)
            declared[cur] |= set(re.findall(r"Unsafe\.\w+", line))
    # TYPE-DIRECTED unchecked-index rule: a bare subscript (no `get`, no `else` fallback)
    # on a RUNTIME-LENGTH container is unproven by construction, because its length is never
    # statically known. A fixed `array[T, N]` is excluded — stage0 proves a constant index in
    # range. Names are collected from `x: ... darray[...]` declarations and parameters.
    for func, body in bodies.items():
        text_body = "\n".join(body)
        runtime_len = set(re.findall(r"([A-Za-z_]\w*)\s*:[^=\n]*\bdarray\s*\[", text_body))
        runtime_len |= set(re.findall(r"([A-Za-z_]\w*)\s*:[^,)\n]*\bdarray\s*\[", header_of.get(func, "")))
        # `for i in 0..<xs.count` PROVES `xs[i]` in range against the container's own length.
        # stage0 recognises this idiom and does not flag it; without the carve-out the model
        # over-claims on it (measured on region_param_arena.elisa::prune).
        bounded = collections.defaultdict(set)
        for line in body:
            m = re.search(r"for\s+([A-Za-z_]\w*)\s+in\s+0\s*\.\.<\s*([A-Za-z_]\w*)\.count", line)
            if m:
                bounded[m.group(2)].add(m.group(1))
        for line in body:
            code = line.split("#")[0]
            # Only an INDEX FALLBACK (`xs[i] else v`) makes a subscript checked. A ternary
            # `a if c else b` on the same line does not — skipping on a bare `else` lost
            # sv_j/sv_k/two_darrays_sview_eq. stage1's AST settles this exactly: Expr.Index
            # carries its own Fallback, so no textual disambiguation is needed there.
            if re.search(r"\]\s*else\b", code) or "get " in code:
                continue
            # `(&xs[0]).cast[T]` reinterprets the container's buffer.
            if re.search(r"&\s*[A-Za-z_]\w*\s*\[[^\]]*\]\s*\)?\s*\.cast\s*\[", code):
                declared[func].add("Unsafe.BufferReinterpret")
            for hit in re.finditer(r"\b([A-Za-z_]\w*)\s*\[\s*([A-Za-z_]\w*)?", code):
                container, index = hit.group(1), hit.group(2)
                if container not in runtime_len:
                    continue
                if index is not None and index in bounded.get(container, set()):
                    continue
                declared[func].add("Unsafe.UncheckedIndex")
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
