#!/usr/bin/env python3
"""Adversarial differential generators — `when` tables, `defer` inside a region, error unions, struct field defaults,
and lambdas with their captures

Each generator yields (name, source) pairs; adversarial_differential.py runs them.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))




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
    yield ("when_string_bool_columns", """
def pick(text: sview, enabled: bool) -> i64:
    return when text, enabled:
        "module" | "extend", _ -> 1
        "ghost", true -> 2
        _, _ -> 3

def main() -> i64:
    return pick("extend", false) * 100 + pick("ghost", true) * 10 + pick("ghost", false)
""")
    yield ("when_cstr_statement_columns", """
global mutable answer: i64 = 0

def choose(text: cstr, enabled: bool) -> void:
    when text, enabled:
        "module" | "extend", _ ->
            answer <- 4
        "ghost", true ->
            answer <- 7
        _, _ ->
            answer <- 9

def main() -> i64:
    choose("ghost", true)
    return answer
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


GENERATORS = [
    gen_when_tables,
    gen_defer_region,
    gen_error_unions,
    gen_struct_defaults,
    gen_lambdas_closures,
]
