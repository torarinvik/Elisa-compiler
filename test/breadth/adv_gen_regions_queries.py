#!/usr/bin/env python3
"""Adversarial differential generators — function values erased through a cast, fixed-array slice shapes, reverse
iteration, region qualifiers and arena-local pins, and the projection/each
query forms with their guards

Each generator yields (name, source) pairs; adversarial_differential.py runs them.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))




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




def gen_region_qualifier_pin():
    """`zs: darray[i64] @host = [...]` -- an explicit REGION PIN on a local declaration.

    stage1's codegen dropped the qualifier entirely and allocated from whatever arena was
    ambient. That is not a wrong number, it is a USE-AFTER-FREE: a container pinned to a
    longer-lived region landed in a shorter-lived one and its data was freed underneath the
    program. stage0 answers 60 here; stage1 segfaulted.

    Both fixtures declare inside `region tmp:` while pinning to the OUTER `host`, and read
    the data AFTER tmp has ended -- the only shape that can catch this, since every
    same-scope read finds the wrong arena still alive. The second also PUSHES twice, so the
    pin has to survive into the growth path (reallocation) and not just the initial
    allocation.
    """
    yield ("region_qualifier_pin", """
def main() -> i64:
	region host(4096)
	total: mutable i64 = 0
	ys: mutable darray[i64] = []
	region tmp(4096):
		zs: darray[i64] @host = [10, 20, 30]
		ys <- zs
	for y in ys |total|:
		total <- total + y
	destroy host
	return total
""")
    yield ("region_qualifier_pin_growth", """
def main() -> i64:
	region host(4096)
	total: mutable i64 = 0
	ys: mutable darray[i64] = []
	region tmp(4096):
		zs: mutable darray[i64] @host = [10, 20]
		zs.push(30)
		zs.push(40)
		ys <- zs
	for y in ys |total|:
		total <- total + y
	destroy host
	return total
""")




def gen_arena_local_region_pin():
    """`@alloc` where `alloc` is an `Arena&`-typed LOCAL, not a `region R:` block or a
    `[@r]` region parameter.

    stage1 rejected it outright -- "unknown region qualifier" -- because the scope check
    knew only those two forms. An `Arena&` local owns a region too.

    Two lifetimes again: the comprehension is built inside `region tmp:` but pinned to
    `host` through the alias, and read after tmp ends. A pin that resolved to the wrong
    arena, or was dropped, loses the data rather than answering 6 + 8 = 14.
    """
    yield ("arena_local_region_pin", """
def build(owner: Arena, rest: darray[i64]) -> darray[i64]:
	alloc: mutable Arena& = (&owner).cast[mutable Arena&]
	xs: darray[i64] @alloc = [item + 1 for item in rest if item > 0]
	return xs

def main() -> i64:
	region host(4096)
	total: mutable i64 = 0
	ys: mutable darray[i64] = []
	region tmp(4096):
		rest: darray[i64] = [5, -2, 7]
		ys <- build(host, rest)
	for y in ys |total|:
		total <- total + y
	destroy host
	return total
""")




def gen_enum_variant_view_after_is():
    """`node.left` after `if node is Expr.Pair:` -- reading a payload field through the
    NARROWED variant view, with no binding pattern to introduce the name.

    stage0 lowers it as a plain payload GEP + extract in the proven branch; stage1 had no
    case for a payload-enum receiver in field position at all.

    The variant is selected by FIELD NAME and only when exactly one variant declares it --
    with two variants sharing a name the offsets can differ and only the branch knows which
    is right, so that declines instead of guessing.

    Asymmetric payload values (3, 4) and a non-matching variant probe, folded to 70, so
    reading the wrong field or the wrong offset changes the answer.
    """
    yield ("enum_variant_view_after_is", """
enum Expr:
	Pair(left: i64, right: i64)
	Int(value: i64)

def score(node: Expr) -> i64:
	if node is Expr.Pair:
		return node.left + node.right
	return 0

def main() -> i64:
	return score(Expr.Pair(3, 4)) * 10 + score(Expr.Int(9))
""")




def gen_bare_variant_loop_filter():
    """`for item in items where Expr.Int:` -- a payload-FREE variant pattern as a loop filter.

    The existing bare-pattern rewrite required a CALL (`where Expr.Int(value)`), so the
    spelling with no binder list parsed as a plain Field, was treated as a boolean
    condition, and declined -- an enum variant is not a bool.

    It is resolved against the enum TABLES rather than by shape, because `where e.enabled`
    is the same Field node; the fixture exercises BOTH in one program, so a rewrite that
    caught the ordinary boolean filter too would change the answer. Matches fold
    positionally (11) and the boolean filter sums a single enabled row (4).
    """
    yield ("bare_variant_loop_filter", """
enum Expr:
	Int(value: i64)
	Missing

struct Entry:
	name: i64
	enabled: bool

def count_ints(items: array[Expr, 3]) -> i64:
	total: mutable i64 = 0
	for item in items where Expr.Int:
		total <- total * 10 + 1
	return total

def sum_enabled(items: darray[Entry]) -> i64:
	total: mutable i64 = 0
	for e in items where e.enabled:
		total <- total + e.name
	return total

def main() -> i64:
	xs: array[Expr, 3] = [Expr.Int(1), Expr.Missing, Expr.Int(2)]
	es: darray[Entry] = [Entry{name: 4, enabled: true}, Entry{name: 8, enabled: false}]
	return count_ints(xs) + sum_enabled(es)
""")




def gen_loop_pattern_filter_guard():
    """`for item in items where item is Expr.Int(value): value > 2:` -- a pattern filter
    with a GUARD.

    The parser parsed the guard and threw it away. That was not a decline: stage1 compiled
    the loop and ran it over every Int, so `where … : value > 2` silently summed values the
    guard excludes. The guard is now retained as a second Refinement layer, and the flow
    resolver walks it in the PATTERN's scope so it can see the payload bindings.

    Guarded and unguarded forms run over the same list in one program and are folded
    positionally with different weights, so dropping the guard (or applying it to the wrong
    form) changes the answer: 34*2 + 314 - 600 = 38.
    """
    yield ("loop_pattern_filter_guard", """
enum Expr:
	Int(value: i64)
	Missing

def guarded(items: array[Expr, 4]) -> i64:
	acc: mutable i64 = 0
	for item in items where item is Expr.Int(value): value > 2:
		acc <- acc * 10 + value
	return acc

def unguarded(items: array[Expr, 4]) -> i64:
	acc: mutable i64 = 0
	for item in items where item is Expr.Int(value):
		acc <- acc * 10 + value
	return acc

def main() -> i64:
	xs: array[Expr, 4] = [Expr.Int(3), Expr.Missing, Expr.Int(1), Expr.Int(4)]
	return guarded(xs) * 2 + unguarded(xs) - 600
""")




def gen_catch_per_variant_arms():
    """`catch f(x):` with per-VARIANT error arms (`NotFound:` / `Busy:`) rather than a
    single `error e:` catch-all.

    Two things were wrong, and the first hid the second. A bare undotted name in pattern
    position is `Pattern.Binding`, NOT `Pattern.Variant` (parse_pattern_primary returns a
    Variant only for a dotted path), so the arm matched none of the shapes the error-arm
    loop handles. And the ordinal lookup scanned only PAYLOAD enums -- an `error E:` with no
    payload variants registers as a CONST enum, so even after the rewrite the name resolved
    to nothing.

    Each variant returns a different value and the three branches are weighted apart
    (7*100 + 1*10 + 2 = 712), so dispatching to the wrong arm changes the answer. A name
    two error sets share still declines rather than picking one.
    """
    yield ("catch_per_variant_arms", """
error FileError:
	NotFound
	Busy

def read_value(flag: i64) -> i64 error[FileError]:
	if flag == 1:
		raise FileError.NotFound
	if flag == 2:
		raise FileError.Busy
	return 7

def load(flag: i64) -> i64:
	return catch read_value(flag):
		value:
			value
		NotFound:
			1
		Busy:
			2

def main() -> i64:
	return load(0) * 100 + load(1) * 10 + load(2)
""")




def gen_each_collection_query():
    """`each item in items where c` -- the COLLECTION query, which returns a darray.

    It carries no projection body (the element IS the binder), so it means exactly
    `[item for item in items if c]`. The collection branch already lowered that, but bailed
    on a body-less node -- and, once the identity body was supplied, the darray-source path
    pushed the ORIGINAL `body` at a second emit site the first patch never touched. Both
    sites now use the substituted body.

    `each` and the equivalent comprehension run over the same list and are weighted apart
    (2*34 - 34 = 34), so an `each` that collected nothing, or collected the wrong elements,
    changes the answer while the comprehension acts as the control.
    """
    yield ("each_collection_query", """
def positives(items: darray[i64]) -> darray[i64]:
	return each item in items where item > 0

def comp(items: darray[i64]) -> darray[i64]:
	return [item for item in items if item > 0]

def fold(xs: darray[i64]) -> i64:
	total: mutable i64 = 0
	for x in xs |total|:
		total <- total * 10 + x
	return total

def main() -> i64:
	src: darray[i64] = [3, -1, 4]
	return fold(positives(src)) * 2 - fold(comp(src))
""")
    # The SVIEW source has its own emit site, which needed the same substitution.
    yield ("each_collection_query_sview", """
def picks(text: sview) -> darray[u8]:
	return each c in text where c > 97.u8()

def fold(xs: darray[u8]) -> i64:
	total: mutable i64 = 0
	for x in xs |total|:
		total <- total * 10 + (x.i64() - 96)
	return total

def main() -> i64:
	return fold(picks("abcd"))
""")




def gen_first_projection_query():
    """`entry.name for first entry in entries where entry.enabled` -- the PROJECTION form of
    the `first` query, whose result is an Optional of the PROJECTED type, not the element's.

    Two defects on one path. The parser's projection suffix never recorded the `__query`
    HEAD marker (only the leading-keyword form did), so `query_head_for` answered "" and
    `first` was not recognised as producing its own Optional: emit_expression re-emitted the
    node at the payload type and the comprehension emitter took the integer-fold path, where
    an unknown head declines. And the first-quantifier had no projection support -- it
    required the element and the result to be the same type, which a projection breaks.

    Probed on a hit (the SECOND matching entry must not win -- 5, not 7) and a miss, folded
    to 59.
    """
    yield ("first_projection_query", """
struct Entry:
	name: i64
	enabled: bool

def first_enabled(entries: darray[Entry]) -> i64?:
	return entry.name for first entry in entries where entry.enabled

def probe(entries: darray[Entry]) -> i64:
	f: i64? = first_enabled(entries)
	if f is hit:
		return hit
	return 9

def main() -> i64:
	hit: darray[Entry] = [Entry{name: 3, enabled: false}, Entry{name: 5, enabled: true}, Entry{name: 7, enabled: true}]
	miss: darray[Entry] = [Entry{name: 3, enabled: false}]
	return probe(hit) * 10 + probe(miss)
""")




def gen_query_guarded_pattern_filter():
    """`all|any item in items where item is Expr.Int(value): value > 0` -- a query filter
    with a PATTERN and a GUARD.

    The parser has no separate slot for the guard, so it rides in the quantifier's BODY --
    and the quantifier branch excluded any node with a body, on the assumption that a body
    meant a projection. The guard is now evaluated on the MATCHED side of the pattern test,
    where the payload bindings are live.

    It cannot be folded to `condition and guard`: stage0 REJECTS that spelling in a query
    filter ("undefined identifier" for the binder), so emitting it would be permissive.

    Six independent bits at distinct weights (52 = 0b110100) -- both quantifiers over an
    all-pass, a mixed and an all-fail list -- so any single wrong answer moves the total.
    """
    yield ("query_guarded_pattern_filter", """
enum Expr:
	Int(value: i64)
	Missing

def all_pos(items: array[Expr, 3]) -> bool:
	return all item in items where item is Expr.Int(value): value > 0

def any_pos(items: array[Expr, 3]) -> bool:
	return any item in items where item is Expr.Int(value): value > 0

def bit(b: bool) -> i64:
	return 1 if b else 0

def main() -> i64:
	pos: array[Expr, 3] = [Expr.Int(1), Expr.Int(2), Expr.Int(3)]
	mixed: array[Expr, 3] = [Expr.Int(1), Expr.Int(-2), Expr.Int(3)]
	none: array[Expr, 3] = [Expr.Int(-1), Expr.Missing, Expr.Int(-3)]
	return bit(all_pos(pos)) * 32 + bit(any_pos(pos)) * 16 + bit(all_pos(mixed)) * 8 + bit(any_pos(mixed)) * 4 + bit(all_pos(none)) * 2 + bit(any_pos(none))
""")




def gen_each_guarded_pattern_filter():
    """`each item in items where item is Expr.Int(value): value > 0` -- the COLLECTION query
    with a pattern filter AND a guard.

    The body slot of a leading-keyword query means two different things: a GUARD here, and a
    PROJECTION in `EXPR for each x in xs`. The backend cannot tell them apart from the node,
    and collecting the guard would push a BOOL as the element -- so the guarded case is
    marked by the parser (`__query_guard`) and the two roles split on that marker: the
    element is the binder, and the guard joins the filter.

    Before the marker this shape declined rather than mis-answering (the bool did not type
    as the element), but the hazard was real and is what the marker removes.

    The survivors are folded POSITIONALLY (34), so collecting the wrong elements, or losing
    the guard and keeping the negative, changes the answer.
    """
    yield ("each_guarded_pattern_filter", """
enum Expr:
	Int(value: i64)
	Missing

def score(node: Expr) -> i64:
	match node:
		Expr.Int(v):
			return v
		Expr.Missing:
			return 0

def ints(items: darray[Expr]) -> darray[Expr]:
	return each item in items where item is Expr.Int(value): value > 0

def fold(xs: darray[Expr]) -> i64:
	total: mutable i64 = 0
	for x in xs |total|:
		total <- total * 10 + score(x)
	return total

def main() -> i64:
	src: darray[Expr] = [Expr.Int(3), Expr.Int(-1), Expr.Missing, Expr.Int(4)]
	return fold(ints(src))
""")


GENERATORS = [
    gen_function_value_erasure_cast,
    gen_fixed_array_slice_shapes,
    gen_rev_iteration,
    gen_region_qualifier_pin,
    gen_arena_local_region_pin,
    gen_enum_variant_view_after_is,
    gen_bare_variant_loop_filter,
    gen_loop_pattern_filter_guard,
    gen_catch_per_variant_arms,
    gen_each_collection_query,
    gen_first_projection_query,
    gen_query_guarded_pattern_filter,
    gen_each_guarded_pattern_filter,
]
