#!/usr/bin/env python3
"""Adversarial differential generators — match ARMS: bare projection patterns, null arms, nested and labelled variants,
enum bounds in a membership range, wide payload enums, and the first packed-store
matches

Each generator yields (name, source) pairs; adversarial_differential.py runs them.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))




def gen_projection_query_bare_pattern():
    """`value for each item in items where Expr.Int(value)` -- a PROJECTION query whose
    filter is a BARE PATTERN that binds the value the projection then uses.

    A bare pattern is not a predicate: it must BIND the payload as well as test the tag. It
    means exactly `BINDER is PATTERN`, which is fully lowered, so the shared query-filter
    helper now rewrites to that -- the same rewrite the `for`-loop filter already did.

    Folded positionally over a list containing a non-matching variant (58 after truncation),
    so collecting the wrong elements changes the answer.

    The GUARDED spelling of this form is deliberately NOT covered: the projection node has
    no slot for a guard (its body holds the projection), and emitting the filter without the
    guard collected the excluded elements -- stage1 answered 38 where stage0 answers 34.
    That shape now declines, via a parser marker recording that the guard was dropped.
    """
    yield ("projection_query_bare_pattern", """
enum Expr:
	Int(value: i64)
	Missing

def plain(items: darray[Expr]) -> darray[i64]:
	return value for each item in items where Expr.Int(value)

def fold(xs: darray[i64]) -> i64:
	total: mutable i64 = 0
	for x in xs |total|:
		total <- total * 10 + x
	return total

def main() -> i64:
	src: darray[Expr] = [Expr.Int(3), Expr.Missing, Expr.Int(1), Expr.Int(4)]
	return fold(plain(src))
""")




def gen_optional_match_null_arm():
    """`match OPT:` with a literal `null` arm PLUS payload arms -- both the statement and the
    expression spelling.

    The optional-scrutinee branch handled exactly TWO arms and required one of them to be a
    plain BINDING, so three-arm forms (`null:` / `Expr.Int(value):` / `_:`) declined. The
    payload is now bound to a synthetic local and the REMAINING arms are re-entered as an
    ordinary match on it, so every payload pattern the match emitter already models works
    here unchanged. The `return match` spelling routes through the same path by rewriting
    each arm's value into a `return`.

    Three optionals -- a payload variant, a payload-free variant, and null -- run through
    BOTH spellings at distinct weights (192), so a missed arm or a swapped branch moves the
    total, and the two spellings check each other.
    """
    yield ("optional_match_null_arm", """
enum Expr:
	Int(value: i64)
	Missing

def score_stmt(maybe: Expr?) -> i64:
	match maybe:
		null:
			return 0
		Expr.Int(value):
			return value
		_:
			return 2
	return 3

def score_expr(maybe: Expr?) -> i64:
	return match maybe:
		null:
			0
		Expr.Int(value):
			value
		_:
			2

def main() -> i64:
	a: Expr? = Expr.Int(7)
	b: Expr? = Expr.Missing
	c: Expr? = null
	return (score_stmt(a) * 8 + score_stmt(b) * 4 + score_stmt(c)) * 2 + (score_expr(a) * 8 + score_expr(b) * 4 + score_expr(c))
""")




def gen_nested_variant_match_arm():
    """`Outer.Wrap(Inner.A(inner)):` -- a match arm whose nested variant CARRIES a payload
    and binds it.

    Payloadless nesting (`Expr.Leaf(Token.Ident)`) already worked: there the outer payload
    word IS the nested tag. A payload-carrying nested enum keeps its tag inside its own
    aggregate, so the old path would have compared the wrong bytes and deliberately declined.
    The tag is now read from field 0 of the nested aggregate and the binder from field 1.

    Restricted to a SINGLE nested path: an alternation over payload-carrying variants would
    bind different payload types per option, which one binder cannot express.

    All three arms are exercised at distinct weights (3*16 + 5*4 + 7 = 75), deliberately
    sized to fit in a byte, so a mis-tested tag or a mis-bound payload moves the total.
    """
    yield ("nested_variant_match_arm", """
enum Inner:
	A(i64)
	B

enum Outer:
	Wrap(Inner)
	Empty

def nested_value(value: Outer) -> i64:
	match value:
		Outer.Wrap(Inner.A(inner)):
			return inner
		Outer.Wrap(Inner.B):
			return 5
		Outer.Empty:
			return 7
	return 9

def main() -> i64:
	a: Outer = Outer.Wrap(Inner.A(3))
	b: Outer = Outer.Wrap(Inner.B)
	c: Outer = Outer.Empty
	return nested_value(a) * 16 + nested_value(b) * 4 + nested_value(c)
""")




def gen_labelled_payload_match_arm():
    """`PairOrInt.Pair(right: r, left: l):` -- payload patterns written with FIELD LABELS,
    in an order that does not match the declaration.

    Labelled fields arrive as `Pattern.Field(label, [Binding])`, which the arm gatherer did
    not model at all, and the bind loop indexes binders by DECLARED position -- so accepting
    them without reordering would have bound `left` from `right`. Each label now resolves to
    its declared index and fills that slot; unlabelled fields fill positionally, so the plain
    spelling is untouched.

    The labelled arm is deliberately written REVERSED (`right:` before `left:`) and its
    result is asymmetric (l*10 + r), so a lowering that ignored the labels would answer 32
    where the correct value is 23. The positional spelling runs the same inputs as a control,
    and the two are subtracted -- so both must be right, not merely equal.
    """
    yield ("labelled_payload_match_arm", """
enum PairOrInt:
	Just(value: i64)
	Pair(left: i64, right: i64)

def labelled(value: PairOrInt) -> i64:
	match value:
		PairOrInt.Just(value: inner):
			return inner
		PairOrInt.Pair(right: r, left: l):
			return l * 10 + r
	return 0

def positional(value: PairOrInt) -> i64:
	match value:
		PairOrInt.Just(inner):
			return inner
		PairOrInt.Pair(l, r):
			return l * 10 + r
	return 0

def main() -> i64:
	a: PairOrInt = PairOrInt.Just(7)
	b: PairOrInt = PairOrInt.Pair(2, 3)
	return (labelled(a) + labelled(b)) - (positional(a) + positional(b)) + labelled(b)
""")




def gen_membership_range_enum_bounds():
    """`kind in {.IF..=IDENT, .NUMBER..<STRING}` -- brace-set membership whose RANGE bounds
    are enum members, the second written UNQUALIFIED.

    The leading-dot shorthand already resolved; the bare second bound did not, and it is the
    spelling stage0 accepts, so every set containing such a range declined. A bare name is
    rewritten to `Enum.MEMBER` only when it is NOT a local in scope and exactly ONE const
    enum declares it -- otherwise `probe in {lo..=hi}` over VARIABLES would be rewritten into
    nonsense.

    That variable-bound form is exercised in the same fixture as a control, on both sides of
    its range, and all five enum members are probed, folded into a bitmask (122) so a wrong
    inclusive/exclusive edge or a mis-resolved bound moves it.
    """
    yield ("membership_range_enum_bounds", """
const enum TokenKind of u32:
	IF
	LET
	IDENT
	NUMBER
	STRING

def keep(kind: TokenKind) -> bool:
	return kind in {.IF..=IDENT, .NUMBER..<STRING}

def bounds(lo: u32, hi: u32, probe: u32) -> bool:
	return probe in {lo..=hi}

def bit(b: bool) -> i64:
	return 1 if b else 0

def main() -> i64:
	mask: mutable i64 = 0
	mask <- mask * 2 + bit(keep(TokenKind.IF))
	mask <- mask * 2 + bit(keep(TokenKind.LET))
	mask <- mask * 2 + bit(keep(TokenKind.IDENT))
	mask <- mask * 2 + bit(keep(TokenKind.NUMBER))
	mask <- mask * 2 + bit(keep(TokenKind.STRING))
	mask <- mask * 2 + bit(bounds(2.u32(), 4.u32(), 3.u32()))
	mask <- mask * 2 + bit(bounds(2.u32(), 4.u32(), 5.u32()))
	return mask
""")




def gen_wide_payload_enum():
    """`enum Wide: First(items: array[i64, 4])` -- a payload enum whose sole payload is an
    ARRAY, i.e. wider than one blob word.

    stage0 sizes `{i32, [N x i64]}` by the payload's WORD COUNT; stage1 sized it by the
    variant's FIELD COUNT, so an array payload would have got `[1 x i64]`. The acceptance
    guard that rejected array payloads was therefore LOAD-BEARING: relaxing it alone made
    this program compile and SEGFAULT.

    Layout first, acceptance second. The width is taken only for an i64-element array, the
    one case checked against stage0's own IR; anything else still declines rather than risk
    an undersized blob.

    Every slot of the array is read -- including the LAST (`items[3]`), which is exactly what
    an undersized blob corrupts -- through both a match arm and an `is` binding, folded to 41.
    """
    yield ("wide_payload_enum", """
enum Wide:
	First(items: array[i64, 4])
	Second(items: array[i64, 4])
	Empty

def inspect(value: Wide) -> i64:
	match value:
		Wide.First(items):
			return items[0] * 10 + items[3]
		Wide.Second(items):
			return items[1] * 10 + items[2]
		Wide.Empty:
			return 5
	return 9

def narrow(value: Wide) -> i64:
	if value is Wide.First(items):
		return items[2]
	return 0

def main() -> i64:
	a: Wide = Wide.First([1, 2, 3, 4])
	b: Wide = Wide.Second([1, 2, 3, 4])
	c: Wide = Wide.Empty
	return inspect(a) + inspect(b) - inspect(c) + narrow(a) * 3
""")




def gen_unannotated_comprehension_decl():
    """`xs = [item + 1 for item in items if item > 0]` -- a comprehension declared with NO
    type annotation, over both a darray and a RANGE source.

    expression_type answers Unmodeled for a comprehension (its type comes from context, and a
    bare `=` supplies none), and the literal-shape fallback reads only Array literals, so the
    declaration declined while the annotated form worked. The element type is the
    PROJECTION's, evaluated with the binder temporarily bound to the source's element type.

    Both results are folded POSITIONALLY (45 and 123, summed to 168), so a wrong element
    type, a dropped filter, or a reversed traversal changes the answer.
    """
    yield ("unannotated_comprehension_decl", """
def build(items: darray[i64]) -> i64:
	xs = [item + 1 for item in items if item > 0]
	total: mutable i64 = 0
	for x in xs |total|:
		total <- total * 10 + x
	return total

def counted(n: usize) -> i64:
	ys = [index for index in 1..<n]
	total: mutable i64 = 0
	for y in ys |total|:
		total <- total * 10 + y.i64()
	return total

def main() -> i64:
	src: darray[i64] = [3, -1, 4]
	return build(src) + counted(4.usize())
""")




def gen_struct_pattern_match_arm():
    """`match tok: Token(kind: .INTEGER, span: Span(start: start), value: value): … / _: …`
    -- a struct-pattern arm that TESTS a field and destructures, with a tail arm.

    The struct-pattern match path emitted arm 0 UNCONDITIONALLY, which is correct only for a
    destructure with nothing to test and nothing after it -- so the tested form declined. The
    `is` spelling of the same pattern was already fully lowered (field tests, nested struct
    fields, bindings), so the arm is REBUILT as an `is` expression and becomes
    `if SCRUT is PATTERN: body else: <rest>`. No second struct-matching engine.

    Both arms are exercised (a matching and a non-matching kind) at distinct weights (77), so
    a test that always passes -- the previous behaviour -- answers 7*10+7 instead.
    """
    yield ("struct_pattern_match_arm", """
const enum Tok of i32:
	INTEGER = 1
	FLOAT = 2

struct Span:
	start: i64
	finish: i64

struct Token:
	kind: Tok
	span: Span
	value: i64

def score(tok: Token) -> i64:
	match tok:
		Token(kind: .INTEGER, span: Span(start: start), value: value):
			return start + value
		_:
			return 7

def main() -> i64:
	a: Token = Token{kind: Tok.INTEGER, span: Span{start: 3, finish: 9}, value: 4}
	b: Token = Token{kind: Tok.FLOAT, span: Span{start: 3, finish: 9}, value: 4}
	return score(a) * 10 + score(b)
""")




def gen_user_packed_enum_store():
    """A USER `packed enum` with its own store -- `new[store] Node.Empty(zeroed)`.

    The AoS store subsystem was gated on `packed_is_ast_root`, historically
    `name == "Node" and variant_count == 0`: the compiler's own AST-root PLACEHOLDER row.
    That was believed to be what blocked every user packed enum. Measured, it blocks exactly
    ONE of the 21 packed corpus files -- this shape -- and the other 20 decline for their own
    reasons.

    This pins the shape that does work, so the relaxation cannot silently regress.
    """
    yield ("user_packed_enum_store", """
struct Payload:
	data: mutable u8&?
	len: mutable i32

packed enum Node:
	Empty(Payload)
	Byte(u8)

def build() -> i64:
	region scratch(256)
	store: Node.Store[Local] = Node.Store(scratch)
	n: Node = new[store] Node.Empty(zeroed)
	_ = n
	destroy scratch
	return 7

def main() -> i64:
	return build()
""")




def gen_packed_match_default_profile():
    """A DEFAULT-profile `packed enum` store, `new`, and a `match` over the stored node.

    A user packed enum gets the variant-sparse profile (mode 0); the match STATEMENT emitter
    implemented only the AoS profile (mode 2), so the store and `new` compiled while the
    match declined. Mode 0 reads the tag through
    `ctx_packed_store_read_variant_sparse_tag` and each payload word through
    `ctx_packed_store_read_variant_sparse_word` -- both already declared, and already used by
    the match EXPRESSION emitter.

    The payload VALUE is read back (5, not just a tag test), which is what catches a store
    created with the wrong row stride: an earlier version of this change had the user enum
    reporting the AST root's 132-byte row and every payload read back as 0.
    """
    yield ("packed_match_default_profile", """
packed enum Expr:
	Lit(value: i64)

def fold() -> i64:
	region scratch(256)
	store: Expr.Store[Local] = Expr.Store(scratch)
	in store:
		node: Expr = new Expr.Lit(value: 5)
		match node:
			Expr.Lit(value):
				out: i64 = value
				destroy scratch
				return out

def main() -> i64:
	return fold()
""")




def gen_packed_match_in_store_clause():
    """`match node in store:` -- the packed IN-STORE clause on a match header.

    `in` is a binary operator, so the parser hands the header over as
    `Binary(NODE, In, STORE)` and the scrutinee reads as a boolean membership test. It is
    unwrapped in the match emitter -- NOT in the parser: a parser-side split stops the
    resolver walking the store expression, and stage0 reports BOTH an undefined store name
    and the store-type error, so splitting there loses a diagnostic.

    Both variants are exercised through the clause, with the payload VALUE read back and the
    two results weighted apart (5*10 + 3 = 53).
    """
    yield ("packed_match_in_store_clause", """
packed enum Expr:
	Lit(value: i64)
	End

def fold(node: Expr, frozen: Expr.Store[Local]) -> i64:
	match node in frozen:
		Expr.Lit(value):
			return value * 10
		Expr.End:
			return 3
	return 9

def build() -> i64:
	region scratch(256)
	store: Expr.Store[Local] = Expr.Store(scratch)
	total: mutable i64 = 0
	in store:
		a: Expr = new Expr.Lit(value: 5)
		b: Expr = new Expr.End
		total <- fold(a, store) + fold(b, store)
	destroy scratch
	return total

def main() -> i64:
	return build()
""")




def gen_packed_multi_field_payload():
    """`Pair.Both(left: left, right: right)` -- a packed variant with a MULTI-FIELD payload,
    destructured with LABELLED binders.

    Two blockers, one behind the other. The arm gatherer accepted only bare `Binding` or
    `Wildcard` sub-patterns, so a labelled binder (a `Field` wrapping a `Binding`) declined
    before any payload code ran. And under the variant-sparse profile each payload field is
    its OWN word at `1 + commons + i`, not one aggregate load -- the single-word read tried
    to convert one i64 into the whole payload STRUCT.

    Labels resolve to their DECLARED index, so the word read matches the binder; the result
    is asymmetric (left*10 + right = 23), which a swapped pair would report as 32.
    """
    yield ("packed_multi_field_payload", """
packed enum Pair:
	Both(left: i64, right: i64)
	End

def sum_pair() -> i64:
	region scratch(256)
	store: Pair.Store[Local] = Pair.Store(scratch)
	in store:
		node: Pair = new Pair.Both(left: 2, right: 3)
		match node:
			Pair.Both(left: left, right: right):
				out: i64 = left * 10 + right
				destroy scratch
				return out
			Pair.End:
				destroy scratch
				return 0

def main() -> i64:
	return sum_pair()
""")


GENERATORS = [
    gen_projection_query_bare_pattern,
    gen_optional_match_null_arm,
    gen_nested_variant_match_arm,
    gen_labelled_payload_match_arm,
    gen_membership_range_enum_bounds,
    gen_wide_payload_enum,
    gen_unannotated_comprehension_decl,
    gen_struct_pattern_match_arm,
    gen_user_packed_enum_store,
    gen_packed_match_default_profile,
    gen_packed_match_in_store_clause,
    gen_packed_multi_field_payload,
]
