#!/usr/bin/env python3
"""Adversarial DIFFERENTIAL tester for stage1.

Method is the differential corpus's, with adversarially CHOSEN inputs rather than a curated
tree: build each program with BOTH compilers, link, run, compare exit codes.

  MATCH     both ran, same exit code
  MISMATCH  both ran, DIFFERENT exit codes      <- a silent wrong answer, the worst outcome
  DECLINE   stage0 built it, stage1 could not   <- an acceptance gap
  SKIP      stage0 could not build it           <- not a parity signal (the program is bad)

Every bug found in this session lived in a shape the compiler's own source never uses, so
the generators below deliberately target those: overload resolution, generic instantiation
naming, extern declarations, container literals in value position, const enums.
"""
import itertools, os, subprocess, sys, tempfile, hashlib

ROOT = os.environ["REPO_ROOT"]
S0 = os.path.expanduser("~/.elisac/elisac")
WRAP = os.path.join(ROOT, "scripts/elisac_stage1.sh")
RT = os.path.join(ROOT, "build/runtime/elisacore_runtime.o")
STD = os.path.join(ROOT, "elisacore_std/elisacore_runtime.elisa")
ENV = dict(os.environ)

def run(cmd, **kw):
    return subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                          stdin=subprocess.DEVNULL, **kw)

def build_and_run(src_path, work, tag):
    """Compile+link+run with one compiler. Returns (ok, exit_code)."""
    obj = os.path.join(work, f"{tag}.o")
    exe = os.path.join(work, tag)
    if tag == "s0":
        r = run([S0, "-emit", "obj", "-o", obj, src_path], timeout=90)
    else:
        r = run(["bash", WRAP, "-o", obj, src_path], env=ENV, timeout=90)
    if r.returncode != 0:
        return (False, None)
    # Same three link recipes the differential corpus uses, in the same order.
    for extra in ([RT], [], [RT, "-L/opt/homebrew/opt/llvm/lib", "-lLLVM"]):
        if run(["clang", "-Wl,-dead_strip", "-o", exe, obj] + extra).returncode == 0:
            break
    else:
        return (False, None)
    try:
        p = subprocess.run([exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           stdin=subprocess.DEVNULL, timeout=10)
        return (True, p.returncode)
    except subprocess.TimeoutExpired:
        return (False, None)

# ---------------------------------------------------------------- generators
# Each yields (name, source). `main` must return a value the two compilers can disagree on:
# a constant would pass even if the wrong function were called, so every body ENCODES which
# path it took.

def gen_overloads():
    """Overload resolution: exact vs generic, arity, and parameter type."""
    types = ["i64", "u8", "bool", "cstr"]
    for i, t in enumerate(types):
        lit = {"i64": "5", "u8": "5.u8()", "bool": "true", "cstr": '"x"'}[t]
        yield (f"ovl_exact_{t}", f"""
def f(x: {t}) -> i64:
    return 1

def f[T](x: T) -> i64:
    return 2

def main() -> i64:
    return f({lit})
""")
    # An exact overload must win even when the generic is declared FIRST.
    yield ("ovl_generic_first", """
def f[T](x: T) -> i64:
    return 2

def f(x: i64) -> i64:
    return 1

def main() -> i64:
    return f(7)
""")
    # Arity overloads alongside a generic.
    yield ("ovl_arity", """
def f(x: i64) -> i64:
    return 1

def f(x: i64, y: i64) -> i64:
    return 2

def f[T](x: T) -> i64:
    return 4

def main() -> i64:
    return f(1) + f(1, 2)
""")
    # Two DISTINCT non-generic overloads: picking the wrong one is a wrong answer.
    yield ("ovl_two_concrete", """
def f(x: i64) -> i64:
    return 1

def f(x: bool) -> i64:
    return 2

def main() -> i64:
    return f(1) + f(true) * 10
""")

def gen_generic_mangling():
    """Generic instantiations that used to collapse to one mangled name."""
    yield ("mangle_cstr_vs_sview", f"""
include "{STD}"

def idy[T](x: T) -> T:
    return x

def main() -> i64:
    can Memory.Allocate, Abort.Panic:
        a: cstr = idy("ab")
        b: sview = idy(sview("cdef", 0, 4))
        return runtime_strlen(a).i64() + b.count.i64()
""")
    yield ("mangle_two_dicts", f"""
include "{STD}"

def main() -> i64:
    can Memory.Allocate, Abort.Panic:
        m: mutable dict[u64, i64] = {{}}
        m <- m.put(1.u64(), 3)
        n: mutable dict[sview, i64] = {{}}
        n <- n.put(sview("k", 0, 1), 4)
        return (m.count + n.count).i64()
""")

def gen_externs():
    """Extern declarations: const-enum params, duplicate C symbols, shared link names."""
    yield ("extern_const_enum", """
const enum FD of int:
    In = 0
    Out = 1

extern probe_a(fd: FD) -> isize

def main() -> i64:
    return FD.Out.i64() + FD.In.i64()
""")
    # Two externs on ONE C symbol with different signatures — LLVM used to uniquify.
    yield ("extern_dup_symbol", f"""
include "{STD}"

extern write(fd: int, buf: void&, count: usize) -> isize

def main() -> i64:
    can Unsafe.PointerCast:
        return 3
""")
    yield ("extern_variadic_like", """
extern snprintf_probe(buf: u8&, n: usize) -> int

def main() -> i64:
    return 4
""")

def gen_container_values():
    """Container literals used as VALUES rather than initialisers."""
    yield ("lit_index", """
def main() -> i64:
    return [10, 20, 30][1]
""")
    yield ("lit_iterate", """
def main() -> i64:
    total: mutable i64 = 0
    for x in [3, 5, 7] |total|:
        total <- total + x
    return total
""")
    yield ("lit_membership_int", """
def main() -> i64:
    a: bool = 2 in [1, 2, 3]
    b: bool = 9 in [1, 2, 3]
    return (1 if a else 0) + (2 if b else 0)
""")
    yield ("lit_membership_str", """
def main() -> i64:
    a: bool = "b" in {"a", "b"}
    b: bool = "z" in {"a", "b"}
    return (1 if a else 0) + (2 if b else 0)
""")
    yield ("lit_nested_index", """
def main() -> i64:
    return [[1, 2], [3, 4]][1][0]
""")

def gen_numeric_edges():
    """Integer width and literal-typing boundaries."""
    cases = [("u8", "255", 255), ("u8", "0", 0), ("i8", "127", 127),
             ("u16", "65535", 65535 % 256), ("i32", "2147483647", 2147483647 % 256)]
    for t, lit, _ in cases:
        yield (f"num_{t}_{lit}", f"""
def main() -> i64:
    x: {t} = {lit}
    return x.i64() % 251
""")
    yield ("num_shift_boundary", """
def main() -> i64:
    x: i64 = 1
    return (x << 62) % 251
""")
    yield ("num_neg_mod", """
def main() -> i64:
    a: i64 = -7
    b: i64 = 3
    return (a % b) + 100
""")

def gen_discard_and_scope():
    """Discarded expressions, shadowing, and value-block scoping."""
    yield ("discard_binary", """
def side(n: i64) -> i64:
    return n

def main() -> i64:
    n: i64 = 5
    n + 1
    side(n)
    return n
""")
    yield ("shadow_loop_accumulator", """
def main() -> i64:
    n: mutable i64 = 100
    for x in [1, 2, 3] |n = 0|:
        n <- n + x
    return n
""")
    yield ("nested_ternary", """
def main() -> i64:
    a: i64 = 3
    return (1 if a == 1 else (2 if a == 2 else 9))
""")

GENERATORS = [gen_overloads, gen_generic_mangling, gen_externs,
              gen_container_values, gen_numeric_edges, gen_discard_and_scope]


def gen_structs_enums():
    """Structs, payload enums, and match arms — shapes with their own symbol/layout rules."""
    yield ("struct_field_roundtrip", """
struct P:
    x: i64
    y: i64

def main() -> i64:
    p: P = P{x: 3, y: 4}
    return p.x * 10 + p.y
""")
    yield ("enum_payload_match", """
enum E:
    A(v: i64)
    B(v: i64)

def pick(e: E) -> i64:
    match e:
        E.A(v):
            return v
        E.B(v):
            return v * 10
    return 0

def main() -> i64:
    return pick(E.A(2)) + pick(E.B(3))
""")
    yield ("const_enum_arith", """
const enum C of int:
    Lo = 2
    Hi = 5

def main() -> i64:
    return C.Hi.i64() * 10 + C.Lo.i64()
""")
    yield ("struct_overload", """
struct A:
    v: i64

struct B:
    v: i64

def f(a: A) -> i64:
    return 1

def f(b: B) -> i64:
    return 2

def main() -> i64:
    return f(A{v: 0}) + f(B{v: 0}) * 10
""")

def gen_control_flow():
    """Control flow with early exits, guards, and postfix forms."""
    yield ("postfix_guard_chain", """
def classify(n: i64) -> i64:
    1 return if n < 0
    2 return if n == 0
    return 3

def main() -> i64:
    return classify(-1) + classify(0) * 10 + classify(5) * 100
""")
    yield ("while_break_continue", """
def main() -> i64:
    total: mutable i64 = 0
    i: mutable i64 = 0
    while i < 10 |total, i|:
        i <- i + 1
        continue if i % 2 == 0
        break if i > 7
        total <- total + i
    return total
""")
    yield ("nested_loop_labels", """
def main() -> i64:
    total: mutable i64 = 0
    for a in [1, 2, 3] |total|:
        for b in [10, 20] |total|:
            total <- total + a * b
    return total % 251
""")

def gen_refs_optionals():
    """References and optionals — the ABI shapes that produced past divergences."""
    yield ("optional_bind", """
def find(n: i64) -> i64?:
    return null if n < 0
    return n

def main() -> i64:
    a: i64 = 7
    if find(3) is v:
        a <- a + v
    if find(-1) is w:
        a <- a + 100
    return a
""")
    yield ("ref_param_mutation", """
def bump(x: mutable i64&) -> void:
    x <- x + 5

def main() -> i64:
    n: mutable i64 = 2
    bump(&n)
    return n
""")
    yield ("addr_of_index", """
def main() -> i64:
    can Memory.Allocate, Abort.Panic:
        xs: mutable darray[i64] = []
        xs.push(4)
        xs.push(9)
        p: i64& = &xs[1]
        return p
""")

GENERATORS += [gen_structs_enums, gen_control_flow, gen_refs_optionals]



def gen_casts_arith():
    """Casts and arithmetic at width boundaries — where a wrong answer is silent."""
    for a, b in [(7, 3), (-7, 3), (7, -3), (-7, -3)]:
        yield (f"divmod_{a}_{b}".replace("-", "n"), f"""
def main() -> i64:
    a: i64 = {a}
    b: i64 = {b}
    return ((a / b) * 7 + (a % b)) + 100
""")
    for t, v in [("u8", 200), ("u16", 40000), ("i8", -100), ("i32", -70000)]:
        yield (f"cast_roundtrip_{t}", f"""
def main() -> i64:
    x: {t} = {v}
    y: i64 = x.i64()
    z: {t} = y.{t}()
    return (z.i64() - x.i64()) + 50
""")
    yield ("shift_widths", """
def main() -> i64:
    a: u8 = 1
    b: u8 = (a.i64() << 7).u8()
    c: i64 = 1
    return (b.i64() % 131) + ((c << 40) % 97)
""")
    yield ("unsigned_compare", """
def main() -> i64:
    a: u64 = 18446744073709551615.u64()
    b: u64 = 1.u64()
    return 30 if a > b else 7
""")
    yield ("bitops", """
def main() -> i64:
    a: i64 = 0b1011
    b: i64 = 0b0110
    return (a & b) * 100 + (a | b) * 10 + (a ^ b)
""")

def gen_strings():
    """sview/cstr operations — content vs pointer comparison is a classic silent divergence."""
    yield ("sview_eq_content", f"""
include "{STD}"

def main() -> i64:
    can Memory.Allocate, Abort.Panic:
        a: sview = sview("hello", 0, 5)
        b: sview = sview("hello", 0, 5)
        c: sview = sview("world", 0, 5)
        return (10 if a == b else 0) + (3 if a == c else 1)
""")
    yield ("sview_index_len", f"""
include "{STD}"

def main() -> i64:
    can Memory.Allocate, Abort.Panic:
        s: sview = sview("abcd", 0, 4)
        return s.count.i64() * 10 + (s[1] - 96).i64()
""")

def gen_generics_multi():
    """Multi-parameter generics and repeated instantiation at different types."""
    yield ("generic_two_params", """
def pair_first[A, B](a: A, b: B) -> A:
    return a

def main() -> i64:
    x: i64 = pair_first[i64, bool](7, true)
    y: i64 = pair_first[i64, i64](3, 9)
    return x * 10 + y
""")
    yield ("generic_same_fn_two_types", """
def idy[T](x: T) -> T:
    return x

def main() -> i64:
    a: i64 = idy(5)
    b: u8 = idy(3.u8())
    return a * 10 + b.i64()
""")

def gen_match_exhaustive():
    """Match arms, guards, and fallthrough order."""
    yield ("match_guard_order", """
def classify(n: i64) -> i64:
    return match n:
        0: 1
        1: 2
        _: 3

def main() -> i64:
    return classify(0) + classify(1) * 10 + classify(9) * 100
""")
    yield ("match_bool", """
def main() -> i64:
    b: bool = true
    return match b:
        true: 4
        false: 9
""")

GENERATORS += [gen_casts_arith, gen_strings, gen_generics_multi, gen_match_exhaustive]


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    results = {"MATCH": [], "MISMATCH": [], "DECLINE": [], "PERMISSIVE": [], "SKIP": []}
    work = tempfile.mkdtemp()
    progs = []
    for g in GENERATORS:
        if only and only not in g.__name__:
            continue
        progs.extend(g())
    for name, src in progs:
        d = os.path.join(work, name)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, "p.elisa")
        open(path, "w").write(src.lstrip("\n"))
        ok0, rc0 = build_and_run(path, d, "s0")
        if not ok0:
            # stage0 REFUSED it. If stage1 builds and runs the same program, stage1 is more
            # PERMISSIVE than the reference compiler — a real divergence, and one no census
            # here can otherwise see: the decline census counts what stage1 REFUSES, never
            # what it wrongly ACCEPTS. Reported separately from SKIP so the two are not
            # conflated; a genuinely malformed generator program lands in SKIP.
            ok1p, _ = build_and_run(path, d, "s1")
            results["PERMISSIVE" if ok1p else "SKIP"].append((name, None, None))
            continue
        # A CRASHING oracle cannot arbitrate. differential_corpus skips a stage0 timeout for
        # the same reason; a negative code is a signal (observed: -11 SIGSEGV on a program
        # returning a ref from a value function). Counting it as a mismatch cries wolf, and a
        # gate that cries wolf trains the next REAL wrong answer to be waved through.
        if rc0 is not None and rc0 < 0:
            results["SKIP"].append((name, rc0, None)); continue
        ok1, rc1 = build_and_run(path, d, "s1")
        if not ok1:
            results["DECLINE"].append((name, rc0, None)); continue
        if rc0 != rc1:
            results["MISMATCH"].append((name, rc0, rc1))
        else:
            results["MATCH"].append((name, rc0, rc1))
    for k in ("MISMATCH", "DECLINE", "PERMISSIVE", "SKIP", "MATCH"):
        for name, rc0, rc1 in results[k]:
            if k == "MATCH":
                continue
            extra = f"  stage0={rc0} stage1={rc1}" if rc0 is not None else ""
            print(f"  {k:9s} {name}{extra}")
    print(f"\nadversarial: {len(progs)} programs — "
          f"{len(results['MATCH'])} match, {len(results['MISMATCH'])} MISMATCH, "
          f"{len(results['DECLINE'])} declined, "
          f"{len(results['PERMISSIVE'])} PERMISSIVE (stage0 rejects, stage1 builds), "
          f"{len(results['SKIP'])} skipped")
    print(f"work dir: {work}")
    return 1 if results["MISMATCH"] else 0

if __name__ == "__main__":
    sys.exit(main())
