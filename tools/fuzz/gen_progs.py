#!/usr/bin/env python3
"""Random VALID-program generator for stage0/stage1 runtime differential testing (Csmith-style).

Unlike fuzz.py (which mutates fixtures and mostly probes verdicts), every program produced here
is meant to be accepted by both compilers and to have exactly one defined behaviour, so any
difference in the printed trace or exit code between the two products is a miscompile.

UB-avoidance rules (each one exists because the two compilers legitimately differ otherwise):
  * signed overflow: stage1 traps at every -O level, stage0 wraps from -O1 (memory note
    signed-overflow-mode). Every arithmetic node is reduced `% M` (M = 100003) so operands stay
    below 1e5 in magnitude and a product stays below 1e10.
  * division / modulo: the divisor is `(e % 7 + 8)`, which lies in [2, 14].
  * shifts: left operand masked `& 1023`, amount `& 7`.
  * array indices: `% len` of a non-empty darray after `& 1023` (non-negative).
  * loops: bounded `for` ranges, and `while` loops driven by a fresh counter.
  * calls only go to lower-numbered functions, so there is no recursion.

Each program prints a trace through `putchar` (a checksum after every function call in main
plus the final state) and returns `checksum & 127`.

    gen_progs.py --seed N [--count K] --out DIR      # writes DIR/p<seed>.elisa ...
"""
import argparse, os, random

M = 100003

PRELUDE = """extern putchar(c: int) -> int

def pr(n: i64) -> i64:
    x: mutable i64 = n
    if x < 0:
        putchar(45)
        x <- 0 - x
    digits: mutable darray[i64] = []
    if x == 0:
        digits.push(0)
    while x > 0 |x|:
        digits.push(x % 10)
        x <- x / 10
    k: mutable i64 = digits.count.i64()
    while k > 0 |k|:
        k <- k - 1
        putchar((digits[k] + 48).int())
    putchar(10)
    return 0
"""


class Gen:
    def __init__(self, rng, features):
        self.r = rng
        self.f = features
        self.uid = 0
        self.funcs = []  # (name, nparams)
        self.structs = []
        self.enum = None
        self.in_loop = 0
        self.unary = []
        self.effectful = {}

    def fresh(self, p):
        self.uid += 1
        return f"{p}{self.uid}"

    # ---------------- expressions ----------------
    def atom(self, env, rec=True):
        r = self.r
        ints = [v for v, t in env.items() if t == "i64"]
        c = r.random()
        if ints and (c < 0.55 or not rec):
            return r.choice(ints)
        if not rec:
            return str(r.choice([0, 1, 3, 7, 42, -5]))
        if c < 0.62 and env.get("__arrs"):
            a = r.choice(env["__arrs"])
            return f"{a}[({self.atom(env, False)} & 1023) % {a}.count.i64()]"
        if c < 0.68 and env.get("__structs"):
            s, fields = r.choice(env["__structs"])
            return f"{s}.{r.choice(fields)}"
        if c < 0.72 and "u8" in self.f:
            return f"({self.atom(env, False)} & 255).u8().i64()"
        if c < 0.76 and "i32" in self.f:
            return f"(({self.atom(env, False)} % 1000).i32() * 3.i32()).i64()"
        if c < 0.79 and "cenum" in self.f:
            return f"K.{r.choice(['A', 'B', 'C', 'D', 'E'])}.i64()"
        if c < 0.82 and "u32" in self.f:
            x, y = self.atom(env, False), self.atom(env, False)
            op = r.choice(["*", "+", ">>", "/", "%"])
            rhs = f"(({y} & 15) + 1).u32()" if op in ("/", "%", ">>") else f"({y} & 65535).u32()"
            return f"((({x} & 65535).u32() {op} {rhs}).i64() % {M})"
        if c < 0.85 and "f64" in self.f:
            x, y = self.atom(env, False), self.atom(env, False)
            return f"((({x}).f64() * 1.5 + ({y}).f64() / 4.0) / 3.0).i64()"
        if c < 0.88 and "opt" in self.f:
            return f"(oget({self.atom(env, False)}) if 1 > 0 else 0)"
        if c < 0.91 and "query" in self.f and env.get("__arrs"):
            a = r.choice(env["__arrs"])
            q = r.choice(["sum", "count"])
            return f"({q} y in {a} where y {r.choice(['>', '<', '!='])} {self.atom(env, False)})"
        if c < 0.94 and "fnval" in self.f and env.get("__fns"):
            return f"{r.choice(env['__fns'])}({self.atom(env, False)})"
        if c < 0.96 and "sarr" in self.f and env.get("__sarrs"):
            a = r.choice(env["__sarrs"])
            return f"{a}[({self.atom(env, False)} & 1023) % {a}.count.i64()].f{r.randint(0, 1)}"
        return str(r.choice([0, 1, 2, 3, 5, 7, 10, 13, 42, 99, 255, 1000, 65535, 99991]) * r.choice([1, 1, 1, -1]))

    def expr(self, env, depth):
        r = self.r
        if depth <= 0 or r.random() < 0.25:
            return self.atom(env)
        k = r.random()
        a = self.expr(env, depth - 1)
        b = self.expr(env, depth - 1)
        if k < 0.45:
            op = r.choice(["+", "-", "*"])
            return f"(({a} {op} {b}) % {M})"
        if k < 0.55:
            op = r.choice(["/", "%"])
            return f"({a} {op} ({b} % 7 + 8))"
        if k < 0.62:
            op = r.choice(["&", "|", "^"])
            return f"({a} {op} {b})"
        if k < 0.67:
            return f"(({a} & 1023) << ({b} & 7))"
        if k < 0.71:
            return f"({a} >> ({b} & 7))"
        if k < 0.82:
            return f"({a} if {self.cond(env, depth - 1)} else {b})"
        if k < 0.92 and self.funcs:
            name, n = r.choice(self.funcs)
            args = ", ".join(self.expr(env, depth - 1) for _ in range(n))
            return f"{name}({args})"
        if k < 0.96 and self.enum and "enum" in self.f:
            return f"ev({self.mk_enum(env, depth - 1)})"
        return f"(0 - {a})"

    def cond(self, env, depth):
        r = self.r
        k = r.random()
        if depth > 0 and k < 0.15:
            return f"({self.cond(env, depth - 1)} {r.choice(['and', 'or'])} {self.cond(env, depth - 1)})"
        if depth > 0 and k < 0.2:
            return f"(not {self.cond(env, depth - 1)})"
        if "usize" in self.f and env.get("__arrs") and r.random() < 0.3:
            # usize arithmetic: `.count` and a `count` query are usize in stage0 (docs/18), so a
            # difference below zero WRAPS and compares huge. Literals only, so the operand types
            # agree; every product stays far below 2^64.
            a = r.choice(env["__arrs"])
            base = r.choice([f"{a}.count", f"(count y in {a} where y {r.choice(['>', '<', '!='])} {r.randint(-5, 50)})"])
            return f"({base} {r.choice(['+', '-', '-', '*', '/'])} {r.randint(1, 9)} {r.choice(['<', '<=', '>', '>=', '==', '!='])} {r.randint(0, 12)})"
        bools = [v for v, t in env.items() if t == "bool"]
        if bools and k < 0.4:
            return r.choice(bools)
        op = r.choice(["<", "<=", ">", ">=", "==", "!="])
        return f"({self.expr(env, max(depth - 1, 0))} {op} {self.expr(env, max(depth - 1, 0))})"

    def mk_enum(self, env, depth):
        r = self.r
        v = r.choice(self.enum)
        if v[1]:
            return f"E.{v[0]}({self.expr(env, depth)})"
        return f"E.{v[0]}"

    # ---------------- statements ----------------
    def block(self, env, ind, n, depth, muts):
        out = []
        env = dict(env)
        for k in ("__arrs", "__structs", "__fns", "__sarrs"):
            env[k] = list(env.get(k, []))
        for _ in range(n):
            out += self.stmt(env, ind, depth, muts)
        return out

    def stmt(self, env, ind, depth, muts):
        r = self.r
        sp = " " * ind
        k = r.random()
        mutable_ints = [v for v in muts if env.get(v) == "i64"]
        if k < 0.22 or not mutable_ints:
            v = self.fresh("v")
            line = f"{sp}{v}: mutable i64 = {self.expr(env, 3)}"
            env[v] = "i64"
            muts.add(v)
            return [line]
        if k < 0.45:
            v = r.choice(mutable_ints)
            op = r.choice(["<-", "<-", "+=", "-="]) if "compound" in self.f else "<-"
            if op == "<-":
                return [f"{sp}{v} <- {self.expr(env, 3)}"]
            return [f"{sp}{v} {op} {self.expr(env, 2)}", f"{sp}{v} <- {v} % {M}"]
        if k < 0.53:
            v = self.fresh("b")
            line = f"{sp}{v}: bool = {self.cond(env, 2)}"
            env[v] = "bool"
            return [line]
        if k < 0.65 and depth > 0:
            out = [f"{sp}if {self.cond(env, 2)}:"] + self.block(env, ind + 4, r.randint(1, 3), depth - 1, muts)
            if r.random() < 0.5:
                out += [f"{sp}else:"] + self.block(env, ind + 4, r.randint(1, 3), depth - 1, muts)
            return out
        if k < 0.75 and depth > 0:
            caps = [v for v in mutable_ints if r.random() < 0.6] or [r.choice(mutable_ints)]
            iv = self.fresh("i")
            lo, hi = r.randint(-3, 3), r.randint(0, 9)
            rng = r.choice([f"{lo}..<{hi}", f"{lo}..={hi}", f"0..<{hi + 1}..{r.randint(1, 3)}"]) if "ranges" in self.f else f"0..<{hi}"
            inner = dict(env)
            inner[iv] = "i64"
            self.in_loop += 1
            body = self.block(inner, ind + 4, r.randint(1, 3), depth - 1, set(caps))
            self.in_loop -= 1
            if r.random() < 0.2:
                body.insert(r.randint(0, len(body)) if False else 0,
                            f"{sp}    {r.choice(['break', 'continue'])} if {self.cond(inner, 1)}")
            return [f"{sp}for {iv} in {rng} |{', '.join(caps)}|:"] + body
        if k < 0.8 and depth > 0:
            c = self.fresh("w")
            caps = [v for v in mutable_ints if r.random() < 0.5]
            self.in_loop += 1
            body = self.block(env, ind + 4, r.randint(1, 3), depth - 1, set(caps))
            self.in_loop -= 1
            return [f"{sp}{c}: mutable i64 = 0",
                    f"{sp}while {c} < {r.randint(0, 6)} |{', '.join(caps + [c])}|:",
                    f"{sp}    {c} <- {c} + 1"] + body
        if k < 0.86 and "darray" in self.f:
            a = self.fresh("a")
            vals = ", ".join(self.expr(env, 1) for _ in range(r.randint(1, 4)))
            out = [f"{sp}{a}: mutable darray[i64] = [{vals}]"]
            for _ in range(r.randint(0, 3)):
                out.append(f"{sp}{a}.push({self.expr(env, 2)})")
            if r.random() < 0.4:
                out.append(f"{sp}{a}[({self.expr(env, 1)} & 1023) % {a}.count.i64()] <- {self.expr(env, 2)}")
            env["__arrs"].append(a)
            return out
        if k < 0.91 and self.structs and "struct" in self.f:
            name, fields = self.r.choice(self.structs)
            s = self.fresh("s")
            init = ", ".join(f"{f}: {self.expr(env, 2)}" for f in fields)
            env["__structs"].append((s, fields))
            return [f"{sp}{s}: {name} = {name}{{{init}}}"]
        if k < 0.96 and self.enum and "enum" in self.f:
            v = r.choice(mutable_ints)
            return [f"{sp}{v} <- ({v} + ev({self.mk_enum(env, 2)})) % {M}"]
        k2 = r.random()
        if k2 < 0.15 and "defer" in self.f and ind == 4 and not self.in_loop:
            return [f"{sp}defer block:", f"{sp}    gacc <- (gacc * 3 + {r.randint(1, 9)}) % {M}"]
        if k2 < 0.3 and "opt" in self.f:
            v = r.choice(mutable_ints)
            t = self.fresh("t")
            out = [f"{sp}if ofind({self.expr(env, 2)}) is {t}:", f"{sp}    {v} <- ({v} + {t} * 3) % {M}"]
            if r.random() < 0.5:
                out += [f"{sp}else:", f"{sp}    {v} <- ({v} + 17) % {M}"]
            return out
        if k2 < 0.45 and "fnval" in self.f and self.unary:
            g = self.fresh("g")
            env["__fns"].append(g)
            return [f"{sp}{g}: fn(i64) -> i64 = {r.choice(self.unary)}"]
        if k2 < 0.6 and "sarr" in self.f:
            a = self.fresh("sa")
            out = [f"{sp}{a}: mutable darray[P] = [P{{f0: {self.expr(env, 1)}, f1: {self.expr(env, 1)}}}]"]
            for _ in range(r.randint(0, 3)):
                out.append(f"{sp}{a}.push(P{{f0: {self.expr(env, 1)}, f1: {self.expr(env, 1)}}})")
            for _ in range(r.randint(0, 2)):
                out.append(f"{sp}{a}[({self.atom(env, False)} & 1023) % {a}.count.i64()].f{r.randint(0, 1)} <- {self.expr(env, 2)}")
            env["__sarrs"].append(a)
            return out
        if k2 < 0.7 and "when" in self.f:
            v = r.choice(mutable_ints)
            return [f"{sp}{v} <- ({v} + wt({self.expr(env, 2)})) % {M}"]
        if k2 < 0.8 and "darray" in self.f and env.get("__arrs") and depth > 0:
            a = r.choice(env["__arrs"])
            caps = [v for v in mutable_ints if r.random() < 0.6] or [r.choice(mutable_ints)]
            x = self.fresh("x")
            inner = dict(env); inner[x] = "i64"
            inner["__arrs"] = [b for b in env["__arrs"] if b != a]
            self.in_loop += 1
            body = self.block(inner, ind + 4, r.randint(1, 2), depth - 1, set(caps))
            self.in_loop -= 1
            return [f"{sp}for {x} in {a} |{', '.join(caps)}|:"] + body
        v = r.choice(mutable_ints)
        return [f"{sp}{v} <- ({v} + {self.expr(env, 3)}) % {M}"]

    # ---------------- program ----------------
    def program(self):
        r = self.r
        out = [PRELUDE]
        if "struct" in self.f:
            for i in range(r.randint(1, 2)):
                fields = [f"f{j}" for j in range(r.randint(1, 4))]
                name = f"S{i}"
                self.structs.append((name, fields))
                out.append(f"struct {name}:\n" + "\n".join(f"    {f}: i64" for f in fields) + "\n")
        out.append("global mutable gacc: i64 = 1\n")
        if "cenum" in self.f:
            vals = [r.choice(["", f" = {r.randint(-5, 40)}"]) for _ in range(5)]
            # implicit continuation after an explicit value must stay unique: let stage0 judge
            out.append("const enum K of i64:\n" + "\n".join(f"    {n}{v}" for n, v in zip("ABCDE", vals)) + "\n")
        if "opt" in self.f:
            out.append(f"def ofind(n: i64) -> i64?:\n    null return if n % 3 == 0\n    return n % {M}\n")
            out.append("def oget(n: i64) -> i64:\n    if ofind(n) is v:\n        return v + 1\n    return 0 - 1\n")
        if "sarr" in self.f:
            out.append("struct P:\n    f0: mutable i64\n    f1: mutable i64\n")
        if "when" in self.f:
            rows = sorted(set(r.randint(-3, 6) for _ in range(r.randint(1, 4))))
            body = "\n".join(f"        {k} -> {r.randint(0, 99)}" for k in rows)
            out.append(f"def wt(n: i64) -> i64:\n    return when n % 5:\n{body}\n        _ -> {r.randint(0, 99)}\n")
        if "enum" in self.f:
            self.enum = [("A", True), ("B", False), ("C", True), ("D", False)][: r.randint(2, 4)]
            out.append("enum E:\n" + "\n".join(f"    {n}(x: i64)" if p else f"    {n}" for n, p in self.enum) + "\n")
            arms = []
            for idx, (n, p) in enumerate(self.enum):
                arms.append(f"        E.{n}(x):\n            return (x * {idx + 2} + {idx}) % {M}" if p
                            else f"        E.{n}:\n            return {idx * 11 + 5}")
            out.append("def ev(e: E) -> i64:\n    match e:\n" + "\n".join(arms) + "\n")
        for fi in range(r.randint(1, 5)):
            n = r.randint(0, 3)
            params = [f"p{j}" for j in range(n)]
            env = {p: "i64" for p in params}
            name = f"f{fi}"
            body = self.block(env, 4, r.randint(2, 6), 2, set())
            ints = [l.split(":")[0].strip() for l in body if l.startswith("    v") and ": mutable i64" in l]
            ret = self.expr({**env, **{v: "i64" for v in ints}}, 2)
            sig = ", ".join(f"{p}: i64" for p in params)
            out.append(f"def {name}({sig}) -> i64:\n" + "\n".join(body) + f"\n    return {ret}\n")
            self.funcs.append((name, n))
            self.effectful[name] = "gacc" in "\n".join(body) or any(f"{g}(" in "\n".join(body) for g, e in self.effectful.items() if e)
            if n == 1 and not self.effectful[name]:
                self.unary.append(name)
        main = ["def main() -> i64:", "    ck: mutable i64 = 7"]
        for name, n in self.funcs:
            args = ", ".join(str(r.randint(-50, 50)) for _ in range(n))
            main.append(f"    ck <- (ck * 31 + {name}({args})) % {M}")
            main.append("    pr(ck)")
        main.append("    pr(gacc)")
        main.append("    return ck & 127")
        out.append("\n".join(main) + "\n")
        return "\n".join(out)


ALL_FEATURES = ["u8", "i32", "compound", "ranges", "darray", "struct", "enum", "cenum", "u32", "f64", "opt",
                "query", "fnval", "sarr", "when", "defer", "usize"]


def generate(seed):
    rng = random.Random(seed)
    feats = set(f for f in ALL_FEATURES if rng.random() < 0.5)
    return Gen(rng, feats).program()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--count", type=int, default=1)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    for s in range(a.seed, a.seed + a.count):
        src = generate(s)
        if a.out:
            os.makedirs(a.out, exist_ok=True)
            open(os.path.join(a.out, f"p{s}.elisa"), "w").write(src)
        else:
            print(src)
