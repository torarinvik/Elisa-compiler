#!/usr/bin/env python3
"""Adversarial differential generators — operator protocols on structs, compound assignment (including the shapes that
must DECLINE), floats, and `pin`/range match arms

Each generator yields (name, source) pairs; adversarial_differential.py runs them.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))




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


GENERATORS = [
    gen_struct_operator_protocols,
    gen_struct_compound_assign_declines,
    gen_index_compound_assign,
    gen_floats,
    gen_pin_and_range_match_arms,
]
