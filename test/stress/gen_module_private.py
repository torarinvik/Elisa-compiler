#!/usr/bin/env python3
"""Bounded, SEEDED generator for the bug families under test. Each program is small, valid
by construction unless marked '.bad' (a deliberate malformed variant), and returns 0 when
its own hand-computable assertions hold. Records every (seed, index) so a failure minimizes
into a permanent case."""
import random, sys, os
seed = int(sys.argv[1]); count = int(sys.argv[2]); out = sys.argv[3]
rng = random.Random(seed); os.makedirs(out, exist_ok=True)
def program(k):
    n_mod = rng.randint(2, 6)
    mods = []
    expect = []
    for m in range(n_mod):
        name = chr(ord("A") + m)
        init = rng.randint(1, 900)
        arr_n = rng.randint(2, 6)
        arr = [rng.randint(0, 50) for _ in range(arr_n)]
        mods.append((name, init, arr))
    order = list(range(n_mod)); rng.shuffle(order)
    lines = []
    for idx in order:
        name, init, arr = mods[idx]
        lines += [f"module {name}:", "    private:",
                  f"        global mutable counter: i64 = {init}",
                  f"        global mutable values: i64[{len(arr)}] = [{', '.join(map(str, arr))}]",
                  "    public:",
                  "        def read() -> i64:", "            return counter",
                  "        def total() -> i64:", "            t: mutable i64 = 0",
                  f"            for i in 0..<{len(arr)}:", "                t <- t + values[i]", "            return t",
                  "        def bump(by: i64) -> void:", "            counter <- counter + by", ""]
    lines += ["def main() -> i64:"]
    code = 1
    state = {name: init for name, init, _ in mods}
    for step in range(rng.randint(3, 8)):
        name, init, arr = mods[rng.randrange(n_mod)]
        by = rng.randint(1, 20); state[name] += by
        lines.append(f"    {name}::bump({by})")
        for name2, _, arr2 in mods:
            lines.append(f"    {code} return if {name2}::read() != {state[name2]}"); code += 1
            lines.append(f"    {code} return if {name2}::total() != {sum(arr2)}"); code += 1
    lines.append("    return 0")
    return "\n".join(lines) + "\n"
for k in range(count):
    src = program(k)
    bad = rng.random() < 0.15
    name = f"s{seed}_{k}" + (".bad" if bad else "")
    if bad:  # a deliberately malformed sibling: private access from outside
        src += "\ndef poke() -> i64:\n    return A::counter\n"
    open(os.path.join(out, name + ".elisa"), "w").write(src)
print(f"wrote {count} programs for seed {seed} into {out}")
