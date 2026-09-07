#!/usr/bin/env python3
"""Adversarial differential generators — sparse packed profiles, multi-field word packing, ordinal store indices,
`new[region]` allocation, nested or-pattern bindings, monomorphized ref
arithmetic, and ref-to-ref indexing

Each generator yields (name, source) pairs; adversarial_differential.py runs them.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))




def gen_packed_is_variant_sparse_profile():
    """`if tok is Tok.Ident(id):` on a NON-RECURSIVE packed enum.

    Only a RECURSIVE packed enum gets the `__aos` annotation, so a plain one selects the
    variant-sparse profile (mode 0) -- and the `is` payload path was gated to mode 2
    outright. The `match` spelling of the identical test compiled all along; the `is`
    spelling declined, which is the same lag between those two paths this backend has hit
    before.

    Extended to the variant-sparse and index profiles by reading the tag and the payload
    WORD through the runtime helpers, the way the statement-match path already did.

    Note the two helpers disagree on argument order --
    `..._read_variant_sparse_tag(state, index)` but `..._read_variant_sparse_word(index,
    state, word)` -- and passing the word reader's order to the tag reader SEGFAULTED
    (exit 139) while still compiling cleanly. The commons are exercised too, since word 0
    is the tag and words 1..commons precede the payload, so an off-by-commons here reads a
    common as the binder.
    """
    yield ("packed_is_variant_sparse_profile", """
packed enum Tok:
	common:
		span: i32
		kind: i32
	Ident(id: i32)
	Num(n: i32)

def go(owner: Arena) -> i32:
	total: mutable i32 = 0
	store: Tok.Store[Local] = Tok.Store(owner)
	in store:
		a: Tok = new Tok.Ident(span: 5, kind: 1, id: 2)
		b: Tok = new Tok.Num(span: 3, kind: 2, n: 7)
		total <- total + a.span * 1 + a.kind * 2
		total <- total + b.span * 4 + b.kind * 8
		if a is Tok.Ident(aid):
			total <- total + aid * 16
		if b is Tok.Ident(nope):
			total <- total + nope * 1000
	return total

def main() -> i64:
	owner: Arena = zeroed
	return go(owner).i64()
""")




def gen_packed_multi_field_word_packing():
    """A MULTI-FIELD packed payload read under the variant-sparse profile.

    The payload is stored as ONE AGGREGATE at word `1 + commons` --
    `%__packed_payload_N = type { i32, i32 }`, i.e. BOTH fields inside a single 64-bit
    word. The mode-0 match read field `i` from word `1 + commons + i`, which got field 0
    right (it aliases the aggregate's low half) and read field 1 out of a word nothing
    ever wrote.

    For a payload of node HANDLES that was a silent wrong answer rather than a crash: the
    second handle came back 0, which is a valid node index (the first one allocated), so
    `right.span` quietly returned the wrong node's span -- stage0 13, stage1 11.

    Field `i` now reads word `1 + commons + i/2` and shifts down 32 bits on odd positions.
    A payload whose fields are not all 32-bit still declines: there is no size/offset
    helper in this backend, and guessing the layout would be another silent wrong answer.

    Both variants are matched, and the fields are weighted unequally (1 and 4), so reading
    one field twice -- the exact old behaviour for the low half -- moves the total.
    """
    yield ("packed_multi_field_word_packing", """
packed enum Tok:
	common:
		span: i32
	Pair(a: i32, b: i32)
	One(v: i32)

def go(owner: Arena) -> i32:
	total: mutable i32 = 0
	store: Tok.Store[Local] = Tok.Store(owner)
	in store:
		p: Tok = new Tok.Pair(span: 9, a: 3, b: 5)
		q: Tok = new Tok.One(span: 1, v: 7)
		match p:
			Tok.Pair(a: a, b: b):
				total <- total + a * 1 + b * 4
			Tok.One(v: v):
				total <- total + 100
		match q:
			Tok.Pair(a: a2, b: b2):
				total <- total + 200
			Tok.One(v: v2):
				total <- total + v2 * 16
	return total

def main() -> i64:
	owner: Arena = zeroed
	return go(owner).i64()
""")




def gen_packed_store_ordinal_index():
    """`frozen[2]` — indexing a FROZEN packed store by allocation ORDINAL.

    stage0 lowers it to `ctx_packed_store_index_at(state, i64 ordinal)`, mapping an
    ordinal to the node HANDLE at that position. The helper reads `state.indices` off a
    PackedStoreState, so it serves the variant-sparse and index profiles; the AoS store is
    a different struct with no such helper, and that profile declines.

    Worth recording how this was found, because two attempts failed on it: the emitter and
    the `expression_type` case were both CORRECT from the first try, but were inserted late
    in `emit_expression_index_fields`, after four other branches that also match
    `Expr.Index` — one of which claims a PackedStore receiver and returns null. A decline
    marker placed at the same point was silent, which was misread as "the emitter is never
    reached" rather than "not reached HERE". Placing the branch first made it work
    unchanged.

    Two nodes are read back with different spans and weighted 10 and 1, so an off-by-one in
    the ordinal, or both reads resolving to the same node, moves the answer.
    """
    yield ("packed_store_ordinal_index", """
packed enum Expr:
	common:
		span: i32
	Lit(value: i32)
	Sym(id: i32)

def inspect(owner: Arena) -> i32:
	store: Expr.Store[Local] = Expr.Store(owner)
	in store:
		a: Expr = new Expr.Lit(span: 4, value: 3)
		b: Expr = new Expr.Sym(span: 7, id: 5)
		_ = a
		_ = b
	frozen: Expr.Store[Frozen] = freeze(move store)
	in frozen:
		n0: Expr = frozen[0]
		n1: Expr = frozen[1]
		return n0.span * 10 + n1.span
	return 0

def main() -> i64:
	owner: Arena = zeroed
	return inspect(owner).i64()
""")




def gen_region_new_allocation():
    """`new[region] EXPR` — region allocation, both the scalar and the constructor form.

    This construct was ERASED by the parser until 2026-08-13: `new[r] …` returned its bare
    operand, so `v: i32& = new[scratch] x` degraded into an int-to-pointer cast of the
    VALUE and faulted on the first dereference (SIGSEGV for the scalar form, SIGBUS for the
    constructor form). Nothing caught it — the strict backend census counts a file covered
    when stage1 declines no function, and these files decline nothing while emitting a
    crashing binary.

    Two traps this fixture pins deliberately:

    - `new` binds LOOSER than the arithmetic operators. stage0 allocates the whole of
      `new[scratch] seed + 1` (its IR adds first, then allocates and stores the sum).
      Parsing only the postfix operand builds `RegionNew(seed) + 1` — pointer arithmetic —
      which does not crash but silently returns the WRONG value. `scalar` is written as
      `seed + 1` precisely so that mistake changes the answer instead of hiding.
    - The value is read back AFTER `destroy`-free use and weighted, so an allocation that
      returns a stale or aliased pointer moves the result rather than happening to agree.
    """
    yield ("region_new_allocation", """
struct Pt:
	x: i32
	y: i32

def scalar_form(seed: i32) -> i32:
	region scratch(1024)
	value: i32& = new[scratch] seed + 1
	out: i32 = value[0]
	destroy scratch
	return out

def ctor_form(seed: i32) -> i32:
	region scratch(1024)
	point: Pt& = new[scratch] Pt{x: seed + 1, y: seed + 2}
	out: i32 = point.x * 10 + point.y
	destroy scratch
	return out

def main() -> i64:
	return (scalar_form(7) + ctor_form(3) * 3).i64()
""")





def gen_nested_or_pattern_binding():
    """`Outer.Leaf(Inner.A(v) | Inner.B(v))` — a nested or-pattern that BINDS a payload.

    Both compilers were wrong here, in different ways, until 2026-08-13:

    - stage0 MISCOMPILED it. The payload spill was emitted inside the FIRST option's
      basic block, which does not dominate the later options' blocks, so every option
      after the first loaded an uninitialised slot and bound a CONSTANT. Keyword(40),
      (55) and (99) all returned 1.
    - stage1 DECLINED it, and the decline was deliberate: the lowering had been written,
      verified, then reverted, because emitting the correct answer read as a differential
      MISMATCH against the wrong oracle.

    So this shape needs a probe that varies the payload across BOTH options. A single
    value, or a value that happens to equal the variant ordinal, is exactly what let the
    constant-binding bug look like a clean match for as long as it did.

    `second` deliberately exercises the option that was broken (the non-first one) and
    `first` guards against a fix that breaks the option that already worked.
    """
    yield ("nested_or_pattern_binding", """
enum Token:
	Ident(value: i64)
	Keyword(value: i64)
	Other

enum Expr:
	Leaf(kind: Token)
	Missing

def unwrap(t: Token) -> i64:
	expr: Expr = Expr.Leaf(t)
	match expr:
		Expr.Leaf(Token.Ident(value) | Token.Keyword(value)):
			return value
		_:
			return 999

def main() -> i64:
	second: i64 = unwrap(Token.Keyword(40))
	first: i64 = unwrap(Token.Ident(7))
	other: i64 = unwrap(Token.Other)
	return (second * 3 + first * 5 + other) % 251
""")





def gen_monomorphized_ref_arithmetic():
    """`+` on a scalar ref: the INSTANTIATED type must govern, generic or concrete.

    `p + n` where p is a scalar reference is VALUE arithmetic (deref the referent, add) —
    only `u8&`/`void&` is genuine byte-pointer stepping. That rule is type-directed, so it
    cannot be decided while T is still a type parameter, and until 2026-08-13 BOTH
    compilers got the generic form wrong in DIFFERENT ways:

    - stage0 typed generic `T& + n` as POINTER arithmetic and kept that meaning after
      instantiation, so `T&` with T := usize stepped the address while the identical code
      spelled `usize&` added the value. Fixed by re-analyzing each instantiation with the
      type parameters bound (semantic.SpecializedExprTypes).
    - stage1 computed the sum correctly but left the expression typed `T&`, so a following
      `.usize()` treated the SUM as an ADDRESS — inttoptr then load — and faulted. Fixed by
      applying the referent rule at the type level too (expression_type).

    All three arms matter and none is redundant: `generic` and `concrete` must agree with
    each other (that agreement IS monomorphization), and `stepping` guards the `u8&`
    exception, which a fix that simply deref'd every ref would silently destroy.
    """
    yield ("monomorphized_ref_arithmetic", """
def add_generic[T](p: mutable T&, n: usize) -> usize can[Unsafe.PointerArithmetic]:
	trusted [Unsafe.PointerArithmetic]:
		return (p + n).usize()

def add_concrete(p: mutable usize&, n: usize) -> usize can[Unsafe.PointerArithmetic]:
	trusted [Unsafe.PointerArithmetic]:
		return (p + n).usize()

def step_bytes[T](p: mutable T&, n: usize) -> mutable void& can[Unsafe.PointerCast, Unsafe.PointerArithmetic]:
	trusted [Unsafe.PointerCast, Unsafe.PointerArithmetic]:
		return (p + n).cast[mutable void&]

def main() -> i64:
	can[Unsafe.PointerCast, Unsafe.PointerArithmetic]:
		x: mutable usize = 40
		y: mutable usize = 40
		generic: usize = add_generic(&x, 5)
		concrete: usize = add_concrete(&y, 5)
		bytes: mutable u8[4] = [7, 9, 11, 13]
		stepped: mutable u8& = step_bytes(&bytes[0], 2).cast[mutable u8&]
		return (generic.i64() * 7 + concrete.i64() * 3 + stepped[0].i64()) % 251
""")





def gen_ref_to_ref_indexing():
    """`p[i]` where `p: T&&` — a C `char**`, the shape `argv` actually has.

    stage1 DECLINED every ref-to-ref index until 2026-08-13, which is why its driver could
    not read argv at all and fell back to a stdin wire protocol. stage0 lowers it as
    `getelementptr ptr, ptr %base, i64 %i` then `load ptr` — the same GEP+load stage1's
    scalar-ref path already emitted, but gated to Signed/Unsigned/Float.

    TWO places had to agree: the emitter (codegen_expr_index_fields) AND expression_type
    (codegen_scope). Fixing only the emitter changes nothing — the type function returns
    Unmodeled and the branch is never reached.

    Indices 0 and 2 are read and weighted differently so an off-by-one in the GEP, or both
    reads collapsing to the same slot, moves the answer.
    """
    yield ("ref_to_ref_indexing", """
extern strlen(s: cstr) -> usize

def widths(slots: mutable cstr&&, count: i64) -> i64 can[Unsafe.PointerCast]:
	trusted [Unsafe.PointerCast]:
		total: mutable i64 = 0
		for i in 0..<count |total, slots|:
			total <- total * 10 + strlen(slots[i].cast[cstr]).i64()
		return total

def main() -> i64 can[Unsafe.PointerCast, Memory.Allocate]:
	trusted [Unsafe.PointerCast]:
		table: mutable darray[cstr] = ["abc", "de", "fghi"]
		base: mutable cstr&& = (&table[0]).cast[mutable cstr&&]
		return widths(base, 3) % 251
""")


GENERATORS = [
    gen_packed_is_variant_sparse_profile,
    gen_packed_multi_field_word_packing,
    gen_packed_store_ordinal_index,
    gen_region_new_allocation,
    gen_nested_or_pattern_binding,
    gen_monomorphized_ref_arithmetic,
    gen_ref_to_ref_indexing,
]
