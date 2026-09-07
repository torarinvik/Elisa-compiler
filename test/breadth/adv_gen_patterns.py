#!/usr/bin/env python3
"""Adversarial differential generators — destructuring moves, pointer casts on floats, named argument order, nested variant
sub-patterns, loop filters, `do` blocks, container-literal declarations, and
compile-time calls

Each generator yields (name, source) pairs; adversarial_differential.py runs them.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))




def gen_move_as_destructure():
    """`move pair as Pair(left, right)` -- a DESTRUCTURING move.

    The parser lowers it to Block("move", ...) wrapping a Match whose arms have EMPTY
    bodies plus one uninitialized VarDecl per binder. The backend handled no "move" block
    kind at all, so every use declined. stage0 lowers it as a plain per-field extract into
    fresh locals -- the arms carry no runtime test because the scrutinee's STATIC type
    already names the struct.

    The fixture uses ASYMMETRIC field values so a position mix-up changes the answer
    rather than merely compiling: 3*10 + 5 = 35, where swapped binders would give 53.
    """
    yield ("move_as_destructure_positions", """
struct Pair:
	left: mutable i64
	right: mutable i64

def split(pair: Pair) -> i64:
	move pair as Pair(left, right)
	return left * 10 + right

def main() -> i64:
	return split(Pair{left: 3, right: 5})
""")




def gen_float_pointer_cast():
    """`v.cast[heap u8&]` from an f64 -- a FLOAT source reinterpreted as a pointer.

    There is no direct opcode and `inttoptr double` is invalid IR, so the integer step
    has to be spelled out: stage0 emits `fptoui` then `inttoptr`. stage1's reinterpret
    gate admitted only pointer, integer and narrowed-optional-pointer sources, so a float
    fell through and declined.

    Round-tripped back through `.uintptr()` so the VALUE is checked (42), not just that
    the program builds.
    """
    yield ("float_to_pointer_cast_roundtrip", """
def cast_ptr(v: f64) -> heap u8& can[Unsafe.PointerCast]:
	return v.cast[heap u8&]

def main() -> i64 can[Unsafe.PointerCast]:
	p: heap u8& = cast_ptr(42.0)
	return p.uintptr().i64()
""")




def gen_named_call_argument_order():
    """Labelled call arguments supplied OUT OF ORDER (`combine(y: 7, x: 3)`).

    No bug was found here -- this pins an invariant whose failure mode is a SILENT WRONG
    ANSWER rather than a decline: a backend that ignored the labels and bound positionally
    would compile happily and return 73 instead of 37. Worth a fixture precisely because
    nothing currently fails it.
    """
    yield ("named_call_arguments_out_of_order", """
def combine(x: i64, y: i64) -> i64:
	return x * 10 + y

def main() -> i64:
	return combine(y: 7, x: 3)
""")




def gen_user_enum_named_like_ast_node():
    """A user enum named `Expr` (or Node/Stmt/Decl/Pattern) -- the compiler's own AST
    node names.

    These five were effectively RESERVED in stage1: `new_struct_table` reserved AST
    packed-store headers for them in EVERY program, so an ordinary `enum Expr:` found a
    packed slot already present, was registered as a packed AoS enum instead of a payload
    enum, and its constructor declined. Renaming the enum to `Shape` compiled the
    byte-identical program -- the bug was reachable by NAME ALONE.

    One case per reserved name so a partial fix cannot pass, and each RUNS (payload bound
    from one variant, constant from the other) rather than merely compiling: 3*10 + 5 = 35.
    """
    for name in ("Expr", "Node", "Stmt", "Decl", "Pattern"):
        yield (f"user_enum_named_{name.lower()}", f"""
enum {name}:
	Leaf(v: i64)
	Missing

def score(e: {name}) -> i64:
	match e:
		{name}.Leaf(k):
			return k
		{name}.Missing:
			return 5
	return 9

def main() -> i64:
	return score({name}.Leaf(3)) * 10 + score({name}.Missing)
""")




def gen_nested_variant_subpattern():
    """A NESTED variant sub-pattern in a single-field payload --
    `Expr.Leaf(Token.Ident)`, and the alternation `Expr.Leaf(Token.Ident | Token.Keyword)`.

    The match emitter accepted only a Binding or Wildcard as a single-field sub-pattern,
    so both declined. stage0 loads the payload at ITS OWN type and compares against the
    nested variant's ordinal, falling through on a mismatch; this now does the same, with
    the alternation OR-ing the comparisons.

    Both fixtures probe EVERY variant and weight the results, so an arm that matched
    without testing the nested pattern changes the answer rather than merely compiling:
    the single form gives 100 (110 if untested), the alternation 110 (111 if untested).

    A nested variant that itself BINDS still declines -- its sub-fields would have to be
    read too, and matching without testing them is a wrong answer, not a drop.
    """
    yield ("nested_variant_subpattern_single", """
enum Token:
	Ident
	Keyword
	Other

enum Expr:
	Leaf(kind: Token)
	Missing

def score(expr: Expr) -> i64:
	match expr:
		Expr.Leaf(Token.Ident):
			return 1
		_:
			return 0

def main() -> i64:
	return score(Expr.Leaf(Token.Ident)) * 100 + score(Expr.Leaf(Token.Keyword)) * 10 + score(Expr.Missing)
""")
    yield ("nested_variant_subpattern_or", """
enum Token:
	Ident
	Keyword
	Other

enum Expr:
	Leaf(kind: Token)
	Missing

def score(expr: Expr) -> i64:
	match expr:
		Expr.Leaf(Token.Ident | Token.Keyword):
			return 1
		_:
			return 0

def main() -> i64:
	return score(Expr.Leaf(Token.Ident)) * 100 + score(Expr.Leaf(Token.Keyword)) * 10 + score(Expr.Leaf(Token.Other))
""")




def gen_loop_where_filter():
    """`for x in xs where COND:` -- a boolean filter on a container loop.

    The parser wraps the iterable as Expr.Refinement(base, condition) and NOTHING in the
    loop emitter matched Refinement, so the whole loop declined -- a plain boolean filter,
    not just the pattern-filter forms. Desugared to `for x in base: if COND: body`, which
    reaches every iteration path (darray, fixed array, dict, enumerate) untouched.

    The fixture keeps one element BELOW the threshold so a dropped filter changes the
    answer: 5 + 3 = 8, versus 9 if the filter were ignored.

    NOT covered, deliberately: a RANGE base (`for i in 0..<10 where c:`). stage0's PARSER
    rejects that outright ("expected :, got where") while stage1's parser accepts it, so
    emitting it would run a program stage0 refuses -- the PERMISSIVE direction. The
    backend declines that shape so both compilers keep refusing it.
    """
    yield ("loop_where_filter_container", """
def total(xs: darray[i64]&) -> i64:
	sum: mutable i64 = 0
	for x in xs where x > 2:
		sum <- sum + x
	return sum

def main() -> i64:
	xs: mutable darray[i64] = []
	xs.push(1)
	xs.push(5)
	xs.push(3)
	return total(xs)
""")




def gen_loop_bare_pattern_filter():
    """`for item in items where Expr.Int(value):` -- a BARE PATTERN filter, no `item is`
    in front. It BINDS the payload as well as testing the tag, so it is not a boolean
    condition and could not go through the plain `where` desugaring.

    It is exactly what `LOOPVAR is Enum.Variant(binders)` already means, and that form was
    fully lowered, so the loop rewrites to it rather than growing a second
    pattern-matching path. (The semantic half -- putting the binders in scope -- landed
    separately in 7d4b49c3 / 0f03de4a.)

    The fixture interleaves a NON-matching variant between two matching ones, so a filter
    that failed to skip would add garbage and a binding that read the wrong field would
    change the sum: 4 + 9 = 13.

    Multi-binder loops (`for k, v in d where ...`) still decline -- there is no single
    subject for the `is` test.
    """
    yield ("loop_bare_pattern_filter", """
enum Expr:
	Int(value: i64)
	Missing

def total(items: darray[Expr]&) -> i64:
	sum: mutable i64 = 0
	for item in items where Expr.Int(value):
		sum <- sum + value
	return sum

def main() -> i64:
	xs: mutable darray[Expr] = []
	xs.push(Expr.Int(4))
	xs.push(Expr.Missing)
	xs.push(Expr.Int(9))
	return total(xs)
""")




def gen_struct_pattern_tests_and_nesting():
    """Struct patterns with LITERAL/shorthand field tests and one level of NESTING --
    `tok is Token(kind: .INTEGER, span: Span(start: start), value: value)`.

    Three separate gaps met here. The `is` struct path modelled only bare-Ident fields
    (all bindings, result a constant true), so a field tested against a constant declined.
    The PARENTHESISED spelling parses as a labelled CALL, not Expr.Construct, so it was
    never seen at all -- and the NESTED pattern inside it is a labelled call too, which is
    why normalising only the outer level left the function still declined.

    The fixture feeds one MATCHING and one NON-matching token, so a pattern that ignored
    the `.INTEGER` test would take the arm for both: 70 when correct (7*10 + 0), 76 if the
    test were dropped.
    """
    yield ("struct_pattern_tests_and_nesting", """
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
	if tok is Token(kind: .INTEGER, span: Span(start: start), value: value):
		return start + value
	return 0

def main() -> i64:
	hit: Token = Token{kind: Tok.INTEGER, span: Span{start: 3, finish: 9}, value: 4}
	miss: Token = Token{kind: Tok.FLOAT, span: Span{start: 5, finish: 9}, value: 6}
	return score(hit) * 10 + score(miss)
""")




def gen_untyped_literal_binding():
    """`seed = 3` -- an UNTYPED local declared by first assignment from an integer
    literal.

    A bare `x = v` folds to Stmt.Assign, NOT Stmt.VarDecl, so the VarDecl site's
    "integer literal defaults to signed 64" rule never reached it: an int literal has no
    intrinsic type, inference left it Unmodeled, and the declaration declined. (Third
    time this session a fix landed on the VarDecl path when the spelling reaches Assign.)
    """
    yield ("untyped_literal_binding", """
def main() -> i64:
	seed = 3
	other = 5
	return seed * 10 + other
""")




# NOT a generator: labelled arguments through a `fn`-typed local
# (`runner(y: 7, x: 3)`) are a KNOWN PARITY GAP. stage1 used to answer 73 where stage0
# answers 37 -- a SILENT WRONG ANSWER, because the indirect call path takes no argument
# names and passed them POSITIONALLY. stage1 now DECLINES that form, which makes the case
# a DECLINE outcome, and DECLINE is ratcheted at ZERO by adversarial_differential_smoke --
# adding it would fail the gate without fixing anything. Documented in
# stage0-backend-corpus-gap instead. The DIRECT labelled call
# (gen_named_call_argument_order) stays a MATCH and proves labels are honoured wherever
# the target's parameter names can be resolved.


def gen_do_block_declaration():
    """`x = do: <stmts> <tail>` -- an un-annotated declaration from a VALUE BLOCK.

    Its type is the TAIL's, but the tail routinely names locals the block itself declares
    (`do: base = 5 / base + 7`), so it cannot be typed before those statements run:
    expression_type answered Unmodeled and the declaration declined. The statements are
    now emitted FIRST, then the tail is typed and emitted with the block's locals in
    scope.

    The fixture's tail DEPENDS on a block-local, which is the whole difficulty -- a
    version whose tail used only outer scope would pass without the fix.
    """
    yield ("do_block_declaration", """
def build() -> i64:
	value = do:
		base = 5
		base + 7
	return value

def main() -> i64:
	return build()
""")




def gen_flat_container_literal_declaration():
    """`values = [1, 2, 3, 4]` -- an un-annotated declaration from a CONTAINER LITERAL.

    expression_type answers Unmodeled for a literal by design (a literal DEFERS to its
    expected type), so the declaration declined even though the annotated form works.
    literal_container_type derives the shape from the elements; it is used only at the
    declaration site, never taught to expression_type, because a global change there
    previously produced a WRONG ANSWER for nested literals.

    FLAT only, matching stage0: it infers this but REJECTS `m = [[1, 2], [3, 4]]`
    ("cannot infer element type for empty darray builder"). Taking the nested shape too
    made stage1 run a program stage0 refuses -- PERMISSIVE, which the gate ratchets at
    zero. The nested form still declines, so both compilers refuse it.

    The fixture slices the inferred darray and indexes the view, so the element type has
    to be right, not merely present.
    """
    yield ("flat_container_literal_declaration", """
def head_of_middle() -> int:
	values = [1, 2, 3, 4]
	part: view[int] = values[1:3]
	return part[0]

def main() -> i64:
	return head_of_middle().i64()
""")




def gen_extend_darray_from_view():
    """`xs.extend(v)` where v is a `view[T]` -- appending a view's elements to a darray.

    `extend` was modelled for a darray source, an sview BYTE source, an array literal and
    a comprehension, but not for a typed view, so the whole function declined. Lowered on
    the same shape as the sview path (loop the length, push `src[i]`, reusing the existing
    view indexing) but element-typed, with the source and target element types required to
    agree.

    The fixture extends from a SLICE of the middle (`src[1:4]`), sums the result and
    reports the count, so both WHICH elements were copied and HOW MANY have to be right:
    9*10 + 3 = 93. Copying the whole source instead would give 153.
    """
    yield ("extend_darray_from_view", """
def copy_span(src: darray[i64]) -> i64:
	xs: mutable darray[i64] = []
	v: view[i64] = src[1:4]
	xs.extend(v)
	total: mutable i64 = 0
	for x in xs:
		total <- total + x
	return total * 10 + xs.count.i64()

def main() -> i64:
	s: mutable darray[i64] = []
	s.push(1)
	s.push(2)
	s.push(3)
	s.push(4)
	s.push(5)
	return copy_span(s)
""")




def gen_resize_non_scalar_element():
    """`darray[view[u8]].resize(n)` -- resizing a container whose ELEMENT is not a scalar.

    The growth loop was always element-type agnostic; only the FILL was not. It pushed an
    `IntLit(0)`, so the method was restricted to scalar elements and a container element
    declined. A non-scalar element now fills with `zeroed`, the language's own zero value.

    Pins BOTH element kinds in one fixture, so generalising the fill cannot regress the
    scalar path it replaced: 8*10 + 3 = 83. The scalar case also starts non-empty, so a
    resize that ignored the existing count would report the wrong number.
    """
    yield ("resize_non_scalar_element", """
def kernel() -> usize:
	xs: mutable darray[view[u8]] = []
	_ = xs.resize(8.usize())
	return xs.count

def scalar_still_works() -> usize:
	ys: mutable darray[i64] = []
	ys.push(7)
	_ = ys.resize(3.usize())
	return ys.count

def main() -> i64:
	return kernel().i64() * 10 + scalar_still_works().i64()
""")




def gen_literal_payload_is_test():
    """`node is Expr.Float(3.14)` -- a LITERAL payload sub-pattern in an `is` test.

    A binder ident NARROWS (binds the payload); a literal is a VALUE TEST -- it matches
    only when the tag agrees AND the payload equals the literal. Only binders were
    modelled, so every literal payload declined. Handled for the SINGLE-field variant;
    a multi-field variant with literals mixed in keeps declining rather than testing some
    fields and silently ignoring others.

    Each fixture probes three cases -- matching payload, NON-matching payload, and a
    different variant -- so both halves of the conjunction have to work: 100 when correct,
    110 if the payload test were dropped, 101 if the tag test were.

    The float case is pinned separately because it must compare with FCmp, not ICmp.
    """
    yield ("literal_payload_is_test_int", """
enum E:
	A(v: int)
	B

def is_seven(node: E) -> bool:
	return node is E.A(7)

def main() -> i64:
	hit: i64 = 1 if is_seven(E.A(7)) else 0
	miss: i64 = 1 if is_seven(E.A(9)) else 0
	other: i64 = 1 if is_seven(E.B) else 0
	return hit * 100 + miss * 10 + other
""")
    yield ("literal_payload_is_test_float", """
enum Expr:
	Float(PI: f64)
	Int(value: int)

def is_pi(node: Expr) -> bool:
	return node is Expr.Float(3.14)

def main() -> i64:
	hit: i64 = 1 if is_pi(Expr.Float(3.14)) else 0
	miss: i64 = 1 if is_pi(Expr.Float(2.71)) else 0
	other: i64 = 1 if is_pi(Expr.Int(3)) else 0
	return hit * 100 + miss * 10 + other
""")




def gen_static_compile_time_call():
    """`static answer(2)` / `static: answer(2)` where `answer` is a `static def`.

    A call to a static def is COMPILE-TIME only -- stage0 evaluates it during static
    execution and emits nothing (`keep()` lowers to an empty body, with no `@answer` in
    the module). select_module_declarations already drops `static def` declarations, so
    the callee has no FnTable entry, the call could not be emitted, and it took the whole
    enclosing function down with it.

    The fixture deliberately ALSO contains a `static if` whose taken branch mutates a
    local, because that is the reason a static block emits inline at all: dropping the
    whole block instead of just the compile-time calls would lose it. 5 + 3 = 8.
    """
    yield ("static_compile_time_call", """
static def answer(step: i64) -> i64:
	return step + 40

def keep() -> i64:
	static answer(2)
	static:
		answer(2)
	total: mutable i64 = 5
	static if true:
		total <- total + 3
	return total

def main() -> i64:
	return keep()
""")


GENERATORS = [
    gen_move_as_destructure,
    gen_float_pointer_cast,
    gen_named_call_argument_order,
    gen_user_enum_named_like_ast_node,
    gen_nested_variant_subpattern,
    gen_loop_where_filter,
    gen_loop_bare_pattern_filter,
    gen_struct_pattern_tests_and_nesting,
    gen_untyped_literal_binding,
    gen_do_block_declaration,
    gen_flat_container_literal_declaration,
    gen_extend_darray_from_view,
    gen_resize_non_scalar_element,
    gen_literal_payload_is_test,
    gen_static_compile_time_call,
]
