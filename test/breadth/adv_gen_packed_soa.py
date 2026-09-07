#!/usr/bin/env python3
"""Adversarial differential generators — packed common fields (both row layouts), labelled single payloads, recursive
packed evaluation, typestate qualifiers, and the SoA layout: columns, row handles,
row iteration and its wrappers

Each generator yields (name, source) pairs; adversarial_differential.py runs them.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))




def gen_packed_common_field_read():
    """`node.span` -- reading a packed enum's COMMON field.

    There was no packed common-field read path at all. The common is read INLINE at word
    `1 + commonIndex` (word 0 is the tag), which is exactly where stage1's own constructor
    WRITES it. stage0 instead keeps commons in a SIDE TABLE and builds the store with
    `..._variant_sparse_with_side_words` -- a different layout, but not an observable one,
    since stores never cross compilers. A first attempt read with stage0's convention against
    stage1's writer and the compiled program segfaulted on an uninitialised side table.

    The common is read TWICE and weighted (7*10 + 7 = 77) so a zero or garbage read cannot
    coincide with the right answer.
    """
    yield ("packed_common_field_read", """
packed enum Expr:
	common:
		span: i64
	Lit(value: i64)

def fold_common() -> i64:
	region scratch(256)
	store: Expr.Store[Local] = Expr.Store(scratch)
	in store:
		node: Expr = new Expr.Lit(span: 7, value: 5)
		out: i64 = node.span * 10 + node.span
		destroy scratch
		return out

def main() -> i64:
	return fold_common()
""")




def gen_packed_common_field_read_aos():
    """`leaf.span` on an AoS-profile packed enum -- one a RECURSIVE payload forces.

    A recursive payload (`Add(left: Expr, right: Expr)`) switches the enum to packed mode 2,
    where there IS no word reader: `packed_read_word` is bound to `ctx_aos_store_record`,
    which takes (state, handle) and returns the ROW POINTER. The variant-sparse read called
    it with the word reader's three arguments and used the result as the value, producing a
    `ptr` where an i64 was wanted. A BARE `return leaf.span` then declined on the return
    path's type-identity check, while `leaf.span + 0` silently accepted the POINTER as an
    arithmetic operand -- a wrong answer with no diagnostic. The common is read out of the
    row instead, at field `1 + commonIndex`.

    The span is returned on its own, so a pointer-shaped read cannot pass as the value.
    """
    yield ("packed_common_field_read_aos", """
packed enum Expr:
	common:
		span: i64
	Int(value: i64)
	Add(left: Expr, right: Expr)

def main() -> i64:
	region scratch(4096)
	store: Expr.Store[Local] = Expr.Store(scratch)
	out: mutable i64 = 0
	in store:
		leaf: Expr = new Expr.Int(span: 7, value: 3)
		out <- leaf.span
	destroy scratch
	return out
""")




def gen_packed_labelled_single_payload_match():
    """`Expr.Int(value: value)` -- a LABELLED single payload field, plus the AoS payload offset.

    Two defects met here, and each hid behind the other:

    * A single payload field written LABELLED arrives as Pattern.Field, which only the
      MULTI-field loop resolved. The binder was never declared, so the arm body declined on
      an unknown name -- and since `main` was the declining function, the driver exited 2
      with no `!elisa.declined` record at all.
    * Under the AoS profile (which a RECURSIVE payload forces) the payload was GEPed at row
      field 1. The row is `{i32 tag, <commons x i64>, [N x i64] payload}`, so with a common
      declared, field 1 IS the common: `value` read back the SPAN. That is a silent wrong
      answer -- 77 where stage0 says 37 -- and it only became visible once the labelled bind
      above stopped declining.

    Both variants are covered: `Add` forces AoS, `Neg` keeps the default variant-sparse
    profile. The payload is weighted against the common (`value * 10 + span`) so reading
    either slot in place of the other cannot produce the right answer.
    """
    for tag, second, ctor in (("aos", "Add(left: Expr, right: Expr)", "Expr.Add(left: left, right: right)"),
                              ("sparse", "Neg(inner: i64)", "Expr.Neg(inner: inner)")):
        yield (f"packed_labelled_single_payload_match_{tag}", """
packed enum Expr:
	common:
		span: i64
	Int(value: i64)
	%s

def demo() -> i64:
	region scratch(4096)
	store: Expr.Store[Local] = Expr.Store(scratch)
	out: mutable i64 = 0
	in store:
		leaf: Expr = new Expr.Int(span: 7, value: 3)
		match leaf:
			Expr.Int(value: value):
				out <- value * 10 + leaf.span
			%s:
				out <- 99
	destroy scratch
	return out

def main() -> i64:
	return demo()
""" % (second, ctor))




def gen_packed_recursive_eval():
    """stage0's own `packed_enum_common.elisa` shape: a recursive packed AST, walked.

    `Expr.Add(left: left, right: right)` is a LABELLED MULTI-field arm whose fields are
    themselves packed handles, under the AoS profile the recursion forces. Two gaps met:
    the AoS binder loop resolved only Pattern.Binding, so a labelled arm bound NOTHING; and
    a payload field that is itself a node is an i32 handle in an i64 row word, which
    emit_conversion declines outright rather than narrowing.

    The tree is built with distinct spans and values (1/3, 2/4, root 3) so the answer 13
    encodes that every common AND every payload word was read from its own slot -- swapping
    any two of them changes it.
    """
    yield ("packed_recursive_eval", """
packed enum Expr:
	common:
		span: i64
	Int(value: i64)
	Add(left: Expr, right: Expr)

def eval(node: Expr, store: Expr.Store[Local]) -> i64:
	in store:
		match node:
			Expr.Int(value: value):
				return value + node.span
			Expr.Add(left: left, right: right):
				return node.span + eval(left, store) + eval(right, store)

def demo() -> i64:
	region scratch(4096)
	store: Expr.Store[Local] = Expr.Store(scratch)
	root: mutable Expr = zeroed
	in store:
		left: Expr = new Expr.Int(span: 1, value: 3)
		right: Expr = new Expr.Int(span: 2, value: 4)
		root <- new Expr.Add(span: 3, left: left, right: right)
	out: i64 = eval(root, store)
	destroy scratch
	return out

def main() -> i64:
	return demo()
""")




def gen_typestate_struct_qualifier():
    """`struct Holder[?]` with a `Holder[&]` parameter -- a TYPESTATE-qualified struct type.

    States are a type-level refinement with no representation: stage0 passes the struct BY
    VALUE and GEPs the field, identical to the unqualified spelling
    (`define i32 @read(%Holder %0)`). stage1 had no case for a bracket on a plain
    non-generic struct, so the annotation stayed Unmodeled and every function taking one
    declined.

    NOTE: stage0 also CHECKS states at the call site (`argument 1 to "read" expects
    Holder[&], got Holder[?]`). stage1 has no such check, so a state MISMATCH is accepted
    where stage0 rejects it -- see the typestate-check note in memory. This fixture uses the
    shape stage0 accepts, so it pins the lowering without depending on the missing check.
    """
    yield ("typestate_struct_qualifier", """
struct Holder[?]:
	value: i32

def make() -> Holder[&]:
	return Holder{value: 41}

def read(value: Holder[&]) -> i32:
	return value.value

def main() -> i64:
	return read(make()).i64() + 1
""")




def gen_darray_literal_spread():
    """`[first, ...rest, 9]` -- a SPREAD element inside a darray literal.

    The `...` arrives as a unary Ellipsis; the literal's element loop pushed it as if it
    were a single value, so the whole literal declined. Lowered as a copy loop that reuses
    emit_darray_push per item, so growth and element conversion are the ordinary path.

    The result is folded positionally (`total * 10 + x`), so a spread that dropped an item,
    duplicated one, or emitted them out of order changes the answer.
    """
    yield ("darray_literal_spread", """
def build(owner: Arena, first: i64, rest: darray[i64]) -> i64:
	alloc: mutable Arena& = (&owner).cast[mutable Arena&]
	xs: darray[i64] @alloc = [first, ...rest, 9]
	total: mutable i64 = 0
	for x in xs:
		total <- total * 10 + x
	return total

def main() -> i64:
	region scratch(4096)
	src: mutable darray[i64] = []
	src.push(2)
	src.push(3)
	out: i64 = build(scratch, 1, src)
	destroy scratch
	return out
""")




def gen_enum_variant_alias_after_is():
    """`if node is Expr.Pair as pair:` -- the variant-test ALIAS binder.

    The parser modelled `is TARGET as NAME` by REPLACING the is-RHS with the alias ident,
    which is right for a refinement target but DROPPED the variant outright: the condition
    became `if let pair = node`, with no test at all. Only a Field-shaped target now keeps
    its target as the RHS and records the alias under its own marker; the refinement-alias
    form (an Ident target) is untouched.

    Both variants are exercised and weighted (`Pair` -> 34, `Int` -> 7, combined 3407), so a
    condition that dropped the test — taking the Pair arm for an Int — cannot pass.
    """
    yield ("enum_variant_alias_after_is", """
enum Expr:
	Pair(left: i64, right: i64)
	Int(value: i64)

def score(node: Expr) -> i64:
	if node is Expr.Pair as pair:
		return pair.left * 10 + pair.right
	return 7

def main() -> i64:
	return score(Expr.Pair(3, 4)) * 100 + score(Expr.Int(9))
""")




def gen_projection_query_explicit_owner():
    """`entry.name for each entry in entries with alloc` -- an EXPLICIT allocation owner.

    The projection parser had no case for the trailing `with OWNER`, so the iterable stopped
    at `entries` and the clause was left for the STATEMENT parser, which turned the whole
    `return` into a recovery `pass`. The function then had no return at all and the semantic
    layer rejected it with "'names' must return a value" -- a parse gap that surfaced as a
    type error two layers away.

    Two separate results are produced and read back AFTER both calls, so a result whose
    storage was freed and reused by the second call cannot give the right answer.
    """
    yield ("projection_query_explicit_owner", """
struct Entry:
	name: i64

def names(owner: Arena, entries: darray[Entry]) -> darray[i64]:
	alloc: mutable Arena& = (&owner).cast[mutable Arena&]
	return entry.name for each entry in entries with alloc

def main() -> i64:
	region scratch(8192)
	a: mutable darray[Entry] = []
	a.push(Entry{name: 1})
	a.push(Entry{name: 2})
	b: mutable darray[Entry] = []
	b.push(Entry{name: 7})
	b.push(Entry{name: 8})
	first: darray[i64] = names(scratch, a)
	second: darray[i64] = names(scratch, b)
	out: mutable i64 = 0
	for n in first:
		out <- out * 10 + n
	for n in second:
		out <- out * 10 + n
	destroy scratch
	return out
""")




def gen_soa_layout_columns():
    """`struct Rows layout(soa)` -- the COLUMN representation.

    stage0 lowers a column-major struct to a plain struct whose every field is a darray of
    the declared type (`%SymbolRows = type { %DynArray__usize, %DynArray__u32 }`), so the
    whole column API is the ordinary darray machinery once the fields register that way.

    THREE layers, and all three are load-bearing: the backend wraps each member type in both
    registration paths (the Decl-shaped one AND the metadata-driven flat one the self-hosted
    backend actually takes -- patching only the first left the ValueTypes saying darray while
    the LLVM body stayed {i64, i64}), and the semantic field table types a column as a mutable
    darray or every `.push` trips the immutable-receiver wall.

    Two columns are grown to DIFFERENT lengths and both are read back, so a layout that
    aliased them or mixed up a count cannot give the right answer.
    """
    yield ("soa_layout_columns", """
struct Rows layout(soa):
	key: i64
	depth: i64

def build(owner: Arena) -> i64:
	alloc: mutable Arena& = (&owner).cast[mutable Arena&]
	in alloc:
		pending: mutable Rows = zeroed
		pending.key.reserve(4)
		pending.key.push(1)
		pending.key.push(2)
		pending.depth.push(7)
		total: mutable i64 = 0
		for k in pending.key:
			total <- total * 10 + k
		total <- total * 10 + pending.depth[0]
		return total * 10 + pending.key.count + pending.depth.count

def main() -> i64:
	region scratch(4096)
	out: i64 = build(scratch)
	destroy scratch
	return out
""")




def gen_soa_row_api():
    """`rows.reserve(n)` / `rows.push(a, b)` / `rows.count` -- the ROW-level SoA API.

    Row operations fan out over the columns: push takes one argument per column in
    declaration order, reserve applies one count to every column, and `count` is the row
    count (column 0's, since every column has the same length -- stage0 reads it exactly
    that way).

    Two rows are pushed with DIFFERENT values per column and row 1 is read back from both
    columns, so a fan-out that crossed the columns or dropped a row cannot give 782.
    """
    yield ("soa_row_api", """
struct Rows layout(soa):
	key: i64
	depth: i64

def build(owner: Arena) -> i64:
	alloc: mutable Arena& = (&owner).cast[mutable Arena&]
	in alloc:
		pending: mutable Rows = zeroed
		pending.reserve(4)
		pending.push(5, 6)
		pending.push(7, 8)
		return pending.key[1] * 100 + pending.depth[1] * 10 + pending.count

def main() -> i64:
	region scratch(4096)
	out: i64 = build(scratch)
	destroy scratch
	return out
""")




def gen_soa_row_handles():
    """`RowId[S]`, `s.valid(row)`, `s[row].field` read and write — the SoA ROW HANDLE API.

    A RowId is an i32: stage0 narrows the column count to i32 on push (`%row = alloca i32`).
    `valid` is a plain `row < rowCount`, and `s[row].field` resolves through the ONE lvalue
    chain resolver, so the read and the write share an address computation.

    Two rows are pushed, the SECOND is mutated, and BOTH are read back alongside the row
    count and an out-of-range `valid` probe — so a row index off by one, a crossed column, or
    a write that missed cannot produce the same answer.
    """
    yield ("soa_row_handles", """
struct SymbolRows layout(soa):
	name_id: i64
	flags: i64

def build(owner: Arena) -> i64:
	alloc: mutable Arena& = (&owner).cast[mutable Arena&]
	in alloc:
		symbols: mutable SymbolRows = zeroed
		symbols.reserve(4)
		first: RowId[SymbolRows] = symbols.push(12, 3)
		row: RowId[SymbolRows] = symbols.push(20, 4)
		if not symbols.valid(row):
			return 0
		if symbols.valid(9):
			return 1
		symbols[row].flags <- 5
		return symbols[first].name_id * 10000 + symbols[row].name_id * 100 + symbols[row].flags * 10 + symbols.count

def main() -> i64:
	region scratch(4096)
	out: i64 = build(scratch)
	destroy scratch
	return out % 251
""")




def gen_soa_row_iteration():
    """`for row in s.rows():` -- ROW ITERATION over a column-major aggregate.

    The binder is a row VIEW. Rather than materialise stage0's `{ptr, i64}` pair, the
    aggregate's address and the loop index are recorded as a binder and `row.field` resolves
    straight to the element address -- the same GEP the explicit `s[i].field` form produces.
    `rows` is accepted both called and bare; stage0's own corpus writes it both ways.

    The fold is positional and mixes both columns (`total * 100 + key * 10 + depth`), so a
    loop that visited the rows out of order, ran off the end, or crossed the columns changes
    the answer.
    """
    yield ("soa_row_iteration", """
struct Rows layout(soa):
	key: i64
	depth: i64

def build(owner: Arena) -> i64:
	alloc: mutable Arena& = (&owner).cast[mutable Arena&]
	in alloc:
		pending: mutable Rows = zeroed
		pending.push(5, 6)
		pending.push(7, 8)
		total: mutable i64 = 0
		for row in pending.rows():
			total <- total * 100 + row.key * 10 + row.depth
		return total

def main() -> i64:
	region scratch(4096)
	out: i64 = build(scratch)
	destroy scratch
	return out % 251
""")




def gen_soa_row_iteration_wrappers():
    """`s.rows().enumerate()` and `rev(s.rows())` -- the two wrapped row walks.

    enumerate binds the running index FIRST and the row second; rev starts at count-1 and
    counts down while the index is still >= 0. Both peel back to the same row walk, so the
    binder machinery is shared with the plain form.

    All three walks fold into ONE positional accumulator, and the reversed pass reads the
    column the forward passes do not, so a wrapper that ran the wrong direction, dropped the
    first or last row, or mismatched the index against the row cannot give 61.
    """
    yield ("soa_row_iteration_wrappers", """
struct Rows layout(soa):
	key: i64
	depth: i64

def build(owner: Arena) -> i64:
	alloc: mutable Arena& = (&owner).cast[mutable Arena&]
	in alloc:
		pending: mutable Rows = zeroed
		pending.push(5, 6)
		pending.push(7, 8)
		total: mutable i64 = 0
		for row in pending.rows():
			total <- total * 100 + row.key * 10 + row.depth
		for index, row in pending.rows().enumerate():
			total <- total * 100 + index * 10 + row.key
		for row in rev(pending.rows()):
			total <- total * 100 + row.depth
		return total

def main() -> i64:
	region scratch(4096)
	out: i64 = build(scratch)
	destroy scratch
	return out % 251
""")


GENERATORS = [
    gen_packed_common_field_read,
    gen_packed_common_field_read_aos,
    gen_packed_labelled_single_payload_match,
    gen_packed_recursive_eval,
    gen_typestate_struct_qualifier,
    gen_darray_literal_spread,
    gen_enum_variant_alias_after_is,
    gen_projection_query_explicit_owner,
    gen_soa_layout_columns,
    gen_soa_row_api,
    gen_soa_row_handles,
    gen_soa_row_iteration,
    gen_soa_row_iteration_wrappers,
]
