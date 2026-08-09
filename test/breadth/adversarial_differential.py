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

WHAT THIS HARNESS STRUCTURALLY CANNOT COVER (checked 2026-08-08, don't re-derive it):
every program here is BARE MODE -- standalone source with no std include, linked against
elisacore_runtime.o. So any construct whose operands are STD TYPES is unreachable from
here no matter how the generator is written:

  * `parallel for` / `nursery` / `pool`. stage0 requires the iterable to be a mutable
    Slice[T], a frozen packed store, or a readonly dense view -- a plain darray is
    rejected outright ("not structurally shareable across threads"), and `Slice` is a std
    type (elisacore_std/elisacore_runtime_slice.elisa), so bare mode cannot even name it.
    These are NOT untested overall: test/parity/parallel_for_grant_smoke.sh covers the
    effect-grant and outer-mutation rules, and the std itself uses them, so the self-host
    exercises the codegen. They are simply out of scope for THIS corpus.
  * Anything else requiring a std container/protocol (Slice, MemoryPool, dict/set
    internals) for the same reason.

A zero mention-count for one of those in this file is therefore expected, not a gap to
close here. Prefer the parity smokes for them.
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
    """Compile+link+run with one compiler. Returns (ok, exit_code).

    `s1O2` is stage1 through the real `default<O2>` pass pipeline. Optimisation must never
    change an answer, and a miscompile that only appears optimised is invisible to every
    other check here — the module datalayout bug was exactly that shape."""
    obj = os.path.join(work, f"{tag}.o")
    exe = os.path.join(work, tag)
    if tag == "s0":
        r = run([S0, "-emit", "obj", "-o", obj, src_path], timeout=90)
    elif tag == "s1O2":
        r = run(["bash", WRAP, "-O2", "-o", obj, src_path], env=ENV, timeout=180)
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


def gen_defaults_and_named_args():
    """Default parameter values and named arguments — resolution paths where picking the
    wrong default is a wrong ANSWER, not a decline."""
    yield ("default_arg_omitted_and_given", """
def scale(v: i64, by: i64 = 3) -> i64:
    return v * by

def main() -> i64:
    return scale(2) * 10 + scale(2, 4)
""")
    yield ("default_arg_two_defaults", """
def mix(a: i64, b: i64 = 2, c: i64 = 5) -> i64:
    return a * 100 + b * 10 + c

def main() -> i64:
    return mix(1) - mix(1, 3) + mix(1, 3, 4)
""")
    yield ("named_argument_order", """
def sub(a: i64, b: i64) -> i64:
    return a - b

def main() -> i64:
    return sub(b: 3, a: 10)
""")


def gen_multi_assign():
    """Multi-target assignment and swap — the form where a fresh slot per target silently
    reads uninitialised stack (fixed once; this holds it)."""
    yield ("multi_assign_swap", """
def main() -> i64:
    a: mutable i64 = 3
    b: mutable i64 = 7
    a, b <- b, a
    return a * 10 + b
""")
    yield ("multi_assign_from_calls", """
def one() -> i64:
    return 1

def two() -> i64:
    return 2

def main() -> i64:
    a: mutable i64 = 0
    b: mutable i64 = 0
    a, b <- one(), two()
    return a * 10 + b
""")


def gen_sview_slicing():
    """sview slicing and comparison — content vs pointer, and clamping at the bounds."""
    yield ("sview_slice_and_compare", f"""
include "{STD}"

def main() -> i64 can[Memory.Allocate, Abort.Panic]:
    s: sview = sview("abcdef", 0, 6)
    head: sview = string_view_slice(s, 0, 3)
    rest: sview = string_view_slice(s, 3, 6)
    same: sview = sview("abc", 0, 3)
    return (100 if head == same else 0) + (10 if head == rest else 0) + head.len.i64()
""")
    yield ("sview_slice_clamped", f"""
include "{STD}"

def main() -> i64 can[Memory.Allocate, Abort.Panic]:
    s: sview = sview("abc", 0, 3)
    over: sview = string_view_slice(s, 1, 99)
    return over.len.i64() * 10 + (over[0] - 96).i64()
""")


def gen_optional_containers():
    """Optionals of aggregates, and an optional stored in a container — layouts where the
    niche and the payload can disagree."""
    yield ("optional_struct_roundtrip", """
struct P:
    x: i64
    y: i64

def pick(hit: bool) -> P?:
    return P{x: 4, y: 5} if hit else null

def main() -> i64:
    total: mutable i64 = 0
    if pick(true) is p:
        total <- p.x * 10 + p.y
    if pick(false) is q:
        total <- total + 100
    return total
""")
    yield ("optional_in_darray", """
def main() -> i64:
    xs: mutable darray[i64?] = []
    xs.push(7)
    xs.push(null)
    total: mutable i64 = 0
    if (xs[0] can Unsafe.UncheckedIndex) is a:
        total <- total + a
    if (xs[1] can Unsafe.UncheckedIndex) is b:
        total <- total + 100
    return total * 10 + xs.count.i64()
""")


GENERATORS += [gen_defaults_and_named_args, gen_multi_assign, gen_sview_slicing,
               gen_optional_containers]


def gen_aggregate_abi():
    """Aggregate ABI: structs returned and passed BY VALUE. A wrong sret/byval decision does
    not crash — it reads a neighbouring field, so every field is read back and weighted."""
    yield ("struct_return_many_fields", """
struct Wide:
    a: i64
    b: i64
    c: i64
    d: i64
    e: i64
    f: i64

def mk(base: i64) -> Wide:
    return Wide{a: base, b: base + 1, c: base + 2, d: base + 3, e: base + 4, f: base + 5}

def main() -> i64:
    w: Wide = mk(1)
    return (w.a * 1 + w.b * 2 + w.c * 3 + w.d * 4 + w.e * 5 + w.f * 6) % 251
""")
    yield ("struct_by_value_param", """
struct Pair:
    x: i64
    y: u8

def sum(p: Pair) -> i64:
    return p.x * 10 + p.y.i64()

def main() -> i64:
    return sum(Pair{x: 4, y: 2.u8()})
""")
    yield ("struct_nested_by_value", """
struct Inner:
    v: i64
    w: u8

struct Outer:
    left: Inner
    right: Inner
    tag: bool

def fold(o: Outer) -> i64:
    flag: i64 = 1 if o.tag else 0
    return o.left.v * 1000 + o.left.w.i64() * 100 + o.right.v * 10 + o.right.w.i64() + flag

def main() -> i64:
    o: Outer = Outer{left: Inner{v: 1, w: 2.u8()}, right: Inner{v: 3, w: 4.u8()}, tag: true}
    return fold(o) % 251
""")
    yield ("generic_struct_return", """
struct Box[T]:
    v: T
    n: i64

def wrap[T](value: T, n: i64) -> Box[T]:
    return Box[T]{v: value, n: n}

def main() -> i64:
    a: Box[i64] = wrap(7, 2)
    b: Box[u8] = wrap(3.u8(), 5)
    return a.v * a.n + b.v.i64() * b.n
""")
    yield ("struct_through_optional_and_ref", """
struct P:
    x: mutable i64
    y: i64

def bump(p: mutable P&) -> void:
    p.x <- p.x + 1

def find(p: P&, want: bool) -> P&?:
    return p if want else null

def main() -> i64:
    p: mutable P = P{x: 1, y: 9}
    bump(p)
    bump(p)
    total: mutable i64 = 0
    if find(&p, true) is r:
        total <- r.x * 10 + r.y
    return total
""")


def gen_queries():
    """Query expressions and comprehensions. The parser DISCARDS the head keyword — `count`,
    `sum`, `any`, `all` all become one Comprehension node and are told apart only by a
    line-keyed side table — so this family is worth pushing on. PERMISSIVE is the outcome
    that found the two divergences here: stage0's query grammar is stricter than stage1's."""
    yield ("query_count_and_sum", """
def main() -> i64:
    xs: darray[i64] = [1, 2, 3, 4, 5]
    return (count x in xs where x > 2) * 10 + (sum y in xs where y > 2)
""")
    yield ("query_any_all", """
def main() -> i64:
    xs: darray[i64] = [1, 2, 3]
    hit: bool = any x in xs where x > 2
    every: bool = all y in xs where y > 0
    none: bool = any z in xs where z > 9
    return (1 if hit else 0) * 100 + (1 if every else 0) * 10 + (1 if none else 0)
""")
    yield ("query_empty_source", """
def main() -> i64:
    xs: darray[i64] = []
    every: bool = all x in xs where x > 0
    return (count y in xs where y > 0) + (1 if every else 0) + 40
""")
    # stage0 REQUIRES the filter on `count` — `sum`/`product` accept the bare form. Measured
    # across the whole keyword family before the parser was tightened to match.
    yield ("query_count_without_where", """
def main() -> i64:
    xs: darray[i64] = [1, 2]
    return count x in xs
""")
    yield ("query_sum_without_where", """
def main() -> i64:
    xs: darray[i64] = [1, 2]
    return sum x in xs
""")
    # A COMPREHENSION filter is `if`; `where` is the query form's and stage0 rejects it here.
    yield ("comprehension_if_filter", """
def main() -> i64:
    xs: darray[i64] = [i for i in 0..<10 if i % 3 == 0]
    return (count y in xs where y >= 0) * 10 + (sum z in xs where z >= 0)
""")
    yield ("comprehension_where_filter", """
def main() -> i64:
    xs: darray[i64] = [i for i in 0..<4 where i > 0]
    return 0
""")


def gen_type_mismatches():
    """Return-type mismatches. PERMISSIVE is the outcome that matters — stage0 rejects these,
    so stage1 must too."""
    yield ("fn_value_returned_as_scalar", """
def apply(f: fn(i64) -> i64, n: i64) -> i64:
    return f

def main() -> i64:
    return 0
""")
    yield ("struct_value_returned_as_scalar", """
struct P:
    x: i64

def g() -> i64:
    return P{x: 1}

def main() -> i64:
    return 0
""")
    # The case that broke the first attempt at the rule above — a struct returned where its
    # own ALIAS is declared (`sview` IS `StringView`) — has no standalone spelling: declaring
    # a local `StringView` collides with the builtin, and stage0 rejects the program for that
    # instead. Its real coverage is the std, through self_host_gen3_smoke and the 574
    # stage0 acceptance cases, both of which the narrowed rule was measured against.
    # The control: the same function returning the RIGHT thing still compiles and runs.
    yield ("fn_value_called_not_returned", """
def apply(f: fn(i64) -> i64, n: i64) -> i64:
    return f(n)

def dbl(x: i64) -> i64:
    return x * 2

def main() -> i64:
    return apply(dbl, 21)
""")


def gen_signedness():
    """Comparisons and division at the SIGNED/UNSIGNED boundary — the classic place a single
    wrong LLVM predicate (slt vs ult, sdiv vs udiv, ashr vs lshr) is a wrong answer and not a
    crash. Each case picks operands where the two predicates disagree."""
    yield ("unsigned_compare_high_bit", """
def main() -> i64:
    a: u8 = 200
    b: u8 = 100
    hi: i64 = 1 if a > b else 0
    lo: i64 = 1 if b < a else 0
    return hi * 10 + lo
""")
    yield ("unsigned_divide_high_bit", """
def main() -> i64:
    a: u8 = 200
    b: u8 = 4
    return (a / b).i64()
""")
    yield ("signed_divide_negative", """
def main() -> i64:
    a: i64 = -200
    b: i64 = 4
    return (a / b) + 100
""")
    yield ("unsigned_shift_right_high_bit", """
def main() -> i64:
    a: u8 = 200
    return (a >> 2.u8()).i64()
""")
    yield ("signed_shift_right_negative", """
def main() -> i64:
    a: i64 = -32
    return (a >> 2) + 100
""")
    yield ("u32_compare_above_i32_max", """
def main() -> i64:
    a: u32 = 3000000000
    b: u32 = 1
    return (1 if a > b else 0) * 10 + (1 if b > a else 0)
""")


def gen_string_escapes():
    """Escape sequences — the answer is a BYTE, so a mis-decoded escape is a wrong number."""
    yield ("escape_bytes", f"""
include "{STD}"

def main() -> i64 can[Memory.Allocate, Abort.Panic]:
    s: sview = sview("a\\tb\\nc", 0, 5)
    return s[1].i64() * 100 + s[3].i64()
""")
    yield ("escape_backslash_and_quote", f"""
include "{STD}"

def main() -> i64 can[Memory.Allocate, Abort.Panic]:
    s: sview = sview("x\\\\y", 0, 3)
    return s.len.i64() * 100 + s[1].i64()
""")
    yield ("char_escape_codes", """
def main() -> i64:
    nl: char = '\\n'
    tab: char = '\\t'
    zero: char = '0'
    return nl.i64() * 1000 + tab.i64() * 100 + zero.i64() % 100
""")


def gen_const_enum_values():
    """Const enums with EXPLICIT values and gaps — the shape where compiling a member to its
    ORDINAL instead of its value once passed every test in the repo."""
    yield ("const_enum_gaps", """
const enum Code of i64:
    Lo = 1
    Mid = 7
    Hi = 9

def main() -> i64:
    return Code.Lo.i64() * 100 + Code.Mid.i64() * 10 + Code.Hi.i64()
""")
    yield ("const_enum_implicit_continuation", """
const enum Step of i64:
    A = 5
    B
    C

def main() -> i64:
    return Step.A.i64() * 100 + Step.B.i64() * 10 + Step.C.i64()
""")
    yield ("const_enum_in_when_columns", """
const enum Code of i64:
    Lo = 1
    Hi = 9

def pick(c: Code, n: i64) -> i64:
    return when c, n:
        Code.Lo, 0 -> 3
        Code.Hi, 0 -> 4
        _, _ -> 5

def main() -> i64:
    return pick(Code.Hi, 0) * 100 + pick(Code.Lo, 0) * 10 + pick(Code.Lo, 1)
""")


def gen_as_bindings():
    """`PATTERN as NAME:` — binds the whole matched value alongside its fields. Newly
    implemented this session across struct/payload-enum/packed-enum x statement/value
    position; zero usage anywhere in the compiler's own corpus, so self-hosting cannot
    exercise it at all. Each program must ENCODE which arm ran AND use the `as`-bound
    whole value distinctly from its unpacked fields, so a fix that binds the wrong thing
    (or the field's value instead of the whole matched value) produces a wrong ANSWER,
    not just a decline.
    """
    yield ("as_struct_statement_match", """
struct Point:
    x: i64
    y: i64

def describe(p: Point) -> i64:
    match p:
        Point{x, y} as whole:
            return whole.x * 100 + whole.y * 10 + x + y
    return 0

def main() -> i64:
    return describe(Point{x: 3, y: 4})
""")
    yield ("as_struct_value_match", """
struct Point:
    x: i64
    y: i64

def describe(p: Point) -> i64:
    result: i64 = match p:
        Point{x, y} as whole:
            whole.x * 100 + whole.y * 10 + x + y
        _:
            0
    return result

def main() -> i64:
    return describe(Point{x: 3, y: 4})
""")
    yield ("as_payload_enum_statement_match", """
enum Shape:
    Circle(r: i64)
    Square(side: i64)

def area_code(s: Shape) -> i64:
    match s:
        Shape.Circle(r) as whole:
            return r * 1000
        Shape.Square(side) as whole:
            return side * 1
    return 0

def main() -> i64:
    return area_code(Shape.Circle(3)) + area_code(Shape.Square(4))
""")
    yield ("as_payload_enum_bare_variant", """
enum Signal:
    Empty
    Full(n: i64)

def code(s: Signal) -> i64:
    match s:
        Signal.Empty as whole:
            return 7
        Signal.Full(n) as whole:
            return n * 2
    return 0

def main() -> i64:
    return code(Signal.Empty) * 100 + code(Signal.Full(5))
""")
    yield ("as_binding_two_arms_disjoint", """
enum Op:
    Add(a: i64, b: i64)
    Neg(a: i64)

def eval(o: Op) -> i64:
    match o:
        Op.Add(a, b) as whole:
            return a + b
        Op.Neg(a) as whole:
            return -a
    return 0

def main() -> i64:
    return eval(Op.Add(2, 3)) * 10 + eval(Op.Neg(9))
""")


def gen_struct_operator_protocols():
    """`impl Add/Eq for MyStruct` dispatched through operator syntax (`+`, `==`, `!=`).
    Landed this session by rewriting the operator to the equivalent explicit method call
    (`left.__add__(right)`) and reusing the existing UFCS/impl-method call machinery — no
    prior corpus usage anywhere (the compiler's own `impl` blocks are all for builtin
    scalar types, never a struct), so self-hosting cannot exercise this at all.
    """
    yield ("struct_add_operator", """
protocol Add:
    def __add__(self: Self, other: Self) -> Self

struct Vec2:
    x: i64
    y: i64

impl Add for Vec2:
    def __add__(self: Vec2, other: Vec2) -> Vec2:
        return Vec2{x: self.x + other.x, y: self.y + other.y}

def main() -> i64:
    a: Vec2 = Vec2{x: 1, y: 2}
    b: Vec2 = Vec2{x: 3, y: 4}
    c: Vec2 = a + b
    return c.x * 1000 + c.y
""")
    yield ("struct_add_via_generic_bound", """
protocol Add:
    def __add__(self: Self, other: Self) -> Self

struct Vec2:
    x: i64
    y: i64

impl Add for Vec2:
    def __add__(self: Vec2, other: Vec2) -> Vec2:
        return Vec2{x: self.x + other.x, y: self.y + other.y}

def sum2[T: Add](a: T, b: T) -> T:
    return a + b

def main() -> i64:
    a: Vec2 = Vec2{x: 1, y: 2}
    b: Vec2 = Vec2{x: 3, y: 4}
    d: Vec2 = sum2(a, b)
    return d.x * 1000 + d.y
""")
    yield ("struct_eq_and_ne_operators", """
protocol Eq:
    def __eq__(self: Self, other: Self) -> bool

struct Vec2:
    x: i64
    y: i64

impl Eq for Vec2:
    def __eq__(self: Vec2, other: Vec2) -> bool:
        return self.x == other.x and self.y == other.y

def main() -> i64:
    a: Vec2 = Vec2{x: 1, y: 2}
    b: Vec2 = Vec2{x: 1, y: 2}
    c: Vec2 = Vec2{x: 9, y: 9}
    eq_same: i64 = 1 if a == b else 0
    eq_diff: i64 = 1 if a == c else 0
    ne_same: i64 = 1 if a != b else 0
    ne_diff: i64 = 1 if a != c else 0
    return eq_same * 1000 + eq_diff * 100 + ne_same * 10 + ne_diff
""")
    yield ("struct_no_impl_still_declines", """
struct Vec2:
    x: i64
    y: i64

def main() -> i64:
    a: Vec2 = Vec2{x: 1, y: 2}
    b: Vec2 = Vec2{x: 3, y: 4}
    c: Vec2 = a + b
    return c.x
""")
    yield ("struct_ord_operators", """
protocol Ord:
    def __cmp__(self: Self, other: Self) -> i64

struct Vec2:
    x: i64
    y: i64

impl Ord for Vec2:
    def __cmp__(self: Vec2, other: Vec2) -> i64:
        return self.x - other.x

def main() -> i64:
    a: Vec2 = Vec2{x: 3, y: 0}
    b: Vec2 = Vec2{x: 5, y: 0}
    lt: i64 = 1 if a < b else 0
    gt: i64 = 1 if a > b else 0
    le: i64 = 1 if a <= a else 0
    ge: i64 = 1 if b >= a else 0
    return lt * 1000 + gt * 100 + le * 10 + ge
""")
    yield ("struct_eq_in_control_flow", """
protocol Eq:
    def __eq__(self: Self, other: Self) -> bool

struct Point:
    x: i64
    y: i64

impl Eq for Point:
    def __eq__(self: Point, other: Point) -> bool:
        return self.x == other.x and self.y == other.y

def classify(p: Point, target: Point) -> i64:
    if p == target:
        return 1
    return 0

def main() -> i64:
    a: Point = Point{x: 1, y: 2}
    mutable_b: mutable Point = Point{x: 1, y: 2}
    c: Point = Point{x: 9, y: 9}
    guard_result: mutable i64 = 0
    if a == mutable_b:
        guard_result <- 1
    while a == mutable_b:
        guard_result <- guard_result + 10
        mutable_b <- c
    return classify(a, mutable_b) * 100 + guard_result
""")
    yield ("struct_neg_operator", """
protocol Neg:
    def __neg__(self: Self) -> Self

struct Vec2:
    x: i64
    y: i64

impl Neg for Vec2:
    def __neg__(self: Vec2) -> Vec2:
        return Vec2{x: -self.x, y: -self.y}

def main() -> i64:
    a: Vec2 = Vec2{x: 3, y: -4}
    b: Vec2 = -a
    return b.x * 1000 + b.y
""")
    yield ("struct_neg_no_impl_still_declines", """
struct Vec2:
    x: i64
    y: i64

def main() -> i64:
    a: Vec2 = Vec2{x: 3, y: -4}
    b: Vec2 = -a
    return b.x
""")
    yield ("struct_add_via_nested_field_access", """
protocol Add:
    def __add__(self: Self, other: Self) -> Self

struct Vec2:
    x: i64
    y: i64

impl Add for Vec2:
    def __add__(self: Vec2, other: Vec2) -> Vec2:
        return Vec2{x: self.x + other.x, y: self.y + other.y}

struct Line:
    start: Vec2
    end: Vec2

def main() -> i64:
    l1: Line = Line{start: Vec2{x: 1, y: 1}, end: Vec2{x: 2, y: 2}}
    l2: Line = Line{start: Vec2{x: 10, y: 10}, end: Vec2{x: 20, y: 20}}
    combined: Vec2 = l1.start + l2.end
    return combined.x * 1000 + combined.y
""")
    yield ("struct_add_inside_closure", """
protocol Add:
    def __add__(self: Self, other: Self) -> Self

struct Vec2:
    x: i64
    y: i64

impl Add for Vec2:
    def __add__(self: Vec2, other: Vec2) -> Vec2:
        return Vec2{x: self.x + other.x, y: self.y + other.y}

def apply(fn: fn(Vec2) -> Vec2, v: Vec2) -> Vec2:
    return fn(v)

def main() -> i64:
    base: Vec2 = Vec2{x: 100, y: 200}
    result: Vec2 = apply(fn(x) => x + base, Vec2{x: 1, y: 2})
    return result.x * 1000 + result.y
""")


def gen_struct_compound_assign_declines():
    """`x op= v` (`+=`, `-=`, ...) on a STRUCT target. stage0 categorically rejects this
    ("augmented assignment requires numeric operands") even when the struct has a
    matching `impl Add` -- there is no operator-protocol dispatch for the compound-assign
    form, only for the plain binary operator. stage1 used to SEGFAULT here: the compound-
    assign codegen path called the low-level `emit_binary` directly on a struct-typed
    aggregate value without going through the protocol-rewrite that the plain `+` path
    uses, and `emit_binary`'s signed-overflow-checked-arithmetic branch misused the LLVM
    overflow intrinsic on a non-integer type. Fixed by declining early (matching stage0)
    when the compound-assign target type is a Struct, before reaching emit_binary.
    """
    yield ("struct_compound_assign_with_impl_still_declines", """
protocol Add:
    def __add__(self: Self, other: Self) -> Self

struct Vec2:
    x: i64
    y: i64

impl Add for Vec2:
    def __add__(self: Vec2, other: Vec2) -> Vec2:
        return Vec2{x: self.x + other.x, y: self.y + other.y}

def main() -> i64:
    a: mutable Vec2 = Vec2{x: 1, y: 2}
    b: Vec2 = Vec2{x: 3, y: 4}
    a += b
    return a.x * 1000 + a.y
""")
    yield ("struct_compound_assign_no_impl_declines", """
struct Vec2:
    x: i64
    y: i64

def main() -> i64:
    a: mutable Vec2 = Vec2{x: 1, y: 2}
    b: Vec2 = Vec2{x: 3, y: 4}
    a += b
    return a.x * 1000 + a.y
""")
    yield ("struct_field_compound_assign_numeric", """
struct Counter:
    n: mutable i64

def main() -> i64:
    c: mutable Counter = Counter{n: 5}
    c.n += 10
    return c.n
""")
    yield ("struct_field_compound_assign_through_ref_param", """
struct Counter:
    n: mutable i64

def bump(c: mutable Counter&) -> void:
    c.n += 7

def main() -> i64:
    c: mutable Counter = Counter{n: 5}
    bump(&c)
    return c.n
""")
    yield ("struct_field_compound_assign_struct_typed_field_declines", """
protocol Add:
    def __add__(self: Self, other: Self) -> Self

struct Vec2:
    x: i64
    y: i64

impl Add for Vec2:
    def __add__(self: Vec2, other: Vec2) -> Vec2:
        return Vec2{x: self.x + other.x, y: self.y + other.y}

struct Holder:
    v: mutable Vec2

def main() -> i64:
    h: mutable Holder = Holder{v: Vec2{x: 1, y: 2}}
    b: Vec2 = Vec2{x: 3, y: 4}
    h.v += b
    return h.v.x * 1000 + h.v.y
""")


def gen_index_compound_assign():
    """`xs[i] op= v` -- element address computed once and reused for both the load and
    the store, unlike `xs[i] <- v` which only ever stores. Untested all session, and
    stage1's own comment on the plain-store path called this out as "a separate
    lowering" not yet implemented; fixed alongside the struct-field compound-assign
    gap in the same session by reusing emit_darray_index_address/emit_index_address.
    """
    yield ("darray_index_compound_assign", """
def main() -> i64:
    xs: mutable darray[i64] = [1, 2, 3]
    xs[1] += 10
    return xs[1]
""")
    yield ("fixed_array_index_compound_assign", """
def main() -> i64:
    xs: mutable i64[3] = [1, 2, 3]
    xs[2] *= 5
    return xs[2]
""")
    yield ("borrowed_darray_index_compound_assign", """
def bump(xs: mutable darray[i64]&) -> void:
    xs[1] += 100

def main() -> i64:
    xs: mutable darray[i64] = [1, 2, 3]
    bump(&xs)
    return xs[1]
""")
    yield ("borrowed_fixed_array_index_compound_assign", """
def bump(xs: mutable i64[3]&) -> void:
    xs[2] += 100

def main() -> i64:
    xs: mutable i64[3] = [1, 2, 3]
    bump(&xs)
    return xs[2]
""")
    yield ("nested_darray_index_compound_assign", """
def main() -> i64:
    m: mutable darray[darray[i64]] = [[1, 2], [3, 4]]
    m[0][1] += 100
    return m[0][1]
""")
    yield ("borrowed_nested_darray_index_compound_assign", """
def bump(m: mutable darray[darray[i64]]&) -> void:
    m[0][1] += 100

def main() -> i64:
    m: mutable darray[darray[i64]] = [[1, 2], [3, 4]]
    bump(&m)
    return m[0][1]
""")


def gen_floats():
    """f32/f64 arithmetic, comparisons, and numeric-cast METHOD CALLS whose RECEIVER is a
    bare (or unary-negated) float LITERAL rather than a typed variable — zero corpus usage
    (`grep f32\\|f64` over this file was empty before this generator existed), and the
    receiver-is-a-literal shape is exactly the one `codegen_expr_calls.elisa`'s cast path
    used to special-case AWAY: a comment there read "`1.5.i64()` is not a form the subset
    needs to model", defaulting an untyped literal receiver's source type to i64 regardless
    of the literal's own kind. `3.9.i64()` then resolved its FloatLit receiver AT i64,
    which cannot be emitted, and the decline took the whole enclosing function with it
    (DECLINE VarDecl, DROPPED main) — stage0 accepts and truncates it (exit 3). Fixed by
    defaulting a float-literal receiver (bare OR unary +/- negated, `(-3.9).i32()` is a
    one-layer-deeper case of the same gap) to f64 instead of i64.

    A SECOND, independent bug turned up validating the FIRST fix's own boundary (variables,
    not literals, this time): `emit_expression_binary_tail`'s mixed-width numeric check
    assumed `operand_type` always equals the LEFT operand's exact kind/bits — true for the
    INTEGER narrow-to-left rule it was written for, false the moment either operand is a
    FLOAT of a different width/kind than the other. `f32 + f64` and `f64 + i64` (either
    order) both declined outright, though stage0 accepts both and WIDENS to the wider/float
    side (`fpext`/`sitofp`, confirmed via `-emit llvm` — the opposite direction from the
    integer rule, which narrows). Fixed by special-casing both mixed shapes to pick the
    float side as `operand_type` before the general check runs.
    """
    yield ("float_literal_cast_truncates", """
def main() -> i64:
    return 3.9.i64() * 10 + 7.2.i64()
""")
    yield ("float_literal_cast_negative_and_narrow", """
def main() -> i64:
    a: i32 = (-3.9).i32()
    b: u8 = 9.9.u8()
    return a.i64() * 10 + b.i64()
""")
    yield ("float_mixed_f32_f64_arithmetic", """
def main() -> i64:
    a: f32 = 1.5.f32()
    b: f64 = 2.5
    c: f64 = a + b
    return c.i64()
""")
    # A separate DECLINE found while boundary-checking the f32/f64 widen fix: an INTEGER
    # operand against a FLOAT operand (either order) hits the same "operand_type must equal
    # left_own's exact kind/bits" decline check, even though stage0 accepts and promotes to
    # the float side (`sitofp` on the int, confirmed via `-emit llvm`) exactly as it does
    # for float/float mixed width.
    yield ("float_int_mixed_arithmetic_both_orders", """
def main() -> i64:
    a: i64 = 3
    b: f64 = 2.5
    c: f64 = a - b
    d: bool = a.f64() < b
    e: bool = b < a.f64()
    r: mutable i64 = c.i64()
    r <- r + 100 if d
    r <- r + 1000 if e
    return r
""")
    yield ("float_comparison_branches", """
def main() -> i64:
    a: f64 = 5.5
    b: f64 = 5.5
    c: f64 = 5.6
    r: mutable i64 = 0
    r <- r + 1 if a == b
    r <- r + 10 if a < c
    r <- r + 100 if c > a
    return r
""")
    yield ("float_negative_division_truncates", """
def main() -> i64:
    a: f64 = -7.5
    b: f64 = 2.0
    c: f64 = a / b
    return c.i64()
""")
    yield ("float_f32_arithmetic_and_cast", """
def main() -> i64:
    a: f32 = 10.5.f32()
    b: f32 = 3.25.f32()
    c: f32 = a - b
    return c.i64()
""")
    yield ("float_mixed_width_comparisons", """
def main() -> i64:
    a: f32 = 2.5.f32()
    b: f64 = 2.5
    c: f64 = 2.6
    r: mutable i64 = 0
    r <- r + 1 if a == b
    r <- r + 10 if a < c
    r <- r + 100 if c > a
    return r
""")


def gen_pin_and_range_match_arms():
    """A scalar statement-match over an integer scrutinee with a `^pin` arm (compare
    against an existing binding's VALUE rather than a constant) or a range arm. The
    parser has built Pattern.Pin since parser_stmt_pattern.elisa:279 and three semantic
    passes handled it, but scalar_match_pattern_valid's `_: false` tail rejected both
    shapes outright ("top-level integer match arm must use an integer literal or _"),
    so neither ever reached codegen -- which had no Pattern.Pin case either. Recovered
    from uncommitted work in the sweet-zhukovsky-34d525 worktree.
    """
    yield ("scalar_match_pin_arm", """
def classify(v: i64, target: i64) -> i64:
    match v:
        ^target:
            return 100
        0:
            return 1
        _:
            return 2

def main() -> i64:
    return classify(7, 7) + classify(0, 9) + classify(5, 9)
""")
    yield ("scalar_match_range_arm", """
def bucket(v: i64) -> i64:
    match v:
        0..<10:
            return 1
        10..<20:
            return 2
        _:
            return 3

def main() -> i64:
    return bucket(5) * 100 + bucket(15) * 10 + bucket(99)
""")


def gen_value_match_pin_and_range():
    """The SAME `^pin` and range arms as gen_pin_and_range_match_arms, but through the
    THIRD match emitter: `x: T = match ...` / `return match ...`, which lowers through
    emit_match_into_slot (codegen_condition.elisa) rather than the statement-position
    scalar match (codegen_stmt_match_scalar.elisa) or the plain value-position match
    (codegen_expr_match_aggregates.elisa). All three emitters resolve the same syntax
    but have historically had different capabilities -- this file's own header comment
    on emit_match_into_slot recorded "no ranges" as a known gap, and it had no
    Pattern.Pin case at all. Confirmed via ELISA_DBG_DECLINE: `result: i64 = match v:
    ^target: ...` dropped the whole function with `DECLINE VarDecl`, even though the
    identical pattern already worked in statement position. Fixed by adding both arm
    kinds to emit_match_into_slot's scalar arm loop, mirroring the hit-test logic the
    other two emitters already had (declined for a payload/packed-enum or string
    scrutinee, same restriction the siblings apply).
    """
    yield ("value_match_pin_arm", """
def classify(v: i64, target: i64) -> i64:
    result: i64 = match v:
        ^target:
            100
        0:
            1
        _:
            2
    return result

def main() -> i64:
    return classify(7, 7) + classify(0, 9) + classify(5, 9)
""")
    yield ("value_match_range_arm", """
def bucket(v: i64) -> i64:
    result: i64 = match v:
        0..<10:
            1
        10..<20:
            2
        _:
            3
    return result

def main() -> i64:
    return bucket(5) * 100 + bucket(15) * 10 + bucket(99)
""")


def gen_borrowed_fixed_array_chain():
    """`pts[i].field` (a FIELD chain through an INDEX) where `pts: T[N]&` is a borrowed
    reference to a single fixed-size array -- the standard borrowed-array-parameter
    shape. struct_chain_type/struct_chain_address (codegen_place.elisa) resolve nested
    field/index chains generically, and their shared `container[i]` handling had cases
    for a borrowed single-container Ref pointing at a Struct/Signed/Unsigned/Float/
    Optional/DArray element -- but never TypeKind.Array, even though the sibling
    DArray-behind-Ref case (`m: darray[T]&`, `m[i]`) was already there. `pts[0].x <- v`
    declined outright (`DECLINE Assign`) because the Field-target branch resolves its
    receiver's type through struct_chain_type, which fell through the Ref branch's case
    list to Unmodeled. This is a TYPE/ADDRESS-half drift of the same shape as the
    borrowed-darray-of-darray fix earlier this session: struct_chain_address's own
    Ident+Index+Ref branch was equally missing the Array case (only handled it for
    Struct/Signed/Unsigned/Float). Fixed by adding TypeKind.Array to both halves,
    reusing emit_index_address exactly as the compound-assign path's dedicated
    Ref+Array branch (codegen_stmt_assign_flow.elisa) already does one level up.
    """
    yield ("borrowed_fixed_array_field_chain_assign", """
struct Point:
    x: mutable i64
    y: mutable i64

def bump(pts: mutable Point[3]&):
    pts[0].x <- pts[0].x + 100
    pts[1].y <- pts[1].y + 200

def main() -> i64:
    ps: mutable Point[3] = [Point{x:1,y:2}, Point{x:3,y:4}, Point{x:5,y:6}]
    bump(&ps)
    return ps[0].x + ps[1].y + ps[2].x
""")
    yield ("borrowed_fixed_array_field_chain_read_addr_compound", """
struct Point:
    x: mutable i64
    y: mutable i64

def read_it(pts: Point[3]&) -> i64:
    return pts[1].y

def addr_it(pts: mutable Point[3]&) -> uintptr:
    p: mutable i64& = &pts[2].x
    return p.uintptr()

def compound_it(pts: mutable Point[3]&):
    pts[2].x += 1000

def main() -> i64:
    ps: mutable Point[3] = [Point{x:1,y:2}, Point{x:3,y:4}, Point{x:5,y:6}]
    r: i64 = read_it(&ps)
    a1: uintptr = addr_it(&ps)
    a2: uintptr = (&ps[2]).uintptr()
    same: bool = a1 == a2
    compound_it(&ps)
    return r * 1000 + ps[2].x + (100 if same else 0)
""")


def gen_borrowed_fixed_array_mixed_width_read():
    """A SILENT WRONG ANSWER (MISMATCH), not a decline: `xs[i]` where `xs: T[N]&` is a
    borrowed reference to a single fixed-size array. Two independent gaps compounded:

    1. `expression_type`'s Expr.Index/Ref case (codegen_scope.elisa) had no
       TypeKind.Array branch, so it fell through to the catch-all
       `array_element_of(indexed_type, ...)` called on the raw Ref (not its Array
       target) -- which safely declines a non-Array input, so `pts[i]` silently typed
       as Unmodeled. This alone made a type-dependent use of the read (an explicit
       `.i64()` cast) decline outright.

    2. The matching CODEGEN read (emit_expression_index_fields's own
       `array_type.kind == Ref, target == Array` branch, codegen_expr_index_fields.elisa)
       loaded the element at its NATURAL width with no conversion tail at all -- the
       exact "new read path forgets its conversion tail" shape documented for the
       view[T] index arm earlier this session, just in a sibling branch that never got
       the same fix.

    Together, in a function whose return expression skips the `.i64()` decline path
    (an implicit-width binary add rather than an explicit cast), stage1 built an LLVM
    module with a WIDTH-MISMATCHED `llvm.sadd.with.overflow.i64(i64, i8)` call --
    LLVM accepted it and answered 200 where stage0 answers 202. Confirmed via
    `-emit llvm`: `%arr.ref.elem3 = load i8, ...` fed directly into the i64 overflow
    intrinsic with no zext/sext in between. Fixed both gaps: added TypeKind.Array to
    expression_type's Ref-Index branch (mirroring the DArray-behind-Ref case already
    there), and added the same emit_conversion tail its scalar-ref/opt-ref/view
    sibling branches already have.
    """
    yield ("borrowed_fixed_array_mixed_width_read", """
def combine(ys: mutable i64[3]&, zs: mutable u8[3]&) -> i64:
    return ys[1] + zs[1].i64()

def main() -> i64:
    ys: mutable i64[3] = [100, 200, 300]
    zs: mutable u8[3] = [1, 2, 3]
    return combine(&ys, &zs)
""")
    yield ("borrowed_fixed_array_explicit_cast_isolated", """
def only_u8(zs: mutable u8[3]&) -> i64:
    return zs[1].i64()

def only_i64(ys: mutable i64[3]&) -> i64:
    return ys[1]

def main() -> i64:
    ys: mutable i64[3] = [100, 200, 300]
    zs: mutable u8[3] = [1, 2, 3]
    return only_u8(&zs) * 10 + only_i64(&ys)
""")
    yield ("borrowed_fixed_array_struct_element_read", """
struct Point:
    x: i64
    y: i64

def sum_struct(pts: Point[3]&) -> i64:
    return pts[1].x + pts[2].y

def main() -> i64:
    ps: Point[3] = [Point{x:1,y:2}, Point{x:3,y:4}, Point{x:5,y:6}]
    return sum_struct(&ps)
""")


def gen_range_match_value_slot():
    """A range-pattern arm (`0..<5:`) in a VALUE-position match whose arms are BLOCKS, not
    single expressions (`x: T = match ...` / `return match ...`) -- emit_match_into_slot
    (codegen_condition.elisa), the emitter for exactly that shape. Its sibling emitters
    already supported a range arm -- the statement-position matcher
    (codegen_stmt_match_scalar.elisa) and the single-EXPRESSION-arm value-position matcher
    (codegen_expr_match_aggregates.elisa) -- but emit_match_into_slot's own pattern dispatch
    only classified Pattern.Literal and Pattern.Variant, so a range arm fell through its
    catch-all `mis_declined <- true` and the whole assignment/return declined, even though
    stage0 accepts it and the identical range arm already worked in the OTHER two match
    positions. Each arm below does real per-branch work (not a bare literal return) so a
    wrong bucket, not just a wrong bound, would show up as a mismatch.
    """
    yield ("range_match_value_slot_vardecl", """
def classify(x: i64) -> i64:
    result: i64 = match x:
        0..<5:
            y: i64 = x * 10
            y + 1
        5..=10:
            z: i64 = x * 100
            z + 2
        _:
            -1
    return result

def main() -> i64:
    return classify(2) + classify(7) + classify(99)
""")
    yield ("range_match_value_slot_return", """
def classify(x: i64) -> i64:
    return match x:
        0..<5:
            y: i64 = x * 10
            y + 1
        5..=10:
            z: i64 = x * 100
            z + 2
        _:
            -1

def main() -> i64:
    return classify(0) + classify(10) + classify(4)
""")


def gen_shifts_bitwise_and_size_types():
    """Two thin spots found by auditing corpus density: shift operators (`<<` 4 mentions,
    `>>` 3, `^` 7 — far below comparable features) and `usize`/`isize` (2 each). Both are
    classic divergence territory: a right shift must be ARITHMETIC on a signed operand
    and LOGICAL on an unsigned one, and getting that backwards is a silent wrong answer,
    not a crash. Probed deliberately; stage1 matches stage0 on all of it, so this lands
    as coverage rather than a fix.

    Deliberately stays inside WELL-DEFINED shift ranges (never >= the operand width) —
    an oversized shift is undefined behaviour, and a fixture built on UB proves nothing
    about either compiler (see the poisoned-fixture lesson in the memory notes).
    """
    yield ("shift_arithmetic_vs_logical_right", """
def main() -> i64:
    a: i64 = -16
    r1: i64 = a >> 2
    b: u64 = 18446744073709551600
    r2: u64 = b >> 2
    c: i32 = -16
    r3: i32 = c >> 2
    d: u32 = 4294967280
    r4: u32 = d >> 2
    return (r1 + 4) + (r2 % 100).i64() + (r3 + 4).i64() + (r4 % 100).i64()
""")
    yield ("shift_left_and_bitwise_ops", """
def main() -> i64:
    a: i64 = 1
    l1: i64 = a << 40
    b: u8 = 3
    l2: u8 = b << 5
    c: i16 = -1
    r3: i16 = c >> 3
    m: i64 = 255
    x: i64 = (m ^ 15) | 256
    y: i64 = m & 240
    return (l1 >> 36) + l2.i64() + (r3.i64() + 1) + (x % 1000) + y
""")
    yield ("usize_isize_in_containers_and_loops", """
def take(n: usize, s: isize) -> i64:
    return n.i64() + s.i64()

def main() -> i64:
    xs: mutable darray[i64] = [10, 20, 30]
    n: usize = xs.count
    s: isize = -5
    idx: usize = 1
    v: i64 = xs[idx]
    sum: mutable usize = 0
    for i in 0..<n |sum|:
        sum <- sum + i
    return take(n, s) + v + sum.i64()
""")
    yield ("usize_isize_division_truncation_and_max", """
def main() -> i64:
    a: usize = 10
    b: usize = 3
    q: usize = a / b
    r: usize = a % b
    s: isize = -10
    t: isize = s / 3
    u: isize = s % 3
    big: usize = 18446744073709551615
    w: usize = big / 1000000000000000000
    return q.i64() * 100 + r.i64() * 10 + (t.i64() + 10) + (u.i64() + 10) + w.i64()
""")


def gen_i16_u16_widths():
    """`i16`/`u16` had ZERO corpus coverage before this generator — the same signature as
    the f32/f64 gap found earlier in this session (i8, i32, i64 all had cases; i16 was
    simply skipped), and mixed-width arithmetic is the exact class that produced two
    separate silent wrong answers today (the borrowed `T[N]&` read and the float widen).
    Probed for those shapes specifically and found stage1 already CORRECT on all of them
    — recorded here so the area stops being untested rather than because it was broken.
    Each case gives distinct positions distinct values so a wrong width or a wrong
    truncation cannot pass vacuously.
    """
    yield ("i16_narrow_arithmetic", """
def main() -> i64:
    a: i16 = 300
    b: i16 = 40
    c: i16 = a + b
    d: i64 = c.i64()
    return d
""")
    yield ("i16_mixed_width_and_array_compound", """
def main() -> i64:
    a: i16 = 300
    b: i64 = 7
    c: i64 = a.i64() + b
    xs: mutable i16[3] = [10, 20, 30]
    xs[1] += 5
    return c + xs[1].i64()
""")
    yield ("i16_u16_borrowed_arrays_and_darray", """
def bump(xs: mutable i16[3]&, ys: mutable u16[3]&) -> i64:
    xs[0] += 100
    ys[0] += 7
    return xs[0].i64() + ys[0].i64()

def main() -> i64:
    xs: mutable i16[3] = [1, 2, 3]
    ys: mutable u16[3] = [10, 20, 30]
    r: i64 = bump(&xs, &ys)
    m: mutable darray[i16] = [5, 6]
    m[1] *= 3
    neg: i16 = -300
    return r + m[1].i64() + neg.i64()
""")
    yield ("i16_u16_boundary_division_truncation", """
def main() -> i64:
    a: i16 = 32767
    b: i16 = a / 3
    c: u16 = 65535
    d: u16 = c / 5
    e: i16 = -32768
    f: i16 = e / 7
    return b.i64() + d.i64() + f.i64()
""")


def gen_darray_of_fixed_array():
    """`darray[T[N]]` -- a darray whose ELEMENT is itself a fixed-size array -- declined
    unconditionally at the type-annotation level (`annotation_index_named_value_type`'s
    "darray" case had an explicit `unmodeled_type() return if darray_element.kind ==
    TypeKind.Array` guard, predating any commit in this session's history), even for a
    bare uninitialized `m: darray[i64[2]]` with no literal at all. The darray backing
    store's push/index/growth paths are element-type-agnostic (they size and GEP through
    llvm_type_of generically), so once the guard was removed the feature worked with no
    other changes. Found by following up on a flagged-but-deferred lead from the same
    session's borrowed-darray-of-darray chain-type fix.
    """
    yield ("darray_of_fixed_array_uninitialized", """
def main() -> i64:
    m: darray[i64[2]]
    return 0
""")
    yield ("darray_of_fixed_array_literal", """
def main() -> i64:
    m: mutable darray[i64[2]] = [[1, 2], [3, 4]]
    return m[0][1]
""")
    yield ("darray_of_fixed_array_push", """
def main() -> i64:
    m: mutable darray[i64[2]] = []
    m.push([1, 2])
    return m[0][1]
""")
    yield ("darray_of_fixed_array_index_compound_assign", """
def main() -> i64:
    m: mutable darray[i64[2]] = [[1, 2], [3, 4]]
    m[0][1] += 100
    return m[0][1] + m[1][0]
""")


def gen_named_tuples():
    """Named-tuple return types (`-> (label: T, ...)`), multi-value `return a, b` (bare
    comma, NOT parenthesized `(label: a, ...)` — that shape is a DIFFERENT grammar the
    return-statement parser does not accept), and field access by label. Untested all
    session; zero corpus usage (the compiler's own source doesn't use named tuples).
    """
    yield ("named_tuple_struct_elements", """
struct Point:
    x: i64
    y: i64

def make(a: Point, b: Point) -> (first: Point, second: Point):
    return b, a

def main() -> i64:
    p1: Point = Point{x: 1, y: 2}
    p2: Point = Point{x: 3, y: 4}
    result: (first: Point, second: Point) = make(p1, p2)
    return result.first.x * 1000 + result.second.x
""")
    yield ("named_tuple_scalar_elements", """
def divmod(a: i64, b: i64) -> (quotient: i64, remainder: i64):
    return a / b, a % b

def main() -> i64:
    r: (quotient: i64, remainder: i64) = divmod(17, 5)
    return r.quotient * 100 + r.remainder
""")


def gen_generic_operator_no_bound():
    """A binary operator applied to a value of a COMPLETELY UNBOUND generic type
    parameter (`def bump[T](a: T, b: T): a + b`, no `[T: Interface]` clause). stage0
    checks a generic function's body once, against only what its declared bound
    guarantees -- an unbound T supports nothing, so this is rejected at DECLARATION
    time regardless of any call site. stage1 had no such check and accepted it,
    deferring entirely to per-instantiation codegen -- a genuine PERMISSIVE divergence
    (stage1 was a strict superset of valid programs, never a wrong answer). See
    generic-operator-bound-checking-gap.md for the full writeup, including a real false
    positive found and fixed during staging: a REF parameter (`items: T&`, a C-buffer
    pointer) used in pointer arithmetic (`items + index`) is unrelated to whatever T's
    bound provides and must never be flagged -- the deque/collections
    `*_void_from_items_at` helpers in elisacore_std use exactly this shape.
    """
    yield ("generic_operator_no_bound_rejected", """
def bump[T](a: mutable T&, b: T) -> void:
    a <- a + b

def main() -> i64:
    x: mutable i64 = 5
    bump(&x, 10)
    return x
""")
    yield ("generic_operator_bound_satisfied_accepted", """
protocol Add:
    def __add__(self: Self, other: Self) -> Self

struct P:
    x: i64

impl Add for P:
    def __add__(self: P, other: P) -> P:
        return P{x: self.x + other.x}

def combine[T: Add](a: T, b: T) -> T:
    return a + b

def main() -> i64:
    p: P = combine(P{x: 1}, P{x: 2})
    return p.x
""")
    yield ("generic_no_operator_still_accepted", """
def identity[T](a: T) -> T:
    return a

def main() -> i64:
    return identity(42)
""")
    yield ("generic_ref_param_pointer_arithmetic_not_flagged", """
def buf_offset[T](items: mutable T&, index: usize) -> mutable void& can[Unsafe.PointerCast, Unsafe.PointerArithmetic]:
    trusted [Unsafe.PointerCast, Unsafe.PointerArithmetic]:
        return (items + index).cast[mutable void&]

def main() -> i64:
    x: mutable i64[3] = [10, 20, 30]
    p: mutable void& = buf_offset(&x[0], 1)
    return 5
""")


def gen_mutable_ref_local_rebind():
    """`r: mutable T& = v; r <- v2` -- the LOCAL BINDING itself was declared `mutable`,
    which stage0 treats as REBINDING the reference (assigning a new T&-typed value to
    the binding) rather than writing through it -- a plain non-Ref value on the RHS is
    rejected ("cannot assign int to mutable i64&"). stage1's codegen had no way to tell
    a mutable-declared local from a non-mutable one (Scope tracked name/slot/type only,
    no mutability bit at all) and performed write-through unconditionally for ANY
    Ref-typed `<-` target -- a genuine PERMISSIVE divergence (stage1 silently ACCEPTED
    and ran `ref <- 5` on a `mutable i64&` local, writing 5 through instead of
    rejecting), confirmed to predate this entire session via a throwaway worktree.

    Fixed by adding Scope.local_is_mutable, a bit set ONLY at the one VarDecl shape that
    can spell `mutable` on a Ref-typed annotation at all (type_contains_token already
    existed in the backend for exactly this check); every other local stays at the
    pushed default `false`, so the pre-existing write-through behavior for a
    non-mutable-declared Ref local (the overwhelmingly common case) is unchanged by
    construction. See defer-function-cleanup-scope-gap and mutable-ref-local-rebind-gap
    in the memory notes for how this was found (interaction-axis testing) and the
    corrected-vs-original write-through-ref-gap record.
    """
    yield ("mutable_ref_local_rebind_rejects_plain_value", """
global mutable g: mutable i64 = 100

def main() -> i64:
    ref: mutable i64& = &g
    ref <- 5
    return g
""")
    yield ("mutable_ref_local_rebind_via_call_result_rejects_plain_value", """
global mutable g: i64 = 42

def get_ref() -> mutable i64&:
    return &g

def main() -> i64:
    r: mutable i64& = get_ref()
    r <- 99
    return g
""")
    yield ("mutable_ref_local_rebind_accepts_new_reference", """
global mutable g1: mutable i64 = 1
global mutable g2: mutable i64 = 2

def main() -> i64:
    r: mutable i64& = &g1
    r <- &g2
    return g1 + g2
""")


def gen_ref_returning_call_deref():
    """A function declared `-> T&` whose call result lands in a VALUE context (`x: T =
    f()`, not `x: T& = f()`) must be DEREFERENCED — storing the raw pointer's bit pattern
    into a T-typed slot is a silent WRONG ANSWER, not a decline, and was invisible to
    self-hosting (the compiler's own source apparently never triggers this exact shape).
    """
    yield ("ref_returning_call_deref_global", """
global mutable g: i64 = 42

def get_ref() -> i64&:
    return &g

def main() -> i64:
    v1: i64 = get_ref()
    return v1
""")
    yield ("ref_returning_call_deref_struct_field", """
struct Pair:
    a: i64
    b: i64

def store_get(s: Pair&, h: bool) -> i64&:
    return &s.a if h else &s.b

def main() -> i64:
    p: Pair = Pair{a: 10, b: 20}
    v1: i64 = store_get(p, true)
    v2: i64 = store_get(p, false)
    return v1 * 1000 + v2
""")
    yield ("ref_returning_call_still_works_as_ref", """
global mutable g: i64 = 42

def get_ref() -> i64&:
    return &g

def main() -> i64:
    r: i64& = get_ref()
    v: i64 = r
    return v
""")
    yield ("ref_returning_call_struct_pointee_still_declines", """
struct Pair:
    a: i64
    b: i64

global mutable g: Pair = Pair{a: 10, b: 20}

def get_ref() -> Pair&:
    return &g

def main() -> i64:
    v: Pair = get_ref()
    return v.a
""")
    yield ("ref_returning_call_as_argument", """
global mutable g: i64 = 42

def get_ref() -> i64&:
    return &g

def show(v: i64) -> i64:
    return v * 2

def main() -> i64:
    return show(get_ref())
""")
    yield ("ref_returning_call_in_arithmetic", """
global mutable g: i64 = 42

def get_ref() -> i64&:
    return &g

def main() -> i64:
    return get_ref() + 1
""")


def gen_lmut_place_required():
    """`lmut T` parameters need a mutable PLACE, not a value — stage0 enforces this
    (docs/120 §10) and stage1 was silently missing two shapes of it, both PERMISSIVE gaps
    (stage0 rejects, stage1 built clean). Every program below must FAIL to build under BOTH
    compilers; a stage1 accept here is exactly the bug.

    1. `DiagnosticKind.LmutMutationNotReassignment` (check_lmut_mutation_reassignment.elisa)
       carried severity 0 in semantic_api_severity.elisa. The driver only exits 1 on
       severity-1 findings (`continue if Semantic::diagnostic_severity(diagnostic) != 1`,
       src/driver/elisac.elisa), so this diagnostic — though computed correctly — never
       blocked a build. A bare statement call that threads an `lmut` struct parameter
       without a reassignment (`bump(c)` instead of `c <- bump(c)`) compiled clean.
    2. check_lmut_value_arg.elisa's place-tracking reused the shared `is_primitive_type_name`
       helper, which folds `sview`/`cstr`/`dstr` in with the true scalars — correct for ITS
       OTHER callers (e.g. `.sview()`/`.cstr()` are real builtin conversion method names) but
       wrong here: those three spellings are STRUCTS, and stage0 requires a mutable place for
       an `lmut sview`/`lmut cstr`/`lmut dstr` parameter exactly like any user struct
       ("argument 1 to f expects mutable sview&, got sview"). A by-value sview/cstr/dstr
       local passed to such a parameter was never flagged.
    """
    yield ("lmut_mutation_bare_call_not_reassignment", """
struct Counter:
    n: i64

def bump(c: lmut Counter) -> void:
    pass

def main() -> i64:
    c: mutable Counter = Counter{n: 1}
    bump(c)
    return c.n
""")
    yield ("lmut_value_arg_sview_needs_place", """
def bump(s: lmut sview) -> void:
    pass

def main() -> i64:
    x: sview = "hi"
    bump(x)
    return 0
""")
    yield ("lmut_value_arg_cstr_needs_place", """
def bump(s: lmut cstr) -> void:
    pass

def main() -> i64:
    x: cstr = "hi"
    bump(x)
    return 0
""")
    yield ("lmut_value_arg_dstr_needs_place", """
def bump(s: lmut dstr) -> void:
    pass

def main() -> i64:
    x: dstr = "hi"
    bump(x)
    return 0
""")


def gen_flags_const_enum_sview():
    """`Flags[T]` requires T to be a const enum (check_flags_const_enum.elisa). Its own
    `flags_is_primitive` helper lists every definitely-not-a-const-enum spelling to reject
    (`Flags[i64]`, `Flags[bool]`, ...) and explicitly includes `cstr`/`dstr` — but not
    `sview`, even though sview is exactly the same kind of builtin non-const-enum type.
    stage0 rejects `Flags[sview]` with "Flags[T] expects a const enum type argument, got
    sview"; stage1 silently accepted it (a PERMISSIVE gap) until sview was added alongside
    cstr/dstr in the primitive list.
    """
    yield ("flags_const_enum_sview_rejected", f"""
include "{ROOT}/elisacore_std/collections.elisa"

def f(x: Flags[sview]&) -> bool:
    return true

def main() -> i64:
    return 0
""")


def gen_char_literal_never_fits_sview():
    """`literal_never_fits` (resolve_types.elisa) is the oracle-verified impossible-pair
    matrix deciding whether a literal can NEVER initialize a declared primitive type. Its
    "string"/"int"/"bool" branches all route the string family through the shared
    `is_string_type_name` helper (cstr/dstr/sview together), but the "char" branch
    hand-enumerated only `cstr`/`dstr` and dropped `sview` — even though a char literal
    can no more initialize an sview than a cstr/dstr. stage0 rejects `x: sview = 'a'`
    ("variable x expects sview, got char"); stage1 silently accepted it (PERMISSIVE gap)
    until the char branch was switched to `is_string_type_name` like its siblings.
    """
    yield ("char_literal_into_sview_rejected", """
def main() -> i64:
    x: sview = 'a'
    return 0
""")


def gen_clone_builtin_move_wrapped_source():
    """`clone[darray[T]](src)` where `src` is an `sview` parameter and T != u8 cannot widen
    a byte view into a T-element container (check_clone_builtin.elisa's CloneElemMismatch).
    The check's own source-argument matcher only recognised a BARE `Expr.Ident` — a
    `move src`-wrapped argument (a very ordinary way to pass an owned/linear-tracked
    parameter) skipped the match entirely. In a `return`-position call the separate
    CloneOwnerRequired check happens to also fire and mask this (both compilers still
    reject), but bound to a plain local — the shape here — nothing else catches it: stage0
    rejects ("clone cannot clone sview into darray[u32] in v1"), stage1 silently accepted
    the `move`-wrapped form (a PERMISSIVE gap) until the source-argument matcher unwrapped
    `Paren`/`Move` first.
    """
    yield ("clone_move_wrapped_sview_into_darray_u32", """
def f(src: sview) -> i64:
    x: darray[u32] = clone[darray[u32]](move src)
    return 0

def main() -> i64:
    return 0
""")


def gen_shorthand_member_is():
    """`x is .Variant` -- the leading-dot enum shorthand, whose enum comes from the
    expected type. The parser gives it its own node (Expr.ShorthandMember) while every
    `is` variant-test path in the backend matches Expr.Field, so the shorthand fell
    through all of them and DECLINED: the form was simply unimplemented in codegen
    (`grep ShorthandMember src/backend` found nothing).

    stage0 permits the shorthand for CONST enums only -- on a payload enum it errors
    `shorthand member ".Circle" requires an expected const enum type`. Both spellings
    are pinned here, including `is not` (which the parser desugars to
    Unary(Not, <is>)), and a const enum whose VALUES differ from its ordinals, since
    the compare is against the member's value.

    See shorthand-member-const-enum-only.md -- notably that stage0's `-emit obj`
    ACCEPTS the payload-enum form its `-emit llvm` rejects, so obj-exit-0 alone is not
    proof a form is legal.
    """
    yield ("shorthand_member_is_const_enum", """
const enum Tok of i32:
	IDENT = 7
	NUMBER = 9

def classify(kind: Tok) -> i64:
	return 1 if kind is .IDENT else 0

def negate(kind: Tok) -> i64:
	return 10 if kind is not .IDENT else 20

def main() -> i64:
	return classify(Tok.IDENT) + classify(Tok.NUMBER) * 2 + negate(Tok.NUMBER) + negate(Tok.IDENT)
""")
    # NOT pinned here: the QUALIFIED spelling `kind is Tok.NUMBER` on a const enum.
    # stage0 REJECTS it while stage1 accepts and runs it -- a live PERMISSIVE divergence
    # that predates the shorthand work (stage1's const-enum `is` path at
    # codegen_expr_idents_binary.elisa handles the qualified form unconditionally). The
    # PERMISSIVE bucket is ratcheted at zero, so adding it would fail the gate outright
    # without fixing anything. Documented in shorthand-member-const-enum-only.md instead.


def gen_builtin_view_type_name():
    """`size_of(view[i32])` -- the builtin container type name `view` used where the
    resolver walks a TYPE as a value expression. seed_builtins registered `darray`,
    `dict`, `set` and `array` but not `view`, so it alone reported `undefined
    identifier 'view'` while its siblings resolved.

    Pinned alongside a struct `size_of` so the numeric answers (not just acceptance)
    are compared. Note the argument is strictly a TYPE: stage0 rejects both
    `size_of(NoSuchType)` ("unknown type") and `size_of(x)` for a value `x`, so this
    could NOT be fixed by skipping the argument the way offset_of's field selector is
    skipped -- that would have accepted an undefined type name and gone PERMISSIVE.
    """
    yield ("builtin_view_type_name_size_of", """
struct Padded:
	tag: i8
	value: i32

def padded_size() -> usize:
	return size_of(Padded)

def view_size() -> usize:
	return size_of(view[i32])

def main() -> i64:
	return padded_size().i64() * 100 + view_size().i64()
""")


def gen_void_return_call():
    """`return helper()` where helper is `-> void`, from a `-> void` function --
    returning a VOID-typed call rather than falling off the end.

    stage1 CRASHED on this (SIGTRAP, no diagnostic). The operand is void-typed, so
    LLVMBuildRet emitted `ret void <badref>` -- malformed IR that slipped past the
    return-type identity check (void == void, so the types "match") and then trapped
    LLVM during object emission. The bare-`return` path was always correct; only the
    return-WITH-VALUE path was wrong.

    Pinned through a mutable ref so the relayed call's SIDE EFFECT is observed twice,
    not merely that the program compiles.
    """
    yield ("void_return_call_relay", """
def bump(slot: mutable i64&) -> void:
	slot <- slot + 7
	return

def relay(slot: mutable i64&) -> void:
	return bump(slot)

def main() -> i64:
	total: mutable i64 = 0
	relay(&total)
	relay(&total)
	return total
""")


GENERATORS += [gen_aggregate_abi]
def gen_copy_array_builtin():
    """`copy[array[T, N]](src)` -- a value copy into a fixed-size array. The backend had
    NO handling of `copy` whatsoever, so every use declined.

    A fixed array is an LLVM first-class aggregate VALUE, so the copy is just the value:
    no buffer to duplicate, nothing to alias. The dangerous shape (a runtime-length
    source, where a shallow copy WOULD alias) cannot reach codegen -- check_copy_builtin
    rejects a darray source and any non-array[T, N] target first.

    The fixture MUTATES the duplicate and reads BOTH back, so aliasing would change the
    answer rather than merely compiling: a true copy gives 1*100 + 99, an aliased one
    would give 99*100 + 99.
    """
    yield ("copy_array_builtin_is_value_copy", """
def dup(src: array[u8, 4]) -> array[u8, 4]:
	return copy[array[u8, 4]](src)

def main() -> i64:
	original: mutable array[u8, 4] = [1, 2, 3, 4]
	duplicate: mutable array[u8, 4] = dup(original)
	duplicate[0] <- 99
	return original[0].i64() * 100 + duplicate[0].i64()
""")


def gen_discarded_darray_growth_methods():
    """`_ = xs.resize(n)` / `.truncate(n)` / `.clear()`. These return the receiver for
    chaining, so they are DISCARDED via `_ =` rather than written as bare statements.

    The STATEMENT emitter lowers all three, but emit_expression models none of them, so
    the discarded spelling declined while the bare-statement spelling compiled --
    `reserve` was the only one with a dedicated discard path. Fixed by delegating the
    discard to the statement emitter (a discarded call IS a statement expression).

    Note the discard of a METHOD call folds to Stmt.Assign, not Stmt.VarDecl: an
    equivalent guard added to the VarDecl discard path turned out to be dead code and was
    dropped. Both discard sites exist, so check which one a given spelling reaches.

    Each case returns the resulting COUNT, so a lowering that compiled but resized wrongly
    would still fail.
    """
    for method, expected in (("resize(5.usize())", 5), ("truncate(1.usize())", 1), ("clear()", 0)):
        label = method.split("(")[0]
        yield (f"discarded_darray_{label}", f"""
def main() -> i64:
	xs: mutable darray[i64] = []
	xs.push(7)
	xs.push(8)
	xs.push(9)
	_ = xs.{method}
	return xs.count.i64()
""")


def gen_brace_membership_ranges():
    """`x in {1..=3, 5..<7}` -- a brace membership set containing RANGE candidates.

    Membership lowers to an OR-chain of ICmp EQ over the candidates. A range is not a
    scalar, so emit_expression declined it and killed the ENTIRE chain: every membership
    set containing a range declined, while the all-scalar form (`x in {1, 2, 3}`)
    compiled. Ranges now lower as `x >= lo and x <(=) hi`, synthesized as expressions and
    routed back through emit_expression so the signed-vs-unsigned compare choice is not
    duplicated.

    The fixture folds membership over probes 0..=7 into a BITMASK, so inclusive-vs-
    exclusive boundary errors change the answer rather than merely compiling: `..=`
    must include 3 and `..<` must exclude 7. Expected 118 (0b01110110), which fits in a
    byte so exit-status truncation cannot mask a mismatch.
    """
    yield ("brace_membership_ranges", """
def keep(value: i64) -> bool:
	return value in {1..=3, 5..<7}

def main() -> i64:
	total: mutable i64 = 0
	for probe in 0..=7:
		total <- total * 2 + (1 if keep(probe) else 0)
	return total
""")
    # Leading-dot shorthand CANDIDATES (`kind in {.IF, .LET}`). Same OR-chain, but
    # emit_expression knows only the qualified `Enum.Variant` spelling, so each
    # shorthand candidate declined. Resolved through the same helper the `is` path
    # uses. Expected 6 (0b110): IF and LET are members, IDENT is not.
    #
    # NOT pinned: `kind in {.IF..=IDENT}` -- a range whose UPPER bound is a BARE
    # unqualified enum member rather than a shorthand. That needs bare-ident-in-enum
    # -context resolution, which is a separate gap and still declines.
    yield ("brace_membership_shorthand_members", """
const enum TokenKind of u32:
	IF
	LET
	IDENT

def keep(kind: TokenKind) -> bool:
	return kind in {.IF, .LET}

def main() -> i64:
	total: mutable i64 = 0
	total <- total * 2 + (1 if keep(TokenKind.IF) else 0)
	total <- total * 2 + (1 if keep(TokenKind.LET) else 0)
	total <- total * 2 + (1 if keep(TokenKind.IDENT) else 0)
	return total
""")


def gen_checked_index_else():
    """`get xs[i] else FALLBACK` -- a BOUNDS-CHECKED darray index.

    This is NOT the Refinement node the other `get ... else` forms use: the SUBSCRIPT
    postfix consumes the `else` itself (accept_subscript_else), producing
    `Binary(Index(xs, i), TokenKind.Else, FALLBACK)`, which `get` then wraps in a GetElse
    with an EMPTY recovery list. `grep TokenKind.Else src/backend` found nothing at all --
    the checked-index operator was simply unimplemented in codegen.

    The fixture reads two IN-RANGE indices and one PAST THE END, weighting them by powers
    of 3 so every position contributes distinctly: 1*27 + 2*9 + 7 = 52, small enough that
    exit-status truncation cannot mask a mismatch. A lowering that ignored the bounds test
    would read past the end instead of yielding 7.
    """
    yield ("checked_index_else_darray", """
def at(xs: darray[i64]&, i: usize) -> i64:
	return get xs[i] else 7

def main() -> i64:
	xs: mutable darray[i64] = []
	xs.push(1)
	xs.push(2)
	return at(xs, 0.usize()) * 27 + at(xs, 1.usize()) * 9 + at(xs, 2.usize())
""")


def gen_record_update():
    """`base{field = v}` -- a RECORD UPDATE: the base value with named fields overridden
    and every other field COPIED. `grep RecordUpdate src/backend` found nothing, so the
    form was unimplemented in codegen (and the typer had no case either, so an annotated
    destination could not infer it).

    The fixture updates the MIDDLE field of three and reads all three back, so the
    copy-the-rest half is what the answer depends on: 1*100 + 9*10 + 3 = 193. A lowering
    that zeroed untouched fields instead of copying them would give 90. Fits in a byte,
    so exit-status truncation cannot mask a mismatch.
    """
    yield ("record_update_copies_untouched_fields", """
struct Acc:
	first: i64
	second: i64
	third: i64

def bump(base: Acc, v: i64) -> Acc:
	return base{second = v}

def main() -> i64:
	start: Acc = Acc{first: 1, second: 2, third: 3}
	updated: Acc = bump(start, 9)
	return updated.first * 100 + updated.second * 10 + updated.third
""")


def gen_move_as_destructure():
    """`move pair as Pair(left, right)` -- a DESTRUCTURING move.

    The parser lowers it to Block("move", ...) wrapping a Match whose arms have EMPTY
    bodies plus one uninitialized VarDecl per binder. The backend handled no "move" block
    kind at all, so every use declined. stage0 lowers it as a plain per-field extract into
    fresh locals -- the arms carry no runtime test because the scrutinee's STATIC type
    already names the struct.

    The fixture uses ASYMMETRIC field values so a position mix-up changes the answer
    rather than merely compiling: 3*10 + 5 = 35, where swapped binders would give 53.
    """
    yield ("move_as_destructure_positions", """
struct Pair:
	left: mutable i64
	right: mutable i64

def split(pair: Pair) -> i64:
	move pair as Pair(left, right)
	return left * 10 + right

def main() -> i64:
	return split(Pair{left: 3, right: 5})
""")


def gen_float_pointer_cast():
    """`v.cast[heap u8&]` from an f64 -- a FLOAT source reinterpreted as a pointer.

    There is no direct opcode and `inttoptr double` is invalid IR, so the integer step
    has to be spelled out: stage0 emits `fptoui` then `inttoptr`. stage1's reinterpret
    gate admitted only pointer, integer and narrowed-optional-pointer sources, so a float
    fell through and declined.

    Round-tripped back through `.uintptr()` so the VALUE is checked (42), not just that
    the program builds.
    """
    yield ("float_to_pointer_cast_roundtrip", """
def cast_ptr(v: f64) -> heap u8& can[Unsafe.PointerCast]:
	return v.cast[heap u8&]

def main() -> i64 can[Unsafe.PointerCast]:
	p: heap u8& = cast_ptr(42.0)
	return p.uintptr().i64()
""")


def gen_named_call_argument_order():
    """Labelled call arguments supplied OUT OF ORDER (`combine(y: 7, x: 3)`).

    No bug was found here -- this pins an invariant whose failure mode is a SILENT WRONG
    ANSWER rather than a decline: a backend that ignored the labels and bound positionally
    would compile happily and return 73 instead of 37. Worth a fixture precisely because
    nothing currently fails it.
    """
    yield ("named_call_arguments_out_of_order", """
def combine(x: i64, y: i64) -> i64:
	return x * 10 + y

def main() -> i64:
	return combine(y: 7, x: 3)
""")


def gen_user_enum_named_like_ast_node():
    """A user enum named `Expr` (or Node/Stmt/Decl/Pattern) -- the compiler's own AST
    node names.

    These five were effectively RESERVED in stage1: `new_struct_table` reserved AST
    packed-store headers for them in EVERY program, so an ordinary `enum Expr:` found a
    packed slot already present, was registered as a packed AoS enum instead of a payload
    enum, and its constructor declined. Renaming the enum to `Shape` compiled the
    byte-identical program -- the bug was reachable by NAME ALONE.

    One case per reserved name so a partial fix cannot pass, and each RUNS (payload bound
    from one variant, constant from the other) rather than merely compiling: 3*10 + 5 = 35.
    """
    for name in ("Expr", "Node", "Stmt", "Decl", "Pattern"):
        yield (f"user_enum_named_{name.lower()}", f"""
enum {name}:
	Leaf(v: i64)
	Missing

def score(e: {name}) -> i64:
	match e:
		{name}.Leaf(k):
			return k
		{name}.Missing:
			return 5
	return 9

def main() -> i64:
	return score({name}.Leaf(3)) * 10 + score({name}.Missing)
""")


def gen_nested_variant_subpattern():
    """A NESTED variant sub-pattern in a single-field payload --
    `Expr.Leaf(Token.Ident)`, and the alternation `Expr.Leaf(Token.Ident | Token.Keyword)`.

    The match emitter accepted only a Binding or Wildcard as a single-field sub-pattern,
    so both declined. stage0 loads the payload at ITS OWN type and compares against the
    nested variant's ordinal, falling through on a mismatch; this now does the same, with
    the alternation OR-ing the comparisons.

    Both fixtures probe EVERY variant and weight the results, so an arm that matched
    without testing the nested pattern changes the answer rather than merely compiling:
    the single form gives 100 (110 if untested), the alternation 110 (111 if untested).

    A nested variant that itself BINDS still declines -- its sub-fields would have to be
    read too, and matching without testing them is a wrong answer, not a drop.
    """
    yield ("nested_variant_subpattern_single", """
enum Token:
	Ident
	Keyword
	Other

enum Expr:
	Leaf(kind: Token)
	Missing

def score(expr: Expr) -> i64:
	match expr:
		Expr.Leaf(Token.Ident):
			return 1
		_:
			return 0

def main() -> i64:
	return score(Expr.Leaf(Token.Ident)) * 100 + score(Expr.Leaf(Token.Keyword)) * 10 + score(Expr.Missing)
""")
    yield ("nested_variant_subpattern_or", """
enum Token:
	Ident
	Keyword
	Other

enum Expr:
	Leaf(kind: Token)
	Missing

def score(expr: Expr) -> i64:
	match expr:
		Expr.Leaf(Token.Ident | Token.Keyword):
			return 1
		_:
			return 0

def main() -> i64:
	return score(Expr.Leaf(Token.Ident)) * 100 + score(Expr.Leaf(Token.Keyword)) * 10 + score(Expr.Leaf(Token.Other))
""")


def gen_loop_where_filter():
    """`for x in xs where COND:` -- a boolean filter on a container loop.

    The parser wraps the iterable as Expr.Refinement(base, condition) and NOTHING in the
    loop emitter matched Refinement, so the whole loop declined -- a plain boolean filter,
    not just the pattern-filter forms. Desugared to `for x in base: if COND: body`, which
    reaches every iteration path (darray, fixed array, dict, enumerate) untouched.

    The fixture keeps one element BELOW the threshold so a dropped filter changes the
    answer: 5 + 3 = 8, versus 9 if the filter were ignored.

    NOT covered, deliberately: a RANGE base (`for i in 0..<10 where c:`). stage0's PARSER
    rejects that outright ("expected :, got where") while stage1's parser accepts it, so
    emitting it would run a program stage0 refuses -- the PERMISSIVE direction. The
    backend declines that shape so both compilers keep refusing it.
    """
    yield ("loop_where_filter_container", """
def total(xs: darray[i64]&) -> i64:
	sum: mutable i64 = 0
	for x in xs where x > 2:
		sum <- sum + x
	return sum

def main() -> i64:
	xs: mutable darray[i64] = []
	xs.push(1)
	xs.push(5)
	xs.push(3)
	return total(xs)
""")


def gen_loop_bare_pattern_filter():
    """`for item in items where Expr.Int(value):` -- a BARE PATTERN filter, no `item is`
    in front. It BINDS the payload as well as testing the tag, so it is not a boolean
    condition and could not go through the plain `where` desugaring.

    It is exactly what `LOOPVAR is Enum.Variant(binders)` already means, and that form was
    fully lowered, so the loop rewrites to it rather than growing a second
    pattern-matching path. (The semantic half -- putting the binders in scope -- landed
    separately in 7d4b49c3 / 0f03de4a.)

    The fixture interleaves a NON-matching variant between two matching ones, so a filter
    that failed to skip would add garbage and a binding that read the wrong field would
    change the sum: 4 + 9 = 13.

    Multi-binder loops (`for k, v in d where ...`) still decline -- there is no single
    subject for the `is` test.
    """
    yield ("loop_bare_pattern_filter", """
enum Expr:
	Int(value: i64)
	Missing

def total(items: darray[Expr]&) -> i64:
	sum: mutable i64 = 0
	for item in items where Expr.Int(value):
		sum <- sum + value
	return sum

def main() -> i64:
	xs: mutable darray[Expr] = []
	xs.push(Expr.Int(4))
	xs.push(Expr.Missing)
	xs.push(Expr.Int(9))
	return total(xs)
""")


def gen_struct_pattern_tests_and_nesting():
    """Struct patterns with LITERAL/shorthand field tests and one level of NESTING --
    `tok is Token(kind: .INTEGER, span: Span(start: start), value: value)`.

    Three separate gaps met here. The `is` struct path modelled only bare-Ident fields
    (all bindings, result a constant true), so a field tested against a constant declined.
    The PARENTHESISED spelling parses as a labelled CALL, not Expr.Construct, so it was
    never seen at all -- and the NESTED pattern inside it is a labelled call too, which is
    why normalising only the outer level left the function still declined.

    The fixture feeds one MATCHING and one NON-matching token, so a pattern that ignored
    the `.INTEGER` test would take the arm for both: 70 when correct (7*10 + 0), 76 if the
    test were dropped.
    """
    yield ("struct_pattern_tests_and_nesting", """
const enum Tok of i32:
	INTEGER = 1
	FLOAT = 2

struct Span:
	start: i64
	finish: i64

struct Token:
	kind: Tok
	span: Span
	value: i64

def score(tok: Token) -> i64:
	if tok is Token(kind: .INTEGER, span: Span(start: start), value: value):
		return start + value
	return 0

def main() -> i64:
	hit: Token = Token{kind: Tok.INTEGER, span: Span{start: 3, finish: 9}, value: 4}
	miss: Token = Token{kind: Tok.FLOAT, span: Span{start: 5, finish: 9}, value: 6}
	return score(hit) * 10 + score(miss)
""")


def gen_untyped_literal_binding():
    """`seed = 3` -- an UNTYPED local declared by first assignment from an integer
    literal.

    A bare `x = v` folds to Stmt.Assign, NOT Stmt.VarDecl, so the VarDecl site's
    "integer literal defaults to signed 64" rule never reached it: an int literal has no
    intrinsic type, inference left it Unmodeled, and the declaration declined. (Third
    time this session a fix landed on the VarDecl path when the spelling reaches Assign.)
    """
    yield ("untyped_literal_binding", """
def main() -> i64:
	seed = 3
	other = 5
	return seed * 10 + other
""")


# NOT a generator: labelled arguments through a `fn`-typed local
# (`runner(y: 7, x: 3)`) are a KNOWN PARITY GAP. stage1 used to answer 73 where stage0
# answers 37 -- a SILENT WRONG ANSWER, because the indirect call path takes no argument
# names and passed them POSITIONALLY. stage1 now DECLINES that form, which makes the case
# a DECLINE outcome, and DECLINE is ratcheted at ZERO by adversarial_differential_smoke --
# adding it would fail the gate without fixing anything. Documented in
# stage0-backend-corpus-gap instead. The DIRECT labelled call
# (gen_named_call_argument_order) stays a MATCH and proves labels are honoured wherever
# the target's parameter names can be resolved.


def gen_do_block_declaration():
    """`x = do: <stmts> <tail>` -- an un-annotated declaration from a VALUE BLOCK.

    Its type is the TAIL's, but the tail routinely names locals the block itself declares
    (`do: base = 5 / base + 7`), so it cannot be typed before those statements run:
    expression_type answered Unmodeled and the declaration declined. The statements are
    now emitted FIRST, then the tail is typed and emitted with the block's locals in
    scope.

    The fixture's tail DEPENDS on a block-local, which is the whole difficulty -- a
    version whose tail used only outer scope would pass without the fix.
    """
    yield ("do_block_declaration", """
def build() -> i64:
	value = do:
		base = 5
		base + 7
	return value

def main() -> i64:
	return build()
""")


def gen_flat_container_literal_declaration():
    """`values = [1, 2, 3, 4]` -- an un-annotated declaration from a CONTAINER LITERAL.

    expression_type answers Unmodeled for a literal by design (a literal DEFERS to its
    expected type), so the declaration declined even though the annotated form works.
    literal_container_type derives the shape from the elements; it is used only at the
    declaration site, never taught to expression_type, because a global change there
    previously produced a WRONG ANSWER for nested literals.

    FLAT only, matching stage0: it infers this but REJECTS `m = [[1, 2], [3, 4]]`
    ("cannot infer element type for empty darray builder"). Taking the nested shape too
    made stage1 run a program stage0 refuses -- PERMISSIVE, which the gate ratchets at
    zero. The nested form still declines, so both compilers refuse it.

    The fixture slices the inferred darray and indexes the view, so the element type has
    to be right, not merely present.
    """
    yield ("flat_container_literal_declaration", """
def head_of_middle() -> int:
	values = [1, 2, 3, 4]
	part: view[int] = values[1:3]
	return part[0]

def main() -> i64:
	return head_of_middle().i64()
""")


def gen_extend_darray_from_view():
    """`xs.extend(v)` where v is a `view[T]` -- appending a view's elements to a darray.

    `extend` was modelled for a darray source, an sview BYTE source, an array literal and
    a comprehension, but not for a typed view, so the whole function declined. Lowered on
    the same shape as the sview path (loop the length, push `src[i]`, reusing the existing
    view indexing) but element-typed, with the source and target element types required to
    agree.

    The fixture extends from a SLICE of the middle (`src[1:4]`), sums the result and
    reports the count, so both WHICH elements were copied and HOW MANY have to be right:
    9*10 + 3 = 93. Copying the whole source instead would give 153.
    """
    yield ("extend_darray_from_view", """
def copy_span(src: darray[i64]) -> i64:
	xs: mutable darray[i64] = []
	v: view[i64] = src[1:4]
	xs.extend(v)
	total: mutable i64 = 0
	for x in xs:
		total <- total + x
	return total * 10 + xs.count.i64()

def main() -> i64:
	s: mutable darray[i64] = []
	s.push(1)
	s.push(2)
	s.push(3)
	s.push(4)
	s.push(5)
	return copy_span(s)
""")


def gen_resize_non_scalar_element():
    """`darray[view[u8]].resize(n)` -- resizing a container whose ELEMENT is not a scalar.

    The growth loop was always element-type agnostic; only the FILL was not. It pushed an
    `IntLit(0)`, so the method was restricted to scalar elements and a container element
    declined. A non-scalar element now fills with `zeroed`, the language's own zero value.

    Pins BOTH element kinds in one fixture, so generalising the fill cannot regress the
    scalar path it replaced: 8*10 + 3 = 83. The scalar case also starts non-empty, so a
    resize that ignored the existing count would report the wrong number.
    """
    yield ("resize_non_scalar_element", """
def kernel() -> usize:
	xs: mutable darray[view[u8]] = []
	_ = xs.resize(8.usize())
	return xs.count

def scalar_still_works() -> usize:
	ys: mutable darray[i64] = []
	ys.push(7)
	_ = ys.resize(3.usize())
	return ys.count

def main() -> i64:
	return kernel().i64() * 10 + scalar_still_works().i64()
""")


def gen_literal_payload_is_test():
    """`node is Expr.Float(3.14)` -- a LITERAL payload sub-pattern in an `is` test.

    A binder ident NARROWS (binds the payload); a literal is a VALUE TEST -- it matches
    only when the tag agrees AND the payload equals the literal. Only binders were
    modelled, so every literal payload declined. Handled for the SINGLE-field variant;
    a multi-field variant with literals mixed in keeps declining rather than testing some
    fields and silently ignoring others.

    Each fixture probes three cases -- matching payload, NON-matching payload, and a
    different variant -- so both halves of the conjunction have to work: 100 when correct,
    110 if the payload test were dropped, 101 if the tag test were.

    The float case is pinned separately because it must compare with FCmp, not ICmp.
    """
    yield ("literal_payload_is_test_int", """
enum E:
	A(v: int)
	B

def is_seven(node: E) -> bool:
	return node is E.A(7)

def main() -> i64:
	hit: i64 = 1 if is_seven(E.A(7)) else 0
	miss: i64 = 1 if is_seven(E.A(9)) else 0
	other: i64 = 1 if is_seven(E.B) else 0
	return hit * 100 + miss * 10 + other
""")
    yield ("literal_payload_is_test_float", """
enum Expr:
	Float(PI: f64)
	Int(value: int)

def is_pi(node: Expr) -> bool:
	return node is Expr.Float(3.14)

def main() -> i64:
	hit: i64 = 1 if is_pi(Expr.Float(3.14)) else 0
	miss: i64 = 1 if is_pi(Expr.Float(2.71)) else 0
	other: i64 = 1 if is_pi(Expr.Int(3)) else 0
	return hit * 100 + miss * 10 + other
""")


def gen_static_compile_time_call():
    """`static answer(2)` / `static: answer(2)` where `answer` is a `static def`.

    A call to a static def is COMPILE-TIME only -- stage0 evaluates it during static
    execution and emits nothing (`keep()` lowers to an empty body, with no `@answer` in
    the module). select_module_declarations already drops `static def` declarations, so
    the callee has no FnTable entry, the call could not be emitted, and it took the whole
    enclosing function down with it.

    The fixture deliberately ALSO contains a `static if` whose taken branch mutates a
    local, because that is the reason a static block emits inline at all: dropping the
    whole block instead of just the compile-time calls would lose it. 5 + 3 = 8.
    """
    yield ("static_compile_time_call", """
static def answer(step: i64) -> i64:
	return step + 40

def keep() -> i64:
	static answer(2)
	static:
		answer(2)
	total: mutable i64 = 5
	static if true:
		total <- total + 3
	return total

def main() -> i64:
	return keep()
""")


def gen_darray_as_cstr():
    """`xs.as_cstr()` -- borrow a `darray[u8]` as a NUL-terminated C string.

    `grep '"as_cstr"' src/backend` found nothing: unimplemented in codegen, so every use
    dropped its function. Lowered as stage0 does -- make room for one more byte through
    the same grow/realloc path a push uses, write the NUL at index `count`, hand back the
    items pointer -- and the COUNT is deliberately left alone, since the terminator is not
    an element.

    The fixture checks BOTH halves of that: `strlen` reads the terminator (3) while
    `xs.count` must still be 3, so 3*10 + 3 = 33. Incrementing the count would give 34,
    and omitting the NUL would make strlen run off the end.

    It also pins `xs.push([72, 105])` -- an ARRAY-LITERAL argument pushes EVERY element,
    which stage0 lowers as a bulk extend rather than a single push. Mixing the literal and
    scalar forms means a lowering that handled only one of them changes the length.
    """
    yield ("darray_as_cstr", """
extern strlen(s: cstr) -> usize

def main() -> i64:
	can Abort.Panic, Memory.Allocate:
		region r(256)
		in r:
			xs: mutable darray[u8] = []
			xs.push([72, 105])
			xs.push(33)
			s: cstr = xs.as_cstr()
			total: usize = strlen(s) * 10 + xs.count
			destroy r
			return total.i64()
	return 0
""")


def gen_is_bracketed_alternation():
    """`k is [.LT | .LTEQ | .GT | .GTEQ]` -- a BRACKETED ALTERNATION in an `is` test.

    It means "matches any of these", so each alternative is re-entered as its own `is`
    and the results are OR-ed. Reusing the per-leaf lowering is what makes the
    const-enum, leading-dot shorthand and payload-enum forms all work here without
    restating any of them. `|` parses as an ordinary binary operator inside the brackets,
    so the element list is flattened through Pipe/Or first.

    The fixture probes all four members of the alternation AND one outside it, folded
    into a bitmask, so an alternation that matched too much or too little changes the
    answer: 0b11110 = 30.

    The GROUPED spelling `is (A | B | C)` means the same thing and is pinned separately:
    it arrives as a Paren (sometimes nested) around the Pipe chain rather than as an
    Array, so handling only the bracketed form left the grouped one declining -- and the
    corpus uses both in ONE file.
    """
    yield ("is_bracketed_alternation", """
const enum Tok of i32:
	LT = 1
	LTEQ = 2
	GT = 3
	GTEQ = 4
	PLUS = 5

def is_rel(kind: Tok) -> bool:
	return kind is [.LT | .LTEQ | .GT | .GTEQ]

def main() -> i64:
	total: mutable i64 = 0
	total <- total * 2 + (1 if is_rel(Tok.LT) else 0)
	total <- total * 2 + (1 if is_rel(Tok.LTEQ) else 0)
	total <- total * 2 + (1 if is_rel(Tok.GT) else 0)
	total <- total * 2 + (1 if is_rel(Tok.GTEQ) else 0)
	total <- total * 2 + (1 if is_rel(Tok.PLUS) else 0)
	return total
""")


def gen_is_grouped_alternation():
    """`value is (A | B | C)` -- the GROUPED spelling of an alternation, equivalent to the
    bracketed one. Pinned alongside the bracketed form because the corpus file uses both
    and they take different AST shapes (Paren-around-Pipe vs Array).
    """
    yield ("is_grouped_alternation", """
enum Expr:
	Int
	Bool
	Char
	Missing

def grouped(value: Expr) -> bool:
	return value is (
		Expr.Int
		| Expr.Bool
		| Expr.Char
	)

def bracketed(value: Expr) -> bool:
	return value is [Expr.Int | Expr.Bool | Expr.Char]

def main() -> i64:
	total: mutable i64 = 0
	total <- total * 2 + (1 if grouped(Expr.Int) else 0)
	total <- total * 2 + (1 if grouped(Expr.Missing) else 0)
	total <- total * 2 + (1 if bracketed(Expr.Char) else 0)
	total <- total * 2 + (1 if bracketed(Expr.Missing) else 0)
	return total
""")


def gen_extern_error_return_not_an_export():
    """An `extern f(...) -> T error[E]` carries an internal `__error_return` annotation on
    `f`. The export-target lookup used to return the FIRST non-`__export_fn` annotation on
    an owner, so that internal marker read as an export target name: the export path fired
    on a plain extern, failed to build a wrapper for a target called "__error_return", and
    recorded `f` as DECLINED even though its declaration had lowered correctly.

    The fixture pairs a real `export fn` with such an extern so BOTH halves are pinned --
    the export must still emit, and the extern must stop declining. The harness ratchets
    declines at zero, which is what makes this fixture able to fail.
    """
    yield ("extern_error_return_not_an_export", """
error IoError:
	NotFound

extern read_file(path: u8&) -> cstr[file_text] error[IoError]

def add_impl(a: i64, b: i64) -> i64:
	return a + b

export fn add_two(a: i64, b: i64) -> i64 = add_impl

def main() -> i64:
	return add_impl(17, 25)
""")


def gen_unified_else_recovery():
    """The two `else`-recovery shapes that both parse to `Expr.GetElse` in RETURN position.

    `return get OPT else return V` -- emit_expression has no GetElse case, so the return
    path declined until it routed through the local-declaration emitter.

    `return try f(x) else err: BLOCK` -- the SAME node, but the guarded expression is an
    error-returning call, so the recovery runs on a nonzero status code rather than on an
    absent payload; the value emitter only knew how to PROPAGATE.

    Each is probed on both branches and folded into one number, so a recovery arm that runs
    when it shouldn't (or never runs) changes the answer: 7*10+11 = 81 and 7*10+13 = 83.
    """
    yield ("unified_else_recovery", """
error FileError:
	NotFound

def maybe_value(flag: bool) -> i64?:
	if flag:
		return 7
	return null

def read_value(flag: bool) -> i64 error[FileError]:
	if flag:
		return 7
	raise FileError.NotFound

def optional_return(flag: bool) -> i64:
	return get maybe_value(flag) else return 11

def try_error_binding(flag: bool) -> i64:
	return try read_value(flag) else err:
		return 13

def main() -> i64:
	got: i64 = optional_return(true) * 10 + optional_return(false)
	caught: i64 = try_error_binding(true) * 10 + try_error_binding(false)
	return got + caught - 100
""")


def gen_get_else_raise():
    """`x: T = get OPT else raise E.Tag` -- a `raise` recovery on a monadic unwrap.

    `raise` TERMINATES, but the recovery parser only treated return/break/continue that
    way; everything else was parsed as a value FALLBACK and folded into a Refinement node,
    which types the recovered expression by a value the branch never produces. The branch
    that makes unwrapping the optional sound was lost.

    Probed on both the present and absent path through a `catch`, so a recovery that does
    not actually raise changes the answer: 30 + 7 = 37.
    """
    yield ("get_else_raise", """
error MemoryError:
	OutOfMemory

def helper(n: i64) -> i64?:
	return 3 if n > 0 else null

def checked(n: i64) -> i64 error[MemoryError]:
	v: i64 = get helper(n) else raise MemoryError.OutOfMemory
	return v * 10

def run(n: i64) -> i64:
	return catch checked(n):
		ok:
			ok
		error e:
			7

def main() -> i64:
	return run(1) + run(-1)
""")


def gen_nullable_extern_ref_get():
    """`p: T& = get memchr(...) else raise E.Tag` over a NULLABLE-REFERENCE extern.

    stage0 represents `-> heap T&?` as a bare ptr with null meaning absent, so the extern
    registers as a plain Ref and the `get` path -- which tests for an Optional -- declined.
    Ref-ness alone is not enough to accept: stage0 REJECTS `get` on a non-nullable `T&`, so
    the marker for `?` is carried from the parser through FnTable.returns_nullable.

    memchr is the nullable source rather than a failing malloc: a huge malloc DOES return
    null at -O0 but the optimizer assumes success at -O2, which made an earlier version of
    this fixture report a spurious MISMATCH. memchr's answer is decided by the data.

    Both branches are real -- 'b' is in "abc", 'z' is not -- folded to 5*10+3 = 53, so a
    present-check with the wrong polarity changes the answer.
    """
    yield ("nullable_extern_ref_get", """
error MemoryError:
\tNotThere

extern memchr(s: cstr, c: i32, n: usize) -> heap void&?

def find_byte(c: i32) -> i64 error[MemoryError]:
\thit: heap void& = get memchr("abc", c, 3.usize()) else raise MemoryError.NotThere
\t_ = hit
\treturn 5

def attempt(c: i32) -> i64:
\treturn catch find_byte(c):
\t\tok:
\t\t\tok
\t\terror e:
\t\t\t3

def main() -> i64:
\treturn attempt(98) * 10 + attempt(122)
""")


def gen_labelled_call_through_fn_alias():
    """`runner(y: 7, x: <do-block>)` where `runner: fn(i64,i64)->i64 = add`.

    A `fn(...)` TYPE carries parameter types but no parameter NAMES, so there was nothing to
    reorder labels against and the call declined (it had earlier passed them POSITIONALLY,
    a silent wrong answer). The local now remembers which function it aliases, and the
    labels resolve against that function's parameter names.

    `add` SUBTRACTS and the labels are given in reverse order, so a lowering that ignores
    the labels yields 7-30 = -23 instead of 30-7 = 23.
    """
    yield ("labelled_call_through_fn_alias", """
def add(x: i64, y: i64) -> i64:
	return x - y

def build() -> i64:
	runner: fn(i64, i64) -> i64 = add
	return runner(y: 7, x: do:
		seed = 30
		seed
	)

def main() -> i64:
	return build()
""")


def gen_shadowing_assignment_declaration():
    """`acc = acc + 4` inside a nested block, where `acc` is already bound outside.

    stage1 declined this, treating an already-bound name as "not a declaration". stage0's
    rule is that `=` NEVER mutates -- `<-` is the mutation operator -- so the inner form
    reads the outer binding and declares a NEW one that dies with the block.

    The fixture makes the two readings differ: probe(true)*10 + probe(false) is 11 under
    shadowing and 51 if the assignment mutated the outer binding.
    """
    yield ("shadowing_assignment_declaration", """
def probe(flag: bool) -> i64:
	acc: mutable i64 = 1
	if flag:
		acc = acc + 4
	return acc

def main() -> i64:
	return probe(true) * 10 + probe(false)
""")


def gen_proof_block_erasure():
    """`assert C by:` and `proof C:` -- proof blocks whose BODY is compile-time only.

    Both parse to the same node, with the GOAL riding as body[0] and the proof steps after
    it. stage0 lowers the goal as an ordinary runtime contract check and emits nothing for
    the body; stage1 declined the whole block because the kind was unhandled.

    Three distinct spellings (assert-by, proof, `ensure ... by scoped:`) with different
    return arithmetic, summed to 46, so a block whose goal was dropped or whose body leaked
    into the emitted code changes the answer.
    """
    yield ("proof_block_erasure", """
lemma weaken(x: i64):
	requires x >= 10
	ensure x >= 5
	pass

def use(n: i64) -> i64:
	assert n >= 5 by:
		assert(n >= 10)
		weaken(n)
	return n

def proven(n: i64) -> i64:
	proof n >= 5:
		assert(n >= 10)
		weaken(n)
	return n + 1

def scoped_ensure(n: i64) -> i64:
	ensure result >= 5 by scoped:
		assert(result >= 10)
		weaken(result)
	return n + 10

def main() -> i64:
	return use(12) + proven(20) + scoped_ensure(3)
""")


def gen_first_query():
    """`first VAR in ITER where COND` -- the query whose result is an Optional.

    Two things were missing. The lowering itself (min/max were the only Optional-producing
    folds), and -- the reason a correct lowering still declined -- `first` was absent from
    comprehension_is_extremum, so emit_expression re-emitted it at the PAYLOAD type and the
    comprehension emitter saw `expected` = i64 instead of i64?.

    The probe list is [-3, 7, 5, -1]: `first` answers 7 where any extremal fold answers 5,
    so a min/max-shaped lowering yields 53 instead of 73. The second list has no match, so
    the absent path is exercised too.
    """
    yield ("first_query", """
def first_positive(items: darray[i64]) -> i64?:
	return first item in items where item > 0

def probe(items: darray[i64]) -> i64:
	f: i64? = first_positive(items)
	if f is hit:
		return hit
	return 3

def main() -> i64:
	a: darray[i64] = [-3, 7, 5, -1]
	b: darray[i64] = [-3, -5]
	return probe(a) * 10 + probe(b)
""")


def gen_refined_type_alias():
    """`type Lane4 = u32 is InRange[0, 3]` and `type Pct = i64 where ...` -- REFINED aliases.

    Both erase at runtime (stage0 lowers a `Lane4` parameter as a plain i32 and emits no
    check), but neither target is a type EXPRESSION: the `is` form is a Binary, and the
    fallback head heuristic keeps the last Ident in the span, which is the LAW's name. The
    alias stayed Unmodeled, so every function mentioning it declined -- including ones that
    only did arithmetic on the value.

    Both spellings are exercised, one as an ARRAY INDEX (30) and one in arithmetic (23),
    summing to 53 -- so an alias resolved to the wrong width or a dropped index changes it.
    """
    yield ("refined_type_alias", """
law InRange(self: u32, lo: u32, hi: u32) = self >= lo and self <= hi

type Lane4 = u32 is InRange[0, 3]
type Pct = i64 where 0 <= self and self <= 100

struct Vec4:
	lanes: mutable array[u32, 4]

def read_lane(v: Vec4&, lane: Lane4) -> u32:
	return v.lanes[lane]

def scale(p: Pct) -> i64:
	return p * 2 + 1

def main() -> i64:
	v: Vec4 = Vec4{lanes: [10, 20, 30, 40]}
	return read_lane(&v, 2.u32()).i64() + scale(11)
""")


def gen_builtin_string_surface():
    """Two independent gaps on the byte-array / string-view surface.

    `text[1]` on a `u8[4]` returned the raw i8 without converting to the EXPECTED type, so
    a `-> char` (or plain `-> i64`) context failed the return path's type-identity guard and
    the function declined -- while the same expression with an explicit `.i64()` compiled.
    The sibling optional-ref read one branch above already did the conversion.

    `sview[LO, HI]` is a LENGTH-BOUNDED view whose bounds are a type-level refinement with
    no representation (stage0 lowers it to a plain %StringView), but the annotation resolver
    had no case for it, so it stayed Unmodeled and the unbounded spelling was the only one
    that worked.

    Distinct indices and a subtraction, so a wrong element or a wrong width changes the
    answer: 66 - 67 + 120 - 100 = 19.
    """
    yield ("builtin_string_surface", """
def first_char(text: u8[4]) -> char:
	return text[1]

def wide(text: u8[4]) -> i64:
	return text[2]

def view_char(text: sview[0, 4]) -> char:
	return text[1]

def main() -> i64:
	buf: array[u8, 4] = [65.u8(), 66.u8(), 67.u8(), 68.u8()]
	return first_char(buf).i64() - wide(buf) + view_char("wxyz").i64() - 100
""")


def gen_fixed_array_slice_to_view():
    """`text[1:3]` on a `u8[4]` -- slicing a FIXED ARRAY into a `view[T]`.

    The fat-view slice path handled only darray sources; an array source fell through to a
    guard that declines every container (that guard is load-bearing -- the cstr byte-slice
    path below it byte-GEPs the container header and miscompiles). Unlike a darray there is
    no items pointer to extract: the array IS the storage, so the view points into the
    array's own slot, which is stage0's lowering too.

    The two slice elements are read back with DISTINCT weights (23), so an off-by-one in
    the start offset or a length computed from the wrong end changes the answer.
    """
    yield ("fixed_array_slice_to_view", """
def probe(text: u8[4]) -> i64:
	part: view[u8] = text[1:3]
	return part[0].i64() * 10 + part[1].i64()

def main() -> i64:
	buf: array[u8, 4] = [1.u8(), 2.u8(), 3.u8(), 4.u8()]
	return probe(buf)
""")


def gen_view_iteration():
    """`for x in v:` over a `view[T]`, from both a darray slice and a fixed-array slice.

    A view is a `{ptr data, i64 len}` VALUE, not a header in memory like a darray, so the
    loop emitter's darray branch could not take it and nothing else did. View INDEXING
    worked all along, which is how the gap stayed hidden -- it only shows up when the same
    view is iterated.

    Each loop folds its elements positionally (total*10 + x), so a reversed traversal, an
    off-by-one length, or a dropped element changes the answer: 23 and 23.
    """
    yield ("view_iteration", """
def from_darray(xs: darray[i64]) -> i64:
	part: view[i64] = xs[1:3]
	total: mutable i64 = 0
	for b in part |total|:
		total <- total * 10 + b
	return total

def from_array(text: u8[4]) -> i64:
	part: view[u8] = text[1:3]
	total: mutable i64 = 0
	for b in part |total|:
		total <- total * 10 + b.i64()
	return total

def main() -> i64:
	xs: darray[i64] = [1, 2, 3, 4]
	buf: array[u8, 4] = [1.u8(), 2.u8(), 3.u8(), 4.u8()]
	return from_darray(xs) + from_array(buf)
""")


def gen_function_value_erasure_cast():
    """`inc.cast[uintptr]` -- a bare FUNCTION NAME's address as an integer, then called back
    through `bits.cast[fn(i64) -> i64]`.

    The reverse direction (integer to fn) and the same cast through a fn-typed LOCAL both
    worked; only the bare name declined, because expression_type answers Unmodeled for a
    function name used as a VALUE (it types locals, not the FnTable) so the Fn branch of the
    cast never fired.

    TWO different functions are round-tripped and their results weighted differently
    (42*10 + 43 - 400 = 63), so a cast that lost track of which function it addressed --
    the failure mode that matters here -- changes the answer.
    """
    yield ("function_value_erasure_cast", """
def inc(value: i64) -> i64:
	return value + 1

def dec(value: i64) -> i64:
	return value - 1

def call_bits(bits: uintptr, value: i64) -> i64:
	f: fn(i64) -> i64 = bits.cast[fn(i64) -> i64]
	return f(value)

def main() -> i64:
	up: uintptr = inc.cast[uintptr]
	down: uintptr = dec.cast[uintptr]
	return call_bits(up, 41) * 10 + call_bits(down, 44) - 400
""")


def gen_fixed_array_slice_shapes():
    """The remaining fixed-array slice shapes: a REF receiver, and indexing a slice DIRECTLY.

    `values[1:3]` where `values: i32[4]&` -- the value in hand is already the array's
    address, so no temp is needed, but the by-value branch could not take it.

    `values[1:3][0]` -- every slice path keys off an EXPECTED view type, and here the
    expected type is the ELEMENT's, so nothing produced the view and the chain resolver
    declined. The slice is now emitted at the view type its receiver implies, then read
    through.

    Three readings at distinct powers of two (8, 4, 1) over [1, 2, 3, 4], each picking a
    DIFFERENT element, so any one wrong offset changes the total: 3*8 + 2*4 + 4 = 36.
    Deliberately sized to fit in a byte -- an earlier version returned 324 and "agreed"
    only after exit-status truncation.
    """
    yield ("fixed_array_slice_shapes", """
def by_value(values: i32[4]) -> i32:
	return values[1:3][1]

def by_ref(values: i32[4]&) -> i32:
	return values[1:3][0]

def ref_view(values: i32[4]&) -> i32:
	part: view[i32] = values[2:4]
	return part[1]

def main() -> i64:
	buf: array[i32, 4] = [1, 2, 3, 4]
	return by_value(buf).i64() * 8 + by_ref(&buf).i64() * 4 + ref_view(&buf).i64()
""")


def gen_rev_iteration():
    """`for value in rev(xs):` -- the reversed-iteration builtin.

    stage1 did not know the name at all: the resolver reported "undefined identifier 'rev'",
    a FALSE REJECTION of a program stage0 compiles, not a decline. `rev` is not a real call
    (nothing declares it) -- it wraps the iterable and flips the traversal order, so the loop
    reads the same container with only the element index mirrored.

    The fixture folds positionally in BOTH directions over [1, 2, 3] and subtracts, so a
    `rev` that quietly iterated forward yields 0 instead of 321 - 123 = 198.
    """
    yield ("rev_iteration", """
def build(items: darray[i64]) -> i64:
	total: mutable i64 = 0
	for value in rev(items):
		total <- total * 10 + value
	return total

def forward(items: darray[i64]) -> i64:
	total: mutable i64 = 0
	for value in items |total|:
		total <- total * 10 + value
	return total

def main() -> i64:
	xs: darray[i64] = [1, 2, 3]
	return build(xs) - forward(xs)
""")


GENERATORS += [gen_shorthand_member_is, gen_builtin_view_type_name,
               gen_void_return_call, gen_copy_array_builtin,
               gen_discarded_darray_growth_methods, gen_brace_membership_ranges,
               gen_checked_index_else, gen_record_update, gen_move_as_destructure,
               gen_float_pointer_cast, gen_named_call_argument_order,
               gen_user_enum_named_like_ast_node, gen_nested_variant_subpattern,
               gen_loop_where_filter, gen_loop_bare_pattern_filter,
               gen_struct_pattern_tests_and_nesting, gen_untyped_literal_binding,
               gen_do_block_declaration, gen_flat_container_literal_declaration,
               gen_extend_darray_from_view, gen_resize_non_scalar_element,
               gen_literal_payload_is_test, gen_static_compile_time_call,
               gen_darray_as_cstr, gen_is_bracketed_alternation,
               gen_is_grouped_alternation, gen_extern_error_return_not_an_export,
               gen_unified_else_recovery, gen_get_else_raise,
               gen_nullable_extern_ref_get, gen_labelled_call_through_fn_alias,
               gen_shadowing_assignment_declaration, gen_proof_block_erasure,
               gen_first_query, gen_refined_type_alias,
               gen_builtin_string_surface, gen_fixed_array_slice_to_view,
               gen_view_iteration, gen_function_value_erasure_cast,
               gen_fixed_array_slice_shapes, gen_rev_iteration]
GENERATORS += [gen_signedness, gen_string_escapes, gen_const_enum_values,
               gen_type_mismatches, gen_queries, gen_as_bindings,
               gen_struct_operator_protocols, gen_named_tuples,
               gen_ref_returning_call_deref, gen_struct_compound_assign_declines,
               gen_index_compound_assign, gen_darray_of_fixed_array,
               gen_pin_and_range_match_arms, gen_value_match_pin_and_range,
               gen_borrowed_fixed_array_chain, gen_borrowed_fixed_array_mixed_width_read,
               gen_floats, gen_lmut_place_required,
               gen_flags_const_enum_sview, gen_char_literal_never_fits_sview,
               gen_clone_builtin_move_wrapped_source, gen_range_match_value_slot,
               gen_i16_u16_widths, gen_shifts_bitwise_and_size_types,
               gen_mutable_ref_local_rebind, gen_generic_operator_no_bound]


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    results = {"MATCH": [], "MISMATCH": [], "O2_MISMATCH": [], "O2_DECLINE": [], "DECLINE": [], "PERMISSIVE": [], "SKIP": []}
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
            continue
        # Optimisation must not change the answer. Only checked once the -O0 answer already
        # agrees, so a row here always means "the pipeline changed a CORRECT answer".
        ok2, rc2 = build_and_run(path, d, "s1O2")
        if not ok2:
            results["O2_DECLINE"].append((name, rc1, None))
        elif rc2 != rc1:
            results["O2_MISMATCH"].append((name, rc1, rc2))
        else:
            results["MATCH"].append((name, rc0, rc1))
    for k in ("MISMATCH", "O2_MISMATCH", "O2_DECLINE", "DECLINE", "PERMISSIVE", "SKIP", "MATCH"):
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
          f"{len(results['SKIP'])} skipped")
    print(f"work dir: {work}")
    # RATCHET. All three of these are at zero and must stay there:
    #   MISMATCH   a silent wrong answer — the worst outcome there is
    #   DECLINE    stage0 built it, stage1 could not (an acceptance gap)
    #   PERMISSIVE stage0 rejects it, stage1 builds it (the direction no census can see)
    # SKIP is not ratcheted: it means the ORACLE could not arbitrate (stage0 rejects the
    # program, or crashes on it), which says nothing about stage1. Keep those few honest by
    # fixing the generator program rather than by tolerating the skip.
    return 1 if results["MISMATCH"] or results["O2_MISMATCH"] or results["O2_DECLINE"] or results["DECLINE"] or results["PERMISSIVE"] else 0

if __name__ == "__main__":
    sys.exit(main())
