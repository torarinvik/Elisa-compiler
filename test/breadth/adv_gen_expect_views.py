#!/usr/bin/env python3
"""Adversarial differential generators — `expect` over struct and variant shapes, struct payloads beside a scalar, array
payload fields, static protocol dispatch, return-type generic inference, and the
view-over-borrowed-darray family

Each generator yields (name, source) pairs; adversarial_differential.py runs them.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))




def gen_expect_struct_shape():
	"""`expect b as {tag: 1, size: 9}` — an ANONYMOUS brace shape with LITERAL field tests.

	The pattern names no type; the scrutinee's own struct supplies it. Both spellings that
	stage0 REJECTS as a match arm (`{tag: 1}` and `Block{tag: 1}`) must keep declining, so
	this only exercises the `expect` position — the naming and the literal rebuild are
	deliberately confined there.

	Runs the satisfied case twice and folds it, so a test that silently passes everything
	is indistinguishable from one that works only by luck of the first element.
	"""
	yield ("expect_struct_shape", """
struct Block:
	tag: i64
	size: i64

def gate(b: Block) -> i64:
	can Abort.Panic:
		expect b as {tag: 1, size: 9}
	return 4

def main() -> i64:
	total: mutable i64 = 0
	total <- total * 13 + gate(Block{tag: 1, size: 9})
	total <- total * 13 + gate(Block{tag: 1, size: 9})
	return total % 251
""")




def gen_struct_payload_beside_scalar():
	"""A payload-enum variant carrying a STRUCT alongside another field.

	Only a SOLE aggregate payload was accepted before, so `While(condition: i64, body: Block)`
	declined the whole enum — every construction and every `is` binding over it went with it.
	The blob extent is now the SUM of the fields' words, sized after struct bodies are known;
	the field COUNT is right only while every field is one word wide.

	Every variant contributes a differently-weighted digit and the struct's two fields are
	read separately, so a mis-sized blob or a crossed payload offset changes the answer.
	"""
	yield ("struct_payload_beside_scalar", """
struct Block:
	head: i64
	rest: i64

enum Stmt:
	While(condition: i64, body: Block)
	Note(text: i64, extra: i64)
	Done

def read(s: Stmt) -> i64:
	if s is Stmt.While(c, b):
		return c * 100 + b.head * 10 + b.rest
	if s is Stmt.Note(t, xs):
		return t * 10 + xs
	return 1

def main() -> i64:
	total: mutable i64 = 0
	total <- total * 7 + read((Stmt.While(9, Block{head: 3, rest: 4})))
	total <- total * 7 + read((Stmt.Note(5, 7)))
	total <- total * 7 + read((Stmt.Done))
	return total % 251
""")




def gen_array_payload_field():
	"""A payload-enum variant carrying an ARRAY — directly and inside a struct.

	An array had no size or alignment in the payload ABI, so it made every enclosing type
	unsizeable: `finalize_payload_enum_words` blanked the enum and EVERY use of it declined,
	including variants that had nothing to do with the array.

	The blob here must hold 1 + 3 words. Each array element is read at a different weight
	and the sibling variants are exercised too, so an under-sized blob, a wrong element
	stride, or a crossed payload offset all move the answer.
	"""
	yield ("array_payload_field", """
struct Block:
	stmts: i64[3]
	tag: i64

enum Stmt:
	While(condition: i64, body: Block)
	Note(text: i64)
	Done

def read(s: Stmt) -> i64:
	if s is Stmt.While(c, b):
		return c * 1000 + b.stmts[0] * 100 + b.stmts[2] * 10 + b.tag
	if s is Stmt.Note(t):
		return t
	return 1

def main() -> i64:
	total: mutable i64 = 0
	total <- total + read((Stmt.While(7, Block{stmts: [1, 2, 3], tag: 4})))
	total <- total + read((Stmt.Note(5)))
	total <- total + read((Stmt.Done))
	return total % 251
""")




def gen_expect_variant_payload_shape():
	"""`expect s as E.V(_, 5)` and `expect s as E.V(_, {stmts: [1, 2, ...]})` — VARIANT
	shapes with POSITIONAL payload sub-patterns.

	No expression reads payload field N, so the tag test binds every position to a
	synthetic name and the sub-shapes are tested against those. Three distinct ways to
	fail are covered by the sibling fixtures below: a wrong tag, a payload literal that
	does not match, and a nested list element that does not match.
	"""
	yield ("expect_variant_payload_scalar", """
enum Stmt:
	While(condition: i64, limit: i64)
	Done

def gate(s: Stmt) -> i64:
	can Abort.Panic:
		expect s as Stmt.While(_, 5)
	return 4

def main() -> i64:
	total: mutable i64 = 0
	total <- total * 13 + gate((Stmt.While(9, 5)))
	total <- total * 13 + gate((Stmt.While(1, 5)))
	return total % 251
""")
	yield ("expect_variant_payload_nested_list", """
struct Block:
	stmts: i64[3]

enum Stmt:
	While(condition: i64, body: Block)
	Done

def gate(s: Stmt) -> i64:
	can Abort.Panic:
		expect s as Stmt.While(_, {stmts: [1, 2, ...]})
	return 4

def main() -> i64:
	return gate((Stmt.While(9, Block{stmts: [1, 2, 3]})))
""")




def gen_packed_nested_payload_decode():
	"""A NESTED variant sub-pattern in a packed enum's SINGLE-field payload:
	`Expr.Wrap(inner: Expr.Lit(value: value))`.

	The payload IS the child's handle, so the arm has to read the CHILD's tag from the
	store and fall through when it disagrees. The whole point of the old decline was that
	binding without testing is a silent wrong answer, so the fixture folds two nodes: one
	whose child IS a Lit (the nested arm must fire) and one whose child is another Wrap
	(it must NOT, and the recursive arm must take over). Both answer 7, giving 77 — an
	untested nested pattern makes the second call take the wrong arm.
	"""
	yield ("packed_nested_payload_decode", """
packed enum Expr:
	Lit(value: int)
	Wrap(inner: Expr)

def fold_frozen(node: Expr, frozen: Expr.Store[Frozen]) -> int:
	match node in frozen:
		Expr.Wrap(inner: Expr.Lit(value: value)):
			return value
		Expr.Wrap(inner: inner):
			return fold_frozen(inner, frozen)
		Expr.Lit(value: value):
			return value

def main() -> i64:
	region scratch(512)
	store: Expr.Store[Local] = Expr.Store(scratch)
	lit: Expr = new[store] Expr.Lit(value: 7)
	wrapped: Expr = new[store] Expr.Wrap(inner: lit)
	outer: Expr = new[store] Expr.Wrap(inner: wrapped)
	frozen: Expr.Store[Frozen] = freeze(move store)
	total: int = fold_frozen(wrapped, frozen) * 10 + fold_frozen(outer, frozen)
	destroy scratch
	return total.i64()
""")




def gen_static_protocol_dispatch():
	"""`def f[B: Builder]` calling `B.make(...)` and `B.value_of(...)` — STATIC dispatch
	through a bound type parameter, including the associated type `B.Node`.

	An impl body flattens into ordinary top-level functions, so once B is bound the method
	is reachable by its bare name. Both impl methods TRANSFORM their argument (doubling,
	then adding one) rather than passing it through, so dispatching to the wrong function —
	or skipping one of the two calls — changes the answer.
	"""
	yield ("static_protocol_dispatch", """
struct AstNode:
	value: int

struct BuilderTag:
	tag: int

protocol Builder:
	type Node
	def make(value: int) -> Node
	def value_of(node: Node) -> int

impl Builder for BuilderTag:
	type Node = AstNode

	def make(value: int) -> AstNode:
		return AstNode{value: value * 2}

	def value_of(node: AstNode) -> int:
		return node.value + 1

def build_and_read[B: Builder](value: int) -> int:
	node: B.Node = B.make(value)
	return B.value_of(node)

def main() -> i64:
	return build_and_read[BuilderTag](41).i64() % 251
""")




def gen_index_profile_statement_match():
	"""A STATEMENT match over an `@packed_profile(retained_reads)` enum — the INDEX
	profile, whose word reader takes the arena as a leading argument.

	The statement emitter was variant-sparse/AoS only, so every index-profile match
	declined. The two payload fields carry different weights, so a word index off by one
	changes the answer rather than crashing.

	Note this profile puts payload word i at `1 + i` even with commons declared, where the
	other profiles put it at `1 + commons + i` — a common-carrying index enum still
	declines, since reading it the other way segfaults.
	"""
	yield ("index_profile_statement_match", """
@packed_profile(retained_reads)
packed enum Expr:
	Pair(first: int, second: int)
	End

def fold(node: Expr, frozen: Expr.Store[Frozen]) -> int:
	match node in frozen:
		Expr.Pair(first: first, second: second):
			return first * 10 + second
		Expr.End:
			return 0

def main() -> i64:
	region scratch(256)
	store: Expr.Store[Local] = Expr.Store(scratch)
	node: Expr = new[store] Expr.Pair(first: 4, second: 7)
	frozen: Expr.Store[Frozen] = freeze(move store)
	out: int = fold(node, frozen)
	destroy scratch
	return out.i64() % 251
""")




def gen_return_type_generic_inference():
	"""A generic whose type parameter appears ONLY in the RETURN type:
	`def make[T](api: Namespace) -> Box[T]`.

	Nothing about the ARGUMENTS determines T, so argument-driven inference binds nothing
	and the call used to decline. The declaration's annotation is the only source. Both
	spellings are covered — the plain call and the UFCS one, which is the same call with
	the receiver as its leading argument.

	The two results are folded at different weights, so an instantiation picked for one
	spelling and not the other, or a receiver dropped from the argument list, changes the
	answer rather than failing to build.
	"""
	yield ("return_type_generic_inference", """
struct Box[T]:
	bits: mutable u64

struct Namespace:
	_marker: u8

global boxes: Namespace = zeroed

def make[T](api: Namespace) -> Box[T]:
	_ = api
	result: mutable Box[T] = zeroed
	result.bits <- 3
	return result

def widen[T](value: Box[T]&) -> u64:
	return value.bits * 7

const enum Colour of u8:
	Red
	Green

def main() -> i64:
	direct: Box[Colour] = make(boxes)
	method: Box[Colour] = boxes.make()
	return (widen(direct) * 10 + widen(method)).i64() % 251
""")




def gen_shorthand_member_argument():
	"""A leading-dot shorthand in ARGUMENT position — `take(.Imported)`.

	The parser keeps it as a ShorthandMember, which no expression path emitted, so a
	shorthand argument declined even for an ordinary non-generic call while the qualified
	spelling compiled. Covered here through a plain call AND through a UFCS call to a
	generic, which has its own argument loop.

	Each member is used at a different bit weight, so resolving one to the wrong ordinal
	changes the answer rather than failing to build.
	"""
	yield ("shorthand_member_argument", """
struct Flags[T]:
	bits: mutable u64

const enum RoutineFlag of u8:
	Imported
	Exported
	VarArgs

def flags_mask[T](value: T) -> u64:
	index: u64 = value.u64()
	return 1.u64() << index.u32()

def add[T](items: mutable Flags[T]&, value: T):
	items.bits <- items.bits | flags_mask[T](value)

def weigh(value: RoutineFlag) -> u64:
	return value.u64() + 1

def main() -> i64:
	result: mutable Flags[RoutineFlag] = zeroed
	result.add(.Imported)
	result.add(.VarArgs)
	total: u64 = result.bits * 10 + weigh(.Exported)
	return total.i64() % 251
""")




def gen_flags_bit_test_index():
	"""`value[RoutineFlag.Imported]` on a `Flags[T]` — a BIT TEST, not a container read.

	Two halves had to agree: the EMITTER lowers it to `(bits & (1 << ordinal)) != 0`, and
	the TYPE resolver has to answer Bool — without the second, a binding typed as the
	struct and `if value[F.X]:` declined outright, since a condition must resolve to Bool.

	Three members are probed at different fold weights with only two set, so a wrong
	ordinal, a missed bit or an always-true test each change the answer. The raw `bits`
	are folded in too, pinning the SET side against the TEST side.
	"""
	yield ("flags_bit_test_index", """
struct Flags[T]:
	bits: mutable u64

const enum RoutineFlag of u8:
	Imported
	Exported
	VarArgs

def flags_mask[T](value: T) -> u64:
	index: u64 = value.u64()
	return 1.u64() << index.u32()

def add[T](items: mutable Flags[T]&, value: T):
	items.bits <- items.bits | flags_mask[T](value)

def probe(value: Flags[RoutineFlag]&) -> i64:
	total: mutable i64 = 0
	total <- total * 2 + 1 if value[RoutineFlag.Imported]
	total <- total * 2 + 1 if value[RoutineFlag.Exported]
	total <- total * 2 + 1 if value[RoutineFlag.VarArgs]
	return total

def main() -> i64:
	result: mutable Flags[RoutineFlag] = zeroed
	result.add(.Imported)
	result.add(.VarArgs)
	return probe(result) * 10 + result.bits.i64()
""")




def gen_index_returned_darray():
	"""`make_array()[1]` — indexing a darray a call RETURNED.

	A call is an rvalue with no address of its own, so the header-address helper missed it
	and the whole expression declined; and the type helper it is gated on has no FnTable,
	so a call's return type was out of reach there too. stage0 spills the result to a
	temporary and indexes that.

	Two different elements are read at different weights, so a wrong offset — or a temp
	shared between the two calls — changes the answer.
	"""
	yield ("index_returned_darray", """
def make_array(owner: Arena) -> darray[i32]:
	alloc: mutable Arena& = (&owner).cast[mutable Arena&] can Unsafe.PointerCast
	in alloc:
		xs: mutable darray[i32] = [4, 7, 9]
		return xs

def read(owner: Arena) -> i32:
	return make_array(owner)[1] * 10 + make_array(owner)[2]

def main() -> i64:
	region r:
		return read(r).i64() % 251
""")




def gen_view_over_borrowed_darray():
	"""`view[T]` over a BORROWED darray — `xs[0:3]` where `xs: darray[i64]&`.

	A borrowed container types as a Ref, so the slice branch that builds a fat view missed
	it: the same slice over a LOCAL darray compiled while over a parameter it declined,
	which also made a function RETURNING a view unreachable.

	This exercises the whole chain in one program — slice a borrowed darray, return the
	view, then index the RETURNED view twice at different weights, so a wrong base pointer
	or a dropped start offset changes the answer.
	"""
	yield ("view_over_borrowed_darray", """
def whole(xs: darray[i64]&) -> view[i64]:
	return xs[0:3]

def read(xs: darray[i64]&) -> i64:
	return whole(xs)[1] * 10 + whole(xs)[2]

def main() -> i64:
	region r:
		items: mutable darray[i64] = [4, 7, 9]
		return read(items) % 251
""")




def gen_slice_of_temporary():
	"""`make_array()[1:3][0]` — slicing a RETURNED darray and indexing the slice.

	Two things had to give. A slice in a position with no annotation arrives with an
	Unmodeled expected type, so the branch that builds a fat view never fired; and a SLICE
	is an rvalue with no address, so the index emitter's address-based shapes all missed
	it.

	Three reads at different weights, including one whose slice starts at a NON-zero
	offset and one that starts at zero, so a dropped start offset or a wrong element
	stride shows up in the answer.
	"""
	yield ("slice_of_temporary", """
def make_array(owner: Arena) -> darray[i32]:
	alloc: mutable Arena& = (&owner).cast[mutable Arena&] can Unsafe.PointerCast
	in alloc:
		xs: mutable darray[i32] = [4, 7, 9]
		return xs

def read(owner: Arena) -> i32:
	return make_array(owner)[1:3][0] * 100 + make_array(owner)[1:3][1] * 10 + make_array(owner)[0:3][0]

def main() -> i64:
	region r:
		return read(r).i64() % 251
""")




def gen_view_field_element_read():
	"""A `view[T]` held in a struct FIELD, indexed, then a field taken off the element:
	`state.tokens[at].weight`.

	Three separate holes lined up here. The address-based view path only ever resolved a
	LOCAL, so a view field declined. The type resolver had no View case for an index at
	all, so an indexed view had no type — and without that the element's struct could not
	be found to take a field from. And the element is an rvalue, so the field chain
	resolvers had no address to work with.

	Both fields of the element are read at different weights across two indices, so a
	wrong element stride, a crossed field or a lost const-enum conversion all move the
	answer.
	"""
	yield ("view_field_element_read", """
const enum TokenKind of u8:
	Ident
	Eof

struct Token:
	kind: TokenKind
	weight: i64

struct P:
	tokens: mutable view[Token]

def peek(state: P&, at: usize) -> i64:
	return state.tokens[at].weight * 10 + state.tokens[at].kind.i64()

def main() -> i64:
	region r:
		items: mutable darray[Token] = [Token{kind: TokenKind.Eof, weight: 3}, Token{kind: TokenKind.Ident, weight: 5}]
		state: P = P{tokens: items[0:2]}
		return (peek(state, 0) * 100 + peek(state, 1)) % 251
""")


GENERATORS = [
    gen_expect_struct_shape,
    gen_struct_payload_beside_scalar,
    gen_array_payload_field,
    gen_expect_variant_payload_shape,
    gen_packed_nested_payload_decode,
    gen_static_protocol_dispatch,
    gen_index_profile_statement_match,
    gen_return_type_generic_inference,
    gen_shorthand_member_argument,
    gen_flags_bit_test_index,
    gen_index_returned_darray,
    gen_view_over_borrowed_darray,
    gen_slice_of_temporary,
    gen_view_field_element_read,
]
