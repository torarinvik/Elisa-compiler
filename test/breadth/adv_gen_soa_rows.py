#!/usr/bin/env python3
"""Adversarial differential generators — SoA row bindings, destructured row loops and `let` destructures, packed `is` tests
inside a store clause, `enumerate` over a fixed array, and the `expect` statement
forms

Each generator yields (name, source) pairs; adversarial_differential.py runs them.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))




def gen_soa_row_view_binding():
    """`view = s[row]` -- a ROW VIEW bound to a name, then read AND written through.

    Two things this pins, both found the hard way:

    * An unannotated `=` to a name that is not yet a local arrives as a `Stmt.Assign`, NOT a
      `Stmt.VarDecl` — the declaration emitter never sees this shape, so the binder is
      recorded from the assignment path.
    * A `RowId[S]` is an i32, and every row emitter wants an i64 offset. Storing the i32
      straight into the index slot is a mismatch LLVM does not diagnose, and it SEGFAULTED
      unoptimised while -O2 folded the bad value away and produced stage0's answer. The index
      is widened explicitly now.

    The fixture indexes with a real RowId (not a literal), mutates through the view, and reads
    back through BOTH the view and a fresh row walk, so an index that lost its high bits or a
    write that landed in the wrong column changes the answer. `s1O2` alone would not have
    caught the crash — the unoptimised build is the one that failed.
    """
    yield ("soa_row_view_binding", """
struct SymbolRows layout(soa):
	name_id: i64
	flags: i64

def build(owner: Arena) -> i64:
	alloc: mutable Arena& = (&owner).cast[mutable Arena&]
	in alloc:
		symbols: mutable SymbolRows = zeroed
		symbols.push(11, 2)
		row: RowId[SymbolRows] = symbols.push(12, 3)
		view = symbols[row]
		view.flags <- 5
		symbols[row].name_id <- 20
		total: mutable i64 = view.name_id * 100 + view.flags * 10 + symbols.count
		for iter_row in symbols.rows:
			total <- total * 100 + iter_row.name_id
		return total

def main() -> i64:
	region scratch(4096)
	out: i64 = build(scratch)
	destroy scratch
	return out % 251
""")




def gen_soa_row_destructured_loop():
    """`for {name_key, depth} in s.rows():` -- a DESTRUCTURED row head.

    The brace form parses as a plain multi-binder loop head, so N binders over a row walk
    means one local per COLUMN in declaration order (one binder still means a row view, and
    two with `.enumerate()` still means index + row).

    The fold is positional across both columns and both rows, so binders bound to the wrong
    column, or a row visited twice, change the answer.
    """
    yield ("soa_row_destructured_loop", """
struct Rows layout(soa):
	name_key: i64
	depth: i64

def build(owner: Arena) -> i64:
	alloc: mutable Arena& = (&owner).cast[mutable Arena&]
	in alloc:
		pending: mutable Rows = zeroed
		pending.push(1, 2)
		pending.push(3, 4)
		total: mutable i64 = 0
		for {name_key, depth} in pending.rows():
			total <- total * 100 + name_key * 10 + depth
		return total

def main() -> i64:
	region scratch(4096)
	out: i64 = build(scratch)
	destroy scratch
	return out % 251
""")




def gen_soa_row_let_destructure():
    """`let {name_key, depth} = row` -- ROW DESTRUCTURING through a `let`.

    The parser lowers a `let` to `Stmt.Block("let", …)` wrapping a ONE-ARM MATCH plus one bare
    `VarDecl(name, Invalid, Absent)` per binder, whose only job is to make the name visible
    after the block. The backend had no case for the "let" block kind at all, so the match
    inside it was never even reached -- instrumenting the MATCH emitter showed no marker
    firing, which is what pointed at the enclosing block rather than the pattern.

    Emitted at the block level (like `move`), binding into the ENCLOSING scope: a scoped emit
    would drop the names at the closing brace, and the trailing declarations carry no type to
    allocate from.

    Both destructuring spellings run here and read the columns in OPPOSITE orders, so a binder
    wired to the wrong column cannot cancel out between them.
    """
    yield ("soa_row_let_destructure", """
struct Rows layout(soa):
	name_key: i64
	depth: i64

def build(owner: Arena) -> i64:
	alloc: mutable Arena& = (&owner).cast[mutable Arena&]
	in alloc:
		pending: mutable Rows = zeroed
		pending.push(1, 2)
		pending.push(3, 4)
		total: mutable i64 = 0
		for row in pending.rows():
			let {name_key, depth} = row
			total <- total * 100 + name_key * 10 + depth
		for {name_key, depth} in pending.rows():
			total <- total * 100 + depth * 10 + name_key
		return total

def main() -> i64:
	region scratch(4096)
	out: i64 = build(scratch)
	destroy scratch
	return out % 251
""")




def gen_packed_in_store_is_test():
    """`if node in STORE is Expr.Variant(binder):` -- the in-store variant test in EXPRESSION
    position.

    `in` and `is` share a precedence level, so the parser hands over `(node in STORE) is
    PATTERN`. Every packed test expects a bare node on the left, so the whole shape declined.
    The STATEMENT form (`match NODE in STORE:`) already had this unwrap; this is its `if` twin:
    make the store active and re-enter with the bare node, so the narrowing paths run
    unchanged.

    BOTH variants are classified and the results are positionally combined (Wrap -> 7,
    Int -> 3), so a test that always took one branch, or that ignored the tag, cannot give 73.
    """
    yield ("packed_in_store_is_test", """
packed enum Expr:
	common:
		span: i64
	Int(value: i64)
	Wrap(child: Expr)

def classify(node: Expr, store: Expr.Store[Local]) -> i64:
	if node in store is Expr.Wrap(child_alias):
		return 7
	if node in store is Expr.Int(v):
		return 3
	return 0

def probe() -> i64:
	region scratch(1024)
	store: Expr.Store[Local] = Expr.Store(scratch)
	leaf: Expr = new[store] Expr.Int(span: 5, value: 7)
	node: Expr = new[store] Expr.Wrap(span: 9, child: leaf)
	out: i64 = classify(node, store) * 10 + classify(leaf, store)
	destroy scratch
	return out

def main() -> i64:
	return probe()
""")




def gen_packed_is_payload_handle():
    """A payload BINDER that is itself a node handle, bound by an `is` test.

    Two AoS-row bugs on the `is`-expression path, both already fixed on the statement-match
    path and both live here:

    * the payload was GEPed at row field 1, but the row is `{i32 tag, <commons x i64>,
      payload}` — with a common declared, field 1 IS the common, so the binder read the SPAN;
    * a payload that is itself a node is an i32 handle in an i64 row word, so it must be
      loaded as the word and narrowed, not loaded as i32 out of an i64 slot.

    The enum declares a common, and the bound handle is passed on to a function that reads
    the CHILD's own payload — so a binder that picked up the span instead of the handle
    resolves a different (or invalid) row and cannot give 77.
    """
    yield ("packed_is_payload_handle", """
packed enum Expr:
	common:
		span: i64
	Int(value: i64)
	Wrap(child: Expr)

def leaf_value(node: Expr, store: Expr.Store[Local]) -> i64:
	if node in store is Expr.Int(v):
		return v
	return 0

def unwrap(node: Expr, store: Expr.Store[Local]) -> i64:
	if node in store is Expr.Wrap(child_alias):
		return leaf_value(child_alias, store)
	return 0

def probe() -> i64:
	region scratch(1024)
	store: Expr.Store[Local] = Expr.Store(scratch)
	leaf: Expr = new[store] Expr.Int(span: 5, value: 7)
	node: Expr = new[store] Expr.Wrap(span: 9, child: leaf)
	out: i64 = unwrap(node, store) * 10 + leaf_value(leaf, store)
	destroy scratch
	return out

def main() -> i64:
	return probe()
""")




def gen_packed_guarded_store_stays_active():
    """`if node in STORE is Expr.Wrap(child): child.span` -- the store must stay ACTIVE for
    the GUARDED BODY.

    The condition activates the store only for its own emission, so a common read in the body
    (`child.span`) had no store to read from and the whole function declined. The then-branch
    now runs under a runtime carrying that store.

    The child and the node have DIFFERENT spans (5 and 9) and both are read, so a body that
    resolved the wrong row — or read the outer node where the child was meant — cannot give
    59.
    """
    yield ("packed_guarded_store_stays_active", """
packed enum Expr:
	common:
		@storage(inline)
		span: i64
	Int(value: i64)
	Wrap(child: Expr)

def fold_child_common_frozen() -> i64:
	region scratch(256)
	store: Expr.Store[Local] = Expr.Store(scratch)
	child: Expr = new[store] Expr.Int(span: 5, value: 7)
	node: Expr = new[store] Expr.Wrap(span: 9, child: child)
	frozen: Expr.Store[Frozen] = freeze(move store)
	if node in frozen is Expr.Wrap(child: child_alias):
		out: i64 = child_alias.span * 10 + node.span
		destroy scratch
		return out
	destroy scratch
	return 0

def main() -> i64:
	return fold_child_common_frozen()
""")




def gen_enumerate_over_fixed_array():
    """`for i, x in items.enumerate()` where `items: array[T, N]`.

    The enumerate head required a DARRAY receiver, so a fixed array declined -- even though
    the plain `for x in items` walk already handled one. Rather than a second copy of the
    loop, it borrows the same trick that walk uses: build a synthetic darray HEADER over the
    array's storage (`fixed_array_header_slot`) and run the darray path unchanged.

    The fold is positional and uses BOTH the index and the element, so an index that started
    at the wrong value, a walk that ran off the extent, or a header whose count was wrong
    changes the answer.
    """
    yield ("enumerate_over_fixed_array", """
def sum(items: array[i64, 3]) -> i64:
	total: mutable i64 = 0
	for index, item in items.enumerate():
		total <- total * 10 + item + index
	return total

def main() -> i64:
	xs: array[i64, 3] = [4, 5, 6]
	return sum(xs) % 251
""")




def gen_destructured_struct_loop_head():
    """`for {index, item} in entries:` -- DESTRUCTURED struct elements in a loop head.

    The brace head parses as a plain multi-binder loop, so N binders over a container of
    STRUCTS means one local per named FIELD -- bound BY NAME, not by position. Works over
    both a darray and a fixed array (the latter through the same synthetic header the plain
    walk uses).

    The two fields carry DIFFERENT weights in the fold (`item * 2 + index`) and the elements
    are all distinct, so binders wired to the wrong field, or bound by position instead of
    name, change the answer.
    """
    yield ("destructured_struct_loop_head", """
struct Entry:
	index: i64
	item: i64

def sum(entries: array[Entry, 3]) -> i64:
	total: mutable i64 = 0
	for {index, item} in entries:
		total <- total * 10 + item * 2 + index
	return total

def main() -> i64:
	xs: array[Entry, 3] = [Entry{index: 1, item: 2}, Entry{index: 3, item: 4}, Entry{index: 5, item: 6}]
	return sum(xs) % 251
""")




def gen_renamed_struct_destructure():
	"""`{field: binder}` destructuring — RENAMED members, in a loop head and in a `let`.

	Both binders are renamed AND the members are listed OUT of declaration order, so a
	backend that binds by POSITION, or that looks the binder name up as a field name,
	gets a different answer rather than declining. The `let` form over a plain struct is
	covered too: only a `layout(soa)` row previously reached that path.

	Field weights differ (1000/10/1) and every element is distinct, so any crossed wire
	moves the result.
	"""
	yield ("renamed_struct_destructure", """
struct Row:
	left: int
	right: int
	flag: bool

def run(items: array[Row, 3]) -> int:
	total: mutable int = 0
	for {right: r, left: l, flag: keep} in items if keep:
		total <- total * 100 + l * 10 + r
	let {flag, right: rr, left: ll} = items[0]
	total <- total + ll * 1000 + rr if flag
	return total

def main() -> i64:
	xs: array[Row, 3] = [Row{left: 1, right: 2, flag: true}, Row{left: 3, right: 4, flag: false}, Row{left: 5, right: 6, flag: true}]
	return run(xs) % 251
""")




def gen_guarded_projection_query():
	"""`EXPR for each x in xs where PATTERN: GUARD` — a projection query with BOTH a
	pattern filter and a guard predicate.

	The projection form has no separate guard slot (the body slot holds the projection),
	so the guard used to be dropped — which collects the EXCLUDED elements rather than
	declining. Both spellings are covered: the bare pattern (`where Expr.Int(value):`)
	and the explicit subject (`where item is Expr.Int(value):`).

	The elements straddle the guard (1 and 2 fail `> 2`, 4 and 3 pass) and a `Missing`
	fails the pattern, so dropping the guard, dropping the pattern, or reordering the
	survivors all change the fold.
	"""
	yield ("guarded_projection_query", """
enum Expr:
	Int(value: i64)
	Missing

def bare(owner: Arena, items: darray[Expr]) -> i64:
	alloc: mutable Arena& = (&owner).cast[mutable Arena&]
	in alloc:
		picked: darray[i64] = value for each item in items where Expr.Int(value): value > 2
		total: mutable i64 = 0
		for p in picked:
			total <- total * 10 + p
		return total

def subject(owner: Arena, items: darray[Expr]) -> i64:
	alloc: mutable Arena& = (&owner).cast[mutable Arena&]
	in alloc:
		picked: darray[i64] = value for each item in items where item is Expr.Int(value): value > 2
		total: mutable i64 = 0
		for p in picked:
			total <- total * 10 + p
		return total

def main() -> i64:
	region r:
		xs: mutable darray[Expr] = []
		xs.push((Expr.Int(1)))
		xs.push((Expr.Int(4)))
		xs.push((Expr.Missing))
		xs.push((Expr.Int(3)))
		xs.push((Expr.Int(2)))
		return (bare(r, xs) * 7 + subject(r, xs)) % 251
""")




def gen_multi_binder_enumerate_query():
	"""`any|all|count|first|each index, item in xs.enumerate() where PAT: GUARD` — a
	MULTI-BINDER query. The Comprehension node carries only the first binder, so the
	element binder and the `.enumerate()` receiver both have to be recovered.

	All five query heads appear, each folded into one exit code with a different weight,
	and the guard compares the payload AGAINST the index — so an index bound to the wrong
	value, an unbound index, or a dropped guard changes the answer rather than declining.
	Elements straddle every boundary: 5 passes, 0 fails the guard, `Missing` fails the
	pattern, 9 passes.
	"""
	yield ("multi_binder_enumerate_query", """
enum Expr:
	Int(value: i64)
	Missing

def any_after(items: darray[Expr]) -> bool:
	return any index, item in items.enumerate() where item is Expr.Int(value): value > index

def all_after(items: darray[Expr]) -> bool:
	return all index, item in items.enumerate() where item is Expr.Int(value): value > index

def count_after(items: darray[Expr]) -> usize:
	return count index, item in items.enumerate() where item is Expr.Int(value): value > index

def first_after(items: darray[Expr]) -> i64?:
	return value for first index, item in items.enumerate() where item is Expr.Int(value): value > index

def each_after(owner: Arena, items: darray[Expr]) -> i64:
	alloc: mutable Arena& = (&owner).cast[mutable Arena&]
	in alloc:
		picked: darray[i64] = value for each index, item in items.enumerate() where item is Expr.Int(value): value > index
		total: mutable i64 = 0
		for p in picked:
			total <- total * 10 + p
		return total

def main() -> i64:
	region r:
		xs: mutable darray[Expr] = []
		xs.push((Expr.Int(5)))
		xs.push((Expr.Int(0)))
		xs.push((Expr.Missing))
		xs.push((Expr.Int(9)))
		acc: mutable i64 = 0
		acc <- acc * 2 + 1 if any_after(xs)
		acc <- acc * 2 + 1 if all_after(xs)
		acc <- acc * 10 + count_after(xs).i64()
		got: i64? = first_after(xs)
		acc <- acc * 10 + (get got else 7)
		acc <- acc * 100 + each_after(r, xs)
		return acc % 251
""")




def gen_expect_statement():
	"""`expect VALUE as PATTERN` with no block — the statement form.

	It lowers to a `Block("expect", …)` the backend never handled, so every `expect`
	declined, down to `expect x as 1`. Both edges matter: a SATISFIED expect must fall
	through and return normally, and a VIOLATED one must panic — so the program runs the
	satisfied case twice and folds the result, and the sibling below trips it.
	"""
	yield ("expect_statement_satisfied", """
def gate(x: int) -> int:
	can Abort.Panic:
		expect x as 1
	return 5

def main() -> i64:
	total: mutable int = 0
	total <- total + gate(1)
	total <- total + gate(1)
	return total.i64()
""")
	yield ("expect_statement_violated", """
def gate(x: int) -> int:
	can Abort.Panic:
		expect x as 1
	return 5

def main() -> i64:
	return gate(2).i64()
""")




def gen_expect_list_rest_shape():
	"""`expect b as {stmts: [1, 2, ...], tag: 7}` — a LIST sub-pattern with a rest tail
	inside a struct shape.

	The rest is the point: element 2 is left unconstrained, so a build that checks it (or
	that mis-indexes the elements) aborts where stage0 returns. The first run satisfies the
	shape with a third element that would fail any check; the fixture folds two calls so a
	test short-circuiting on the first element still shows.
	"""
	yield ("expect_list_rest_shape", """
struct Block:
	stmts: i64[3]
	tag: i64

def gate(b: Block) -> i64:
	can Abort.Panic:
		expect b as {stmts: [1, 2, ...], tag: 7}
	return 4

def main() -> i64:
	total: mutable i64 = 0
	total <- total * 13 + gate(Block{stmts: [1, 2, 3], tag: 7})
	total <- total * 13 + gate(Block{stmts: [1, 2, 99], tag: 7})
	return total % 251
""")


GENERATORS = [
    gen_soa_row_view_binding,
    gen_soa_row_destructured_loop,
    gen_soa_row_let_destructure,
    gen_packed_in_store_is_test,
    gen_packed_is_payload_handle,
    gen_packed_guarded_store_stays_active,
    gen_enumerate_over_fixed_array,
    gen_destructured_struct_loop_head,
    gen_renamed_struct_destructure,
    gen_guarded_projection_query,
    gen_multi_binder_enumerate_query,
    gen_expect_statement,
    gen_expect_list_rest_shape,
]
