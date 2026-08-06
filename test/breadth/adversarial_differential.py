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
        return runtime_strlen(a).i64() + b.len.i64()
""")
    yield ("mangle_two_dicts", f"""
include "{STD}"

def main() -> i64:
    can Memory.Allocate, Abort.Panic:
        m: mutable dict[u64, i64] = {{}}
        m <- m.put(1.u64(), 3)
        n: mutable dict[cstr, i64] = {{}}
        n <- n.put("k", 4)
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
    null return if n < 0
    return n

def main() -> i64:
    a: mutable i64 = 7
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
    a: i64 = 0xB
    b: i64 = 0x6
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
        return s.len.i64() * 10 + (s[1] - 96).i64()
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


def gen_when_tables():
    """`when` decision tables. The MULTI-COLUMN form had no backend lowering at all until
    2026-08-06, so nothing here was ever differentially checked; the single-column form is
    covered too because both share the arm machinery. Every row returns a distinct value, so
    a row that hits the WRONG way is a wrong answer rather than a decline."""
    yield ("when_two_columns", """
def pick(a: i64, b: i64) -> i64:
    return when a, b:
        0, 0 -> 11
        0, 1 -> 22
        1, 0 -> 33
        _, _ -> 44

def main() -> i64:
    return pick(0, 1) + pick(1, 0) + pick(9, 9)
""")
    # ORDER-INDEPENDENCE: the `_` row is written in the MIDDLE. A `when` is an unordered
    # table, so the later specific row must still win — the parser moves the default last.
    # Under plain `match` first-wins semantics this would answer 44.
    yield ("when_default_in_middle", """
def pick(a: i64, b: i64) -> i64:
    return when a, b:
        0, 0 -> 11
        _, _ -> 44
        1, 1 -> 33

def main() -> i64:
    return pick(1, 1)
""")
    yield ("when_or_and_range_columns", """
def pick(a: i64, b: i64) -> i64:
    return when a, b:
        1 | 2, 0..<5 -> 7
        3, _ -> 8
        _, _ -> 9

def main() -> i64:
    return pick(2, 4) * 100 + pick(3, 99) * 10 + pick(8, 8)
""")
    # A `_` row is required even here, where the four combinations ARE spelled out: a tuple
    # domain is the PRODUCT of its columns, and stage0 asks for the final row regardless.
    yield ("when_bool_columns", """
def pick(a: bool, b: bool) -> i64:
    return when a, b:
        true, true -> 1
        true, false -> 2
        false, true -> 3
        _, _ -> 4

def main() -> i64:
    return pick(true, false) * 10 + pick(false, false)
""")
    # Columns must be DISJOINT (docs/125 R1): `'a', _` would overlap `'a', 'b'`, so the
    # second row narrows on the other column instead.
    yield ("when_char_columns", """
def pick(a: char, b: char) -> i64:
    return when a, b:
        'a', 'b' -> 5
        'q', 'q' -> 6
        _, _ -> 7

def main() -> i64:
    return pick('a', 'b') * 100 + pick('q', 'q') * 10 + pick('z', 'z')
""")
    yield ("when_const_enum_columns", """
const enum Side of u8:
    Left
    Right

def pick(s: Side, n: i64) -> i64:
    return when s, n:
        Side.Left, 1 -> 3
        Side.Right, 1 -> 4
        _, _ -> 5

def main() -> i64:
    return pick(Side.Right, 1) * 10 + pick(Side.Left, 9)
""")
    yield ("when_in_local_and_nested", """
def pick(a: i64, b: i64) -> i64:
    inner: i64 = when a, b:
        0, 0 -> 2
        _, _ -> 3
    outer: i64 = when inner, a:
        2, 0 -> 40
        _, _ -> 50
    return outer

def main() -> i64:
    return pick(0, 0) + pick(1, 1)
""")
    yield ("when_single_column_range", """
def classify(c: char) -> i64:
    return when c:
        '0'..='9' -> 1
        'a'..='z' -> 2
        _ -> 3

def main() -> i64:
    return classify('5') * 100 + classify('q') * 10 + classify('!')
""")


def gen_defer_region():
    """`defer block:` ordering and region blocks — statement forms whose ORDER is the answer.
    Deferred blocks run LIFO during unwind, so the trace digit order IS the property."""
    yield ("defer_lifo_order", """
global mutable trace: i64 = 0

def note(n: i64) -> void:
    trace <- trace * 10 + n

def run() -> void:
    defer block:
        note(1)
    defer block:
        note(2)
    note(3)

def main() -> i64:
    run()
    return trace
""")
    yield ("defer_runs_on_early_return", """
global mutable trace: i64 = 0

def note(n: i64) -> void:
    trace <- trace * 10 + n

def run(early: bool) -> i64:
    defer block:
        note(1)
    if early:
        note(2)
        return 5
    note(3)
    return 6

def main() -> i64:
    _ = run(true)
    return trace
""")
    # SCOPE exits: a `defer block:` belongs to the scope that declared it, so it runs per
    # loop ITERATION and at the end of a `region` body — not once at function exit.
    yield ("defer_per_loop_iteration", """
global mutable trace: i64 = 0

def note(n: i64) -> void:
    trace <- trace * 10 + n

def run() -> void:
    for i in 0..<2:
        defer block:
            note(1)
        note(2)

def main() -> i64:
    run()
    return trace % 251
""")
    yield ("defer_at_region_end", """
global mutable trace: i64 = 0

def note(n: i64) -> void:
    trace <- trace * 10 + n

def run() -> void:
    region scratch:
        defer block:
            note(1)
        note(2)
    note(3)

def main() -> i64:
    run()
    return trace
""")
    # A `raise` is a function exit and unwinds `defer` exactly as `return` does.
    yield ("defer_on_raise_path", """
global mutable trace: i64 = 0

error Bad:
    Boom

def note(n: i64) -> void:
    trace <- trace * 10 + n

def run(x: i64) -> i64 error[Bad]:
    defer block:
        note(1)
    raise Bad.Boom if x < 0
    note(2)
    return x

def main() -> i64:
    catch run(-1):
        v:
            note(3)
        error e:
            note(4)
    return trace
""")
    # `break` / `continue` jump past the end-of-iteration unwind and must run it themselves.
    yield ("defer_with_break", """
global mutable trace: i64 = 0

def note(n: i64) -> void:
    trace <- trace * 10 + n

def run() -> void:
    for i in 0..<4:
        defer block:
            note(1)
        note(2)
        break if i == 1

def main() -> i64:
    run()
    return trace % 251
""")
    yield ("defer_with_continue", """
global mutable trace: i64 = 0

def note(n: i64) -> void:
    trace <- trace * 10 + n

def run() -> void:
    for i in 0..<3:
        defer block:
            note(1)
        continue if i == 1
        note(2)

def main() -> i64:
    run()
    return trace % 251
""")
    # Nested regions: the inner defer runs at the INNER end.
    yield ("defer_nested_regions", """
global mutable trace: i64 = 0

def note(n: i64) -> void:
    trace <- trace * 10 + n

def run() -> void:
    region outer:
        defer block:
            note(1)
        region inner:
            defer block:
                note(2)
            note(3)
        note(4)

def main() -> i64:
    run()
    return trace % 251
""")
    # A match ARM body and an `if` BRANCH are statement lists too.
    yield ("defer_in_match_arm", """
global mutable trace: i64 = 0

def note(n: i64) -> void:
    trace <- trace * 10 + n

def run(n: i64) -> void:
    match n:
        0:
            defer block:
                note(1)
            note(2)
        _:
            note(3)
    note(4)

def main() -> i64:
    run(0)
    return trace
""")
    yield ("region_block_value_survives", """
def build() -> i64:
    total: mutable i64 = 0
    region scratch:
        xs: mutable darray[i64] = []
        xs.push(4)
        xs.push(5)
        total <- (xs[0] can Unsafe.UncheckedIndex) + (xs[1] can Unsafe.UncheckedIndex)
    return total

def main() -> i64:
    return build()
""")


def gen_error_unions():
    """Error unions through the i32-status + out-param ABI, in each position. Every catch arm
    ENDS WITH AN EXPRESSION — stage0 rejects an arm whose last statement is an assignment."""
    yield ("error_catch_success_and_failure", """
error Bad:
    Boom

def half(x: i64) -> i64 error[Bad]:
    raise Bad.Boom if x < 0
    return x / 2

def use(x: i64) -> i64:
    catch half(x):
        v:
            return v
        error e:
            return 100

def main() -> i64:
    return use(84) + use(-1)
""")
    # stage0 reads a `catch` arm as a MATCH EXPRESSION arm: it must end with an expression,
    # and an arm ending in an ASSIGNMENT is rejected. stage1 used to accept this program —
    # a PERMISSIVE divergence, the direction no decline census can see. Kept as a generator
    # rather than a diagnostics fixture because stage0 follows the per-arm message with a
    # second one ("catch expression arms are incompatible") that stage1 does not model; what
    # matters, and what this pins, is that both compilers REJECT it.
    yield ("catch_arm_ends_with_assignment", """
error Bad:
    Boom

def g(x: i64) -> i64 error[Bad]:
    return x

def main() -> i64:
    t: mutable i64 = 0
    catch g(1):
        v:
            t <- v
        error e:
            t <- 9
    return t
""")
    # The same shape with expression tails — accepted by both, so the rule above cannot be
    # over-firing.
    yield ("catch_arm_ends_with_expression", """
error Bad:
    Boom

def g(x: i64) -> i64 error[Bad]:
    return x

def main() -> i64:
    t: mutable i64 = 0
    catch g(1):
        v:
            t <- v
            0
        error e:
            0
    return t
""")
    yield ("error_try_propagates", """
error Bad:
    Boom

def inner(x: i64) -> i64 error[Bad]:
    raise Bad.Boom if x < 0
    return x + 1

def outer(x: i64) -> i64 error[Bad]:
    v: i64 = try inner(x)
    return v * 2

def main() -> i64:
    catch outer(20):
        v:
            return v
        error e:
            return 1
""")


def gen_struct_defaults():
    """Struct field defaults — the `= default` initializer, whose value was PARSED and then
    discarded until 2026-08-06 (fields silently zero-filled instead)."""
    yield ("struct_default_omitted_field", """
struct Config:
    width: i64 = 7
    height: i64 = 3

def main() -> i64:
    a: Config = Config{}
    b: Config = Config{width: 10}
    return a.width * a.height + b.width + b.height
""")
    yield ("struct_default_all_given", """
struct Config:
    width: i64 = 7
    height: i64 = 3

def main() -> i64:
    c: Config = Config{width: 2, height: 5}
    return c.width * c.height
""")


def gen_lambdas_closures():
    """Closures capturing several values, and higher-order returns."""
    yield ("closure_two_captures", """
def apply(fn: fn(i64) -> i64, v: i64) -> i64:
    return fn(v)

def run() -> i64:
    a: i64 = 3
    b: i64 = 10
    return apply(fn(x) => x * a + b, 4)

def main() -> i64:
    return run()
""")
    yield ("higher_order_two_levels", """
def adder(n: i64) -> fn(i64) -> i64:
    return fn(x) => x + n

def main() -> i64:
    f: fn(i64) -> i64 = adder(2)
    g: fn(i64) -> i64 = adder(30)
    return f(1) + g(1)
""")


GENERATORS += [gen_when_tables, gen_defer_region, gen_error_unions,
               gen_struct_defaults, gen_lambdas_closures]


def gen_loops_control():
    """Loop control flow: `break`/`continue` interaction with accumulators, nested loops, and
    the loop-variable's final value. Each body encodes the ITERATION PATH, not just a total."""
    yield ("loop_break_in_nested", """
def main() -> i64:
    total: mutable i64 = 0
    for i in 0..<4 |total|:
        for j in 0..<4 |total, i|:
            break if j == 2
            total <- total * 10 + j
    return total % 251
""")
    yield ("loop_continue_skips", """
def main() -> i64:
    total: mutable i64 = 0
    for i in 0..<6 |total|:
        continue if i % 2 == 0
        total <- total * 10 + i
    return total % 251
""")
    yield ("while_with_break", """
def main() -> i64:
    i: mutable i64 = 0
    total: mutable i64 = 0
    while i < 10 |i, total|:
        i <- i + 1
        break if i == 4
        total <- total + i
    return total * 10 + i
""")
    yield ("loop_inclusive_vs_exclusive", """
def main() -> i64:
    a: mutable i64 = 0
    for i in 0..<3 |a|:
        a <- a + 1
    b: mutable i64 = 0
    for i in 0..=3 |b|:
        b <- b + 1
    return a * 10 + b
""")
    yield ("loop_stepped_range", """
def main() -> i64:
    total: mutable i64 = 0
    for i in 0..<10..3 |total|:
        total <- total * 10 + i
    return total % 251
""")


def gen_optionals_refs():
    """Optionals and references — layout-sensitive shapes where a wrong niche reads as data."""
    yield ("optional_absent_vs_zero", """
def pick(n: i64) -> i64?:
    return null if n == 0 else 0

def main() -> i64:
    a: i64 = 1 if pick(0) is v0 else 2
    b: i64 = 3 if pick(5) is v1 else 4
    return a * 10 + b
""")
    yield ("optional_ref_niche", """
struct P:
    x: i64

def find(p: P&, want: bool) -> P&?:
    return p if want else null

def main() -> i64:
    p: P = P{x: 7}
    hit: i64 = 1 if find(&p, true) is r0 else 2
    miss: i64 = 3 if find(&p, false) is r1 else 4
    return hit * 10 + miss
""")
    yield ("ref_param_mutation", """
def bump(n: mutable i64&) -> void:
    n <- n + 5

def main() -> i64:
    x: mutable i64 = 3
    bump(x)
    bump(x)
    return x
""")
    yield ("nested_optional_chain", """
def outer(n: i64) -> i64?:
    inner: i64? = null if n < 0 else n * 2
    if inner is v:
        return v + 1
    return null

def main() -> i64:
    a: mutable i64 = 0
    if outer(3) is x:
        a <- x
    b: mutable i64 = 0
    if outer(-1) is y:
        b <- y
    return a * 10 + b
""")


def gen_ufcs_modules():
    """UFCS method-call spelling and module-qualified names — resolution paths a plain call
    never exercises."""
    yield ("ufcs_vs_direct", """
def twice(n: i64) -> i64:
    return n * 2

def main() -> i64:
    return twice(3) * 10 + 3.twice()
""")
    yield ("module_qualified_call", """
module M:
    def f(n: i64) -> i64:
        return n + 1

def f(n: i64) -> i64:
    return n + 100

def main() -> i64:
    return M::f(1) * 100 + f(1)
""")
    yield ("ufcs_chain", """
def inc(n: i64) -> i64:
    return n + 1

def dbl(n: i64) -> i64:
    return n * 2

def main() -> i64:
    return 3.inc().dbl()
""")


def gen_arrays_fixed():
    """Fixed-size arrays: element addressing and 2D indexing, where a stride bug is silent."""
    yield ("fixed_array_index", """
def main() -> i64:
    xs: i64[4] = [10, 20, 30, 40]
    return (xs[0] can Unsafe.UncheckedIndex) + (xs[3] can Unsafe.UncheckedIndex) * 2
""")
    yield ("fixed_array_write_then_read", """
def main() -> i64:
    xs: mutable i64[3] = [1, 2, 3]
    xs[1] <- 9
    return (xs[0] can Unsafe.UncheckedIndex) * 100 + (xs[1] can Unsafe.UncheckedIndex) * 10 + (xs[2] can Unsafe.UncheckedIndex)
""")
    yield ("array_iteration_sum", """
def main() -> i64:
    xs: i64[4] = [1, 2, 3, 4]
    total: mutable i64 = 0
    for x in xs |total|:
        total <- total * 10 + x
    return total % 251
""")


def gen_struct_methods():
    """Struct-typed values through calls and returns, plus a struct with mixed field widths —
    layout is invisible to an exit code unless every field is READ BACK."""
    yield ("struct_mixed_widths", """
struct Mixed:
    a: u8
    b: i64
    c: bool

def mk() -> Mixed:
    return Mixed{a: 7.u8(), b: 300, c: true}

def main() -> i64:
    m: Mixed = mk()
    flag: i64 = 1 if m.c else 0
    return m.a.i64() * 1000 + m.b + flag
""")
    yield ("struct_by_ref_mutation", """
struct Counter:
    n: mutable i64

def bump(c: mutable Counter&) -> void:
    c.n <- c.n + 2

def main() -> i64:
    c: mutable Counter = Counter{n: 1}
    bump(c)
    bump(c)
    return c.n
""")
    yield ("struct_nested_field", """
struct Inner:
    v: i64

struct Outer:
    left: Inner
    right: Inner

def main() -> i64:
    o: Outer = Outer{left: Inner{v: 3}, right: Inner{v: 8}}
    return o.left.v * 10 + o.right.v
""")


GENERATORS += [gen_loops_control, gen_optionals_refs, gen_ufcs_modules,
               gen_arrays_fixed, gen_struct_methods]


def gen_comprehensions():
    """Comprehensions and queries — the construct the language exists to vectorize, and one
    whose result is a CONTAINER, so a wrong element order or a dropped filter is silent."""
    yield ("comprehension_filtered", """
def main() -> i64:
    xs: darray[i64] = [i for i in 0..<8 if i % 3 == 1]
    total: mutable i64 = 0
    for x in xs |total|:
        total <- total * 10 + x
    return total
""")
    yield ("comprehension_mapped", """
def main() -> i64:
    xs: darray[i64] = [i * 2 + 1 for i in 0..<4]
    total: mutable i64 = 0
    for x in xs |total|:
        total <- total + x
    return total
""")
    yield ("comprehension_over_literal", """
def main() -> i64:
    xs: darray[i64] = [x * x for x in [1, 2, 3]]
    return (xs[0] can Unsafe.UncheckedIndex) * 100 + (xs[1] can Unsafe.UncheckedIndex) * 10 + (xs[2] can Unsafe.UncheckedIndex)
""")


def gen_casts_widths():
    """Width casts and sign extension — a wrong extension is invisible until the value is
    read back at a different width."""
    yield ("cast_narrow_then_widen", """
def main() -> i64:
    big: i64 = 300
    narrowed: u8 = big.u8()
    return narrowed.i64()
""")
    yield ("cast_sign_extension", """
def main() -> i64:
    small: i8 = -2
    widened: i64 = small.i64()
    return widened + 100
""")
    yield ("cast_unsigned_no_sign_extend", """
def main() -> i64:
    small: u8 = 254
    widened: i64 = small.i64()
    return widened % 251
""")
    yield ("cast_roundtrip_u32", """
def main() -> i64:
    a: i64 = 70000
    b: u32 = a.u32()
    c: u16 = b.u16()
    return c.i64() % 251
""")


def gen_payload_enums():
    """Payload enums: multi-field payloads and per-variant binding, where a wrong slot reads
    a neighbouring field."""
    yield ("penum_two_fields", """
enum Shape:
    Rect(i64, i64)
    Dot

def area(s: Shape) -> i64:
    return match s:
        Shape.Rect(w, h): w * 10 + h
        Shape.Dot: 99

def main() -> i64:
    return area(Shape.Rect(3, 4)) + area(Shape.Dot)
""")
    yield ("penum_mixed_widths", """
enum Msg:
    Tag(u8, i64)
    Empty

def read(m: Msg) -> i64:
    return match m:
        Msg.Tag(a, b): a.i64() * 1000 + b
        Msg.Empty: 7

def main() -> i64:
    return read(Msg.Tag(5.u8(), 42)) + read(Msg.Empty)
""")
    yield ("penum_variant_order", """
enum E:
    A(i64)
    B(i64)
    C(i64)

def pick(e: E) -> i64:
    return match e:
        E.A(v): v + 100
        E.B(v): v + 200
        E.C(v): v + 300

def main() -> i64:
    return pick(E.B(1)) - pick(E.A(1))
""")


def gen_bit_operations():
    """Shifts and masks at type boundaries — where an implicit width promotion changes the
    answer without changing the program's shape."""
    yield ("shift_u8_wraps", """
def main() -> i64:
    x: u8 = 200
    y: u8 = (x << 1.u8())
    return y.i64() % 251
""")
    yield ("mask_and_or_xor", """
def main() -> i64:
    a: i64 = 0xC
    b: i64 = 0xA
    return (a & b) * 100 + (a | b) * 10 + (a ^ b)
""")
    yield ("right_shift_signed", """
def main() -> i64:
    a: i64 = -16
    return (a >> 2) + 100
""")


def gen_generic_structs():
    """Generic STRUCTS instantiated at more than one argument — the mangling path that
    collapsed two instantiations into one before."""
    yield ("generic_struct_two_args", """
struct Box[T]:
    v: T

def unbox[T](b: Box[T]) -> T:
    return b.v

def main() -> i64:
    a: Box[i64] = Box[i64]{v: 40}
    b: Box[u8] = Box[u8]{v: 2.u8()}
    return unbox(a) + unbox(b).i64()
""")
    yield ("generic_nested_instantiation", """
struct Box[T]:
    v: T

def main() -> i64:
    inner: Box[i64] = Box[i64]{v: 7}
    outer: Box[Box[i64]] = Box[Box[i64]]{v: inner}
    return outer.v.v * 6
""")
    yield ("generic_fn_two_instantiations", """
def pick[T](a: T, b: T, first: bool) -> T:
    return a if first else b

def main() -> i64:
    n: i64 = pick(3, 9, true)
    c: u8 = pick(1.u8(), 2.u8(), false)
    return n * 10 + c.i64()
""")


GENERATORS += [gen_comprehensions, gen_casts_widths, gen_payload_enums,
               gen_bit_operations, gen_generic_structs]


def gen_std_containers():
    """The STD's containers through their real API — dict/set/darray/f-string. These need the
    std in the unit, which is a different acceptance path from the bare programs above."""
    yield ("std_dict_put_get_overwrite", f"""
include "{STD}"

def main() -> i64 can[Abort.Panic, Memory.Allocate]:
    m: mutable dict[i64, i64] = {{}}
    m <- m.put(1, 10)
    m <- m.put(2, 20)
    m <- m.put(1, 30)
    total: mutable i64 = m.count.i64() * 100
    if m.get(1) is v:
        total <- total + v
    if m.get(9) is w:
        total <- total + 1
    return total % 251
""")
    yield ("std_set_dedup_and_membership", f"""
include "{STD}"

def main() -> i64 can[Abort.Panic, Memory.Allocate]:
    s: mutable set[i64] = {{}}
    _ = s.add(3)
    _ = s.add(3)
    _ = s.add(4)
    a: i64 = 1 if 3 in s else 0
    b: i64 = 1 if 9 in s else 0
    return s.count.i64() * 100 + a * 10 + b
""")
    yield ("std_darray_push_pop", f"""
include "{STD}"

def main() -> i64 can[Abort.Panic, Memory.Allocate]:
    xs: mutable darray[i64] = []
    xs.push(1)
    xs.push(2)
    xs.push(3)
    popped: i64 = xs.pop()
    return xs.count.i64() * 100 + popped * 10 + (xs[0] can Unsafe.UncheckedIndex)
""")
    yield ("std_fstring_interpolation", f"""
include "{STD}"

def main() -> i64 can[Abort.Panic, Memory.Allocate]:
    a: dstr = "ab"
    b: dstr = "cde"
    s: dstr = f"{{a}}-{{b}}!"
    return s.count.i64() * 10 + (s[3] can Unsafe.UncheckedIndex).i64() % 10
""")


GENERATORS += [gen_std_containers]


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
    # RATCHET. All three of these are at zero and must stay there:
    #   MISMATCH   a silent wrong answer — the worst outcome there is
    #   DECLINE    stage0 built it, stage1 could not (an acceptance gap)
    #   PERMISSIVE stage0 rejects it, stage1 builds it (the direction no census can see)
    # SKIP is not ratcheted: it means the ORACLE could not arbitrate (stage0 rejects the
    # program, or crashes on it), which says nothing about stage1. Keep those few honest by
    # fixing the generator program rather than by tolerating the skip.
    return 1 if results["MISMATCH"] or results["DECLINE"] or results["PERMISSIVE"] else 0

if __name__ == "__main__":
    sys.exit(main())
