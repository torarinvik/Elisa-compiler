#!/usr/bin/env python3
"""Adversarial differential generators — loops, UFCS and module calls, fixed arrays, struct methods, comprehensions,
payload enums, bit operations, generic structs and the std containers, plus
default and named arguments

Each generator yields (name, source) pairs; adversarial_differential.py runs them.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from adversarial_harness import STD




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


GENERATORS = [
    gen_loops_control,
    gen_optionals_refs,
    gen_ufcs_modules,
    gen_arrays_fixed,
    gen_struct_methods,
    gen_comprehensions,
    gen_casts_widths,
    gen_payload_enums,
    gen_bit_operations,
    gen_generic_structs,
    gen_std_containers,
    gen_defaults_and_named_args,
    gen_multi_assign,
    gen_sview_slicing,
]
