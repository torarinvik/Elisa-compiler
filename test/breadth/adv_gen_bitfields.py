#!/usr/bin/env python3
"""Adversarial differential generators — `try` as a binary operand, const dict tables, sub-byte enum bitfields, view slice
offsets, scoped arena allocators, proof-carrying view helpers, reduce/zip over
views, and the bitset/bitfield packing rules

Each generator yields (name, source) pairs; adversarial_differential.py runs them.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))




def gen_try_as_binary_operand():
	"""`return (try f(x)) and COND` — a propagating try as an OPERAND rather than the whole
	returned expression.

	The value form only matched a try that WAS the entire return value, so the same call
	one level in declined. It is now bound to a synthetic local first, which propagates on
	the error path exactly as the whole-expression form does.

	All four outcomes are folded into one exit code: both sides of the `and` true, the
	left true with the right false, the left false, and the callee RAISING — so a dropped
	propagation, a short-circuit evaluated in the wrong order, or a lost operand shows up.
	"""
	yield ("try_as_binary_operand", """
error RuntimeError:
	OutOfMemory

def inner(x: int) -> bool error[RuntimeError]:
	if x < 0:
		raise RuntimeError.OutOfMemory
	return x > 3

def outer(x: int) -> bool error[RuntimeError]:
	return (try inner(x)) and x == 7

def probe(x: int) -> int:
	ok: bool = try outer(x) else return 9
	return 1 if ok else 0

def main() -> i64:
	total: mutable int = 0
	total <- total * 10 + probe(7)
	total <- total * 10 + probe(5)
	total <- total * 10 + probe(1)
	total <- total * 10 + probe(-1)
	return total.i64() % 251
""")




def gen_const_dict_table():
	"""`const NUMBERS: dict[cstr, u8] = {…}` — a COMPILE-TIME dict, laid out statically.

	stage0 builds the whole table at compile time and this reproduces its algorithm
	exactly (read from its source, not guessed from its IR): capacity 8 doubling while
	`count*4 > capacity*3`, FNV-1a 64 over the key bytes, `slot = hash & (capacity-1)`
	with linear probing, buckets of `{key, value, i8 state}` and a header whose fields 1
	AND 2 are both the entry count.

	The seven-entry dict is the one that matters: it forces the capacity to GROW to 16, so
	a wrong load-factor rule changes every slot. Both counts are folded into the exit code.
	"""
	yield ("const_dict_table", """
const NUMBERS: dict[cstr, u8] = {"one": 1, "two": 2, "three": 3}
const WIDE: dict[cstr, u8] = {"a": 1, "b": 2, "c": 3, "d": 4, "e": 5, "f": 6, "g": 7}

def main() -> i64:
	return (NUMBERS.count * 100 + WIDE.count).i64()
""")




def gen_subbyte_enum_bitfield():
	"""A bitfield member whose type is a SUB-BYTE-backed const enum — `mode: Mode` where
	`Mode` is `const enum … of u4`.

	`u4` is not a modeled type NAME (stage0 rejects a `u4` PARAMETER, and stage1 must keep
	rejecting one), so the enum's BACKING was unmodeled and the whole enum was discarded,
	taking every mention of `Mode.Fast` with it. The backing is now widened for the enum
	only, and a sub-byte width reaches the LLVM type as a real narrow integer.

	Both a plain sub-byte member and the enum-typed one are written and read back, and the
	tag is read at a non-zero bit offset, so a lost widening, a wrong mask or a wrong
	offset all flip the answer.
	"""
	yield ("subbyte_enum_bitfield", """
const enum Mode of u4:
	None = 0
	Fast = 3

struct Header:
	flags: bitset:
		has_read
		has_write
	layout: bitfield:
		tag: u4
		mode: Mode
		active: u1

def build() -> bool:
	header: Header = zeroed
	header.flags.has_read <- true
	header.layout.tag <- 7
	header.layout.mode <- Mode.Fast
	return header.flags.has_read and header.layout.tag == 7 and header.layout.mode == Mode.Fast

def main() -> i64:
	return 1 if build() else 0
""")




def gen_view_slice_offsets():
    """Slicing a `view[T]` at a NON-ZERO start, then iterating and indexing it.

    The slice emitter had no case for a view receiver, so it fell through to the CSTR path:
    the whole `{data, len}` AGGREGATE went to GEP, producing
    `getelementptr i8, %DynArrayView %load, i64 0` -- malformed IR. It survived at -O0 and
    became TWO -O2 defects, both fixed by extracting the data field first:

      * `whole[0]..whole[3]` off a darray slice returned 255 at -O2 where -O0 and stage0 both
        say 230 -- an optimisation-only WRONG ANSWER;
      * `for x in v` CRASHED the compiler at -O2 inside the pass pipeline.

    The offset is also in ELEMENTS, not bytes, which is why the slice here starts at 4: a
    byte-addressed walk lands mid-element and cannot produce 64. The view is iterated AND
    indexed, and cross-checked against the same element read through the unsliced view.

    No view program was in this corpus before, which is how both -O2 defects stayed hidden:
    the backend corpus has view shapes but never RUNS them, and this one runs everything but
    had no view.
    """
    yield ("view_slice_offsets", """
def kernel(buf: view[i64]) -> i64:
	whole: view[i64] = buf[0:8]
	hi: view[i64] = readonly(whole[4:8])
	total: mutable i64 = 0
	for x in hi:
		total <- total * 10 + x
	return total * 10 + hi[0] + whole[4]

def main() -> i64:
	xs: mutable darray[i64] = []
	for n in 1..=8:
		xs.push(n)
	v: view[i64] = xs[0:8]
	return kernel(v) % 251
""")




def gen_with_arena_scoped_allocator():
    """`with arena scratch(4096) as owner:` -- a SCOPED ALLOCATOR block.

    It is the region block in different clothes: an owned arena of the given capacity, live
    for the body, freed at scope end. Rewritten into the region form rather than duplicating
    the arena setup, unwind bookkeeping and frame tracking -- so `defer`, early `return` and
    nested regions keep behaving exactly as they do for `region`.

    The parser also had to capture the capacity, which it did only for `region` and `pool`;
    without it the clause held names but no size to open an arena with.

    A container is grown INSIDE the block and folded positionally, so a body that allocated
    from the wrong arena (or from none) cannot give 230.
    """
    yield ("with_arena_scoped_allocator", """
def build() -> i64:
	can Memory.Allocate:
		with arena scratch(4096) as owner:
			xs: mutable darray[i64] = [1, 2, 3]
			xs.push(4)
			total: mutable i64 = 0
			for x in xs:
				total <- total * 10 + x
			return total

def main() -> i64:
	return build() % 251
""")




def gen_proof_carrying_view_helpers():
    """`split_at` and `chunks_exact` -- the proof-carrying view helpers.

    stage0's layouts, read off its IR rather than invented:
    `%SplitView__T = { %DynArrayView, %DynArrayView }` and
    `%ChunksExactView__T = { %DynArrayView, i64 chunk, i64 count }`. Both are built INLINE --
    the halves and the chunks are ordinary view slices, so there is no runtime helper to call.

    `readonly(x)` also had to TYPE as its operand, not just emit as it: `chunks_exact(readonly(v), n)`
    read its argument's type to find the element, and an Unmodeled answer declined the call.

    Every read is positional and the chunk size (3) differs from the split point (2), so a
    chunk stride in bytes rather than elements, a split that kept the wrong half, or an
    off-by-one count all change the answer.
    """
    yield ("proof_carrying_view_helpers", """
def run(values: darray[i64, 6]) -> i64:
	base: view[i64] = values[0:6]
	halves: SplitView[i64] = split_at(base, 2)
	left: view[i64] = halves.left
	right: view[i64] = halves.right
	chunks: ChunksExactView[i64] = chunks_exact(readonly(base), 3)
	first: view[i64] = chunks[0]
	total: mutable i64 = left[0] * 100 + left[1] * 10 + right[0]
	total <- total * 10 + first[2]
	for chunk in chunks:
		total <- total * 10 + chunk[0] + chunk[2]
	return total

def main() -> i64:
	ys: mutable darray[i64, 6] = [1, 2, 3, 4, 5, 6]
	return run(ys) % 251
""")




def gen_derived_state_is_test():
    """`player is Player[Alive]` -- a DERIVED STATE test.

    There is no state tag to read: the state IS a predicate over the value's fields, and
    stage0 inlines the declared rule (`derive state: Alive when self.health > 0` becomes
    `extractvalue …, 0; icmp sgt i64 %health, 0` right at the `is`). `self` in the condition
    denotes the scrutinee, so it is bound to the scrutinee's own slot for the emit.

    The parser already captured the rules on `file.derived_state_rules` — only the backend was
    missing, which is why the whole function declined rather than mis-testing.

    BOTH states are exercised (health 7 -> Alive, health 0 -> Dead), so a test stuck at true or
    false cannot give 70.
    """
    yield ("derived_state_is_test", """
struct Player[state Alive | Dead]:
	health: int

	derive state:
		Alive when self.health > 0
		Dead when self.health <= 0

def score(player: Player) -> int:
	if player is Player[Alive]:
		return player.health
	return 0

def main() -> i64:
	alive: Player = Player{health: 7}
	dead: Player = Player{health: 0}
	return score(alive) * 10 + score(dead)
""")




def gen_reduce_sum_over_view():
    """`reduce_sum(v, f, extra…)` and its method spelling `v.reduce_sum(f)`.

    stage0 emits a plain counted loop with two phis (index and accumulator), calling
    `f(elem, extra…)` per element — no runtime helper. The method form is rewritten to the
    function form so there is one implementation rather than two that can drift.

    Both spellings run over the SAME view with DIFFERENT folds (`+ bias` vs `* 2`) and the
    results are combined positionally, so a fold that dropped an element, ignored the extra
    argument, or reused the wrong accumulator changes the answer.
    """
    yield ("reduce_sum_over_view", """
def add_bias(value: i64, bias: i64) -> i64:
	return value + bias

def sum_one(value: i64) -> i64:
	return value * 2

def run(values: darray[i64, 4], bias: i64) -> i64:
	base: view[i64] = values[0:4]
	direct: i64 = readonly(base).reduce_sum(sum_one)
	return reduce_sum(readonly(base), add_bias, bias) * 4 + direct

def main() -> i64:
	xs: mutable darray[i64, 4] = [1, 2, 3, 4]
	return run(xs, 10)
""")




def gen_zip_map_over_views():
    """`zip_map(dst, a, b, f)` -- elementwise `dst[i] = f(a[i], b[i])`.

    The bound is the DESTINATION's length, which is what stage0 uses (`zip_map.total` comes
    off the dst view). Same counted-loop shape as reduce_sum, storing instead of accumulating.

    `f` is ASYMMETRIC (`left * 10 + right`), so swapping the two source views changes the
    answer, and the check reads an element JUST PAST the destination slice as well — a write
    that ran one element long would corrupt it.
    """
    yield ("zip_map_over_views", """
def add(left: i64, right: i64) -> i64:
	return left * 10 + right

def kernel(buf: view[i64]) -> void:
	whole: view[i64] = buf[0:6]
	ro: view[i64] = readonly(whole)
	zip_map(whole[0:2], ro[2:4], ro[4:6], add)

def main() -> i64:
	xs: mutable darray[i64, 6] = [0, 0, 3, 4, 5, 6]
	v: view[i64] = xs[0:6]
	kernel(v)
	return xs[0] * 2 + xs[1] + xs[2]
""")




def gen_bitset_named_flags():
    """Any NAMED member of a `bitset:` group, read and written.

    Only two flag names were ever handled — `has_suffix` and `has_prefix`, the ones the
    self-host `Token` struct uses — so every other flag declined on BOTH the read and the
    write. The bit offset now comes from the group's recorded member list, which the parser
    already carried.

    The fixture sets the SECOND flag and reads BOTH back, so writing the wrong bit, or
    clobbering the neighbouring flag, changes the answer.
    """
    yield ("bitset_named_flags", """
struct Header:
	flags: bitset:
		has_read
		has_write

def build() -> i64:
	header: mutable Header = zeroed
	header.flags.has_write <- true
	first: i64 = 1 if header.flags.has_write else 0
	second: i64 = 1 if header.flags.has_read else 0
	return first * 10 + second

def main() -> i64:
	return build()
""")




def gen_bitfield_member_widths():
    """`bitfield:` members wider than one bit, and a one-bit one beside them.

    Two things the earlier bitset-only support got wrong:

    * the WIDTH came from `annotation_value_type`, which does not model sub-byte types, so
      `tag: u4` fell back to ONE BIT and packed 9 into a single bit. The width is read off the
      declared name instead (a `uN` form, or a const enum's backing width).
    * a one-bit BITFIELD member is an INTEGER (`active: u1` takes `1`), not a bool — the group
      KIND decides that, not the width. Keying on the width made `active <- 1` decline.

    The fixture writes both members, reads both, then REWRITES `tag` and re-checks `active` —
    so a wrong width, a wrong offset, or a write that clobbered its neighbour changes the
    answer. 87 under both compilers.
    """
    yield ("bitfield_member_widths", """
struct Header:
	layout: bitfield:
		tag: u4
		active: u1

def build() -> i64:
	header: mutable Header = zeroed
	header.layout.tag <- 9
	header.layout.active <- 1
	first: i64 = 1 if header.layout.tag == 9 else 0
	second: i64 = 1 if header.layout.active == 1 else 0
	header.layout.tag <- 5
	third: i64 = 1 if header.layout.active == 1 else 0
	fourth: i64 = 1 if header.layout.tag == 5 else 0
	return first * 1000 + second * 100 + third * 10 + fourth

def main() -> i64:
	return build()
""")




def gen_bitfield_pack_width():
    """A `bitfield:` group WIDER than one byte.

    The backing integer was sized by the COUNT of members (`flag_count <= 8 -> u8`), which is
    right for a bitset (one bit each) and wrong for a bitfield: three `u4` members are TWELVE
    bits and need an i16, while a count of 3 picked an i8 and the third member's bits fell off
    the top. The pack now sums the members' WIDTHS, computed the same way the offsets are — the
    two must agree or an offset lands outside the pack.

    All three members are written and read back with DISTINCT values, so a pack that truncated
    the group, or an offset past its end, changes the answer.
    """
    yield ("bitfield_pack_width", """
struct Header:
	layout: bitfield:
		a: u4
		b: u4
		c: u4

def build() -> i64:
	header: mutable Header = zeroed
	header.layout.a <- 9
	header.layout.b <- 5
	header.layout.c <- 3
	first: i64 = 1 if header.layout.a == 9 else 0
	second: i64 = 1 if header.layout.b == 5 else 0
	third: i64 = 1 if header.layout.c == 3 else 0
	return first * 100 + second * 10 + third

def main() -> i64:
	return build()
""")




def gen_packed_new_store_selector():
    """`new[store] E.V(...)` -- an EXPLICIT allocation target, outside any `in store:` block,
    with the store later handed on by `freeze(move store)`.

    Only the AMBIENT active store was honoured. The parser CONSUMES the `new[...]` bracket and
    leaves a line-keyed `__region_use` row, which the backend never read -- so every packed
    program that allocates without an enclosing `in` block declined, which was most of the
    remaining ones.

    `freeze` itself needs no backend work: stage0 emits a plain load/store (frozen and local
    stores are bit-identical) and stage1's parser already discards the marker, leaving a
    `move` the expression emitter handles.

    The payload is read BACK through the frozen store (5), so a row allocated from the wrong
    store -- or from none -- cannot pass.
    """
    yield ("packed_new_store_selector", """
packed enum Expr:
	Lit(value: i64)
	End

def fold_frozen() -> i64:
	region scratch(256)
	store: Expr.Store[Local] = Expr.Store(scratch)
	node: Expr = new[store] Expr.Lit(value: 5)
	frozen: Expr.Store[Frozen] = freeze(move store)
	match node in frozen:
		Expr.Lit(value):
			out: i64 = value
			destroy scratch
			return out
		Expr.End:
			destroy scratch
			return 0

def main() -> i64:
	return fold_frozen()
""")



def gen_packed_forward_declared_payload_enum():
    """A packed enum whose payload field names a packed enum declared LATER in the file.

    Registration walks declarations in SOURCE order, so `Expr` was still unregistered when
    `Clause.Terminal(body: Expr)` was registered: the field resolved to Unmodeled, which
    DECLINED the whole `Clause` enum -- and with it every match and every construction over
    it. stage0 has no such order dependence; swapping the two declarations compiled the
    byte-identical program, which is what made the asymmetry visible.

    Both orders are generated, and each reads a payload back THROUGH the handle (9 + 1), so a
    Clause whose row is laid out wrongly cannot pass by accident.
    """
    body = """
def score_clause(node: Clause, clauses: Clause.Store[Frozen], exprs: Expr.Store[Frozen]) -> i64:
	match node in clauses:
		Clause.Terminal(body: body):
			return score_expr(body, exprs) + 1

def score_expr(node: Expr, exprs: Expr.Store[Frozen]) -> i64:
	match node in exprs:
		Expr.Literal(value: value):
			return value

def main() -> i64:
	region scratch(512)
	exprs: Expr.Store[Local] = Expr.Store(scratch)
	clauses: Clause.Store[Local] = Clause.Store(scratch)
	lit: Expr = new[exprs] Expr.Literal(value: 9)
	clause: Clause = new[clauses] Clause.Terminal(body: lit)
	frozen_exprs: Expr.Store[Frozen] = freeze(move exprs)
	frozen_clauses: Clause.Store[Frozen] = freeze(move clauses)
	out: i64 = score_clause(clause, frozen_clauses, frozen_exprs)
	destroy scratch
	return out
"""
    clause_decl = """@packed_profile(retained_reads)
packed enum Clause:
	Terminal(body: Expr)
"""
    expr_decl = """@packed_profile(retained_reads)
packed enum Expr:
	Literal(value: i64)
"""
    yield ("packed_forward_declared_payload_enum", clause_decl + "\n" + expr_decl + body)
    yield ("packed_backward_declared_payload_enum", expr_decl + "\n" + clause_decl + body)


GENERATORS = [
    gen_try_as_binary_operand,
    gen_const_dict_table,
    gen_subbyte_enum_bitfield,
    gen_view_slice_offsets,
    gen_with_arena_scoped_allocator,
    gen_proof_carrying_view_helpers,
    gen_derived_state_is_test,
    gen_reduce_sum_over_view,
    gen_zip_map_over_views,
    gen_bitset_named_flags,
    gen_bitfield_member_widths,
    gen_bitfield_pack_width,
    gen_packed_new_store_selector,
    gen_packed_forward_declared_payload_enum,
]
