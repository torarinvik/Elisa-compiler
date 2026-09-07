#!/usr/bin/env python3
"""Adversarial differential generators — optional containers, aggregate ABI, queries, deliberate type mismatches,
signedness, string escapes, const-enum values and `as` bindings

Each generator yields (name, source) pairs; adversarial_differential.py runs them.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from adversarial_harness import STD




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


GENERATORS = [
    gen_optional_containers,
    gen_aggregate_abi,
    gen_queries,
    gen_type_mismatches,
    gen_signedness,
    gen_string_escapes,
    gen_const_enum_values,
    gen_as_bindings,
]
