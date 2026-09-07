#!/usr/bin/env python3
"""Adversarial differential generators — value matches over pins and ranges, borrowed fixed-array chains and mixed-width
reads, shifts and the size types, i16/u16 widths, darrays of fixed arrays, named
tuples, and an unbound generic operator

Each generator yields (name, source) pairs; adversarial_differential.py runs them.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))




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
    time regardless of any call site. The stage1 declaration-time guard now mirrors this
    rule, including operators nested in value expressions and augmented assignments. See
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
    yield ("generic_operator_no_bound_nested_expression_rejected", """
def pack[T](a: T, b: T) -> darray[T]:
    return [a + b]

def main() -> i64:
    return 0
""")
    yield ("generic_operator_no_bound_compound_rejected", """
def bump_compound[T](a: mutable T, b: T) -> void:
    a += b

def main() -> i64:
    return 0
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


GENERATORS = [
    gen_value_match_pin_and_range,
    gen_borrowed_fixed_array_chain,
    gen_borrowed_fixed_array_mixed_width_read,
    gen_range_match_value_slot,
    gen_shifts_bitwise_and_size_types,
    gen_i16_u16_widths,
    gen_darray_of_fixed_array,
    gen_named_tuples,
    gen_generic_operator_no_bound,
]
