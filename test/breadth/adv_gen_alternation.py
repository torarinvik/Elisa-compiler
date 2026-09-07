#!/usr/bin/env python3
"""Adversarial differential generators — `is` alternation (bracketed and grouped), the unified `else` recovery forms,
nullable extern refs, labelled calls through an `fn` alias, shadowing, proof-block
erasure, refined type aliases and the view surface

Each generator yields (name, source) pairs; adversarial_differential.py runs them.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))




def gen_darray_as_cstr():
    """`xs.as_cstr()` -- borrow a `darray[u8]` as a NUL-terminated C string.

    `grep '"as_cstr"' src/backend` found nothing: unimplemented in codegen, so every use
    dropped its function. Lowered as stage0 does -- make room for one more byte through
    the same grow/realloc path a push uses, write the NUL at index `count`, hand back the
    items pointer -- and the COUNT is deliberately left alone, since the terminator is not
    an element.

    The fixture checks BOTH halves of that: `strlen` reads the terminator (3) while
    `xs.count` must still be 3, so 3*10 + 3 = 33. Incrementing the count would give 34,
    and omitting the NUL would make strlen run off the end.

    It also pins `xs.push([72, 105])` -- an ARRAY-LITERAL argument pushes EVERY element,
    which stage0 lowers as a bulk extend rather than a single push. Mixing the literal and
    scalar forms means a lowering that handled only one of them changes the length.
    """
    yield ("darray_as_cstr", """
extern strlen(s: cstr) -> usize

def main() -> i64:
	can Abort.Panic, Memory.Allocate:
		region r(256)
		in r:
			xs: mutable darray[u8] = []
			xs.push([72, 105])
			xs.push(33)
			s: cstr = xs.as_cstr()
			total: usize = strlen(s) * 10 + xs.count
			destroy r
			return total.i64()
	return 0
""")




def gen_is_bracketed_alternation():
    """`k is [.LT | .LTEQ | .GT | .GTEQ]` -- a BRACKETED ALTERNATION in an `is` test.

    It means "matches any of these", so each alternative is re-entered as its own `is`
    and the results are OR-ed. Reusing the per-leaf lowering is what makes the
    const-enum, leading-dot shorthand and payload-enum forms all work here without
    restating any of them. `|` parses as an ordinary binary operator inside the brackets,
    so the element list is flattened through Pipe/Or first.

    The fixture probes all four members of the alternation AND one outside it, folded
    into a bitmask, so an alternation that matched too much or too little changes the
    answer: 0b11110 = 30.

    The GROUPED spelling `is (A | B | C)` means the same thing and is pinned separately:
    it arrives as a Paren (sometimes nested) around the Pipe chain rather than as an
    Array, so handling only the bracketed form left the grouped one declining -- and the
    corpus uses both in ONE file.
    """
    yield ("is_bracketed_alternation", """
const enum Tok of i32:
	LT = 1
	LTEQ = 2
	GT = 3
	GTEQ = 4
	PLUS = 5

def is_rel(kind: Tok) -> bool:
	return kind is [.LT | .LTEQ | .GT | .GTEQ]

def main() -> i64:
	total: mutable i64 = 0
	total <- total * 2 + (1 if is_rel(Tok.LT) else 0)
	total <- total * 2 + (1 if is_rel(Tok.LTEQ) else 0)
	total <- total * 2 + (1 if is_rel(Tok.GT) else 0)
	total <- total * 2 + (1 if is_rel(Tok.GTEQ) else 0)
	total <- total * 2 + (1 if is_rel(Tok.PLUS) else 0)
	return total
""")




def gen_is_grouped_alternation():
    """`value is (A | B | C)` -- the GROUPED spelling of an alternation, equivalent to the
    bracketed one. Pinned alongside the bracketed form because the corpus file uses both
    and they take different AST shapes (Paren-around-Pipe vs Array).
    """
    yield ("is_grouped_alternation", """
enum Expr:
	Int
	Bool
	Char
	Missing

def grouped(value: Expr) -> bool:
	return value is (
		Expr.Int
		| Expr.Bool
		| Expr.Char
	)

def bracketed(value: Expr) -> bool:
	return value is [Expr.Int | Expr.Bool | Expr.Char]

def main() -> i64:
	total: mutable i64 = 0
	total <- total * 2 + (1 if grouped(Expr.Int) else 0)
	total <- total * 2 + (1 if grouped(Expr.Missing) else 0)
	total <- total * 2 + (1 if bracketed(Expr.Char) else 0)
	total <- total * 2 + (1 if bracketed(Expr.Missing) else 0)
	return total
""")




def gen_extern_error_return_not_an_export():
    """An `extern f(...) -> T error[E]` carries an internal `__error_return` annotation on
    `f`. The export-target lookup used to return the FIRST non-`__export_fn` annotation on
    an owner, so that internal marker read as an export target name: the export path fired
    on a plain extern, failed to build a wrapper for a target called "__error_return", and
    recorded `f` as DECLINED even though its declaration had lowered correctly.

    The fixture pairs a real `export fn` with such an extern so BOTH halves are pinned --
    the export must still emit, and the extern must stop declining. The harness ratchets
    declines at zero, which is what makes this fixture able to fail.
    """
    yield ("extern_error_return_not_an_export", """
error IoError:
	NotFound

extern read_file(path: u8&) -> cstr[file_text] error[IoError]

def add_impl(a: i64, b: i64) -> i64:
	return a + b

export fn add_two(a: i64, b: i64) -> i64 = add_impl

def main() -> i64:
	return add_impl(17, 25)
""")




def gen_unified_else_recovery():
    """The two `else`-recovery shapes that both parse to `Expr.GetElse` in RETURN position.

    `return get OPT else return V` -- emit_expression has no GetElse case, so the return
    path declined until it routed through the local-declaration emitter.

    `return try f(x) else err: BLOCK` -- the SAME node, but the guarded expression is an
    error-returning call, so the recovery runs on a nonzero status code rather than on an
    absent payload; the value emitter only knew how to PROPAGATE.

    Each is probed on both branches and folded into one number, so a recovery arm that runs
    when it shouldn't (or never runs) changes the answer: 7*10+11 = 81 and 7*10+13 = 83.
    """
    yield ("unified_else_recovery", """
error FileError:
	NotFound

def maybe_value(flag: bool) -> i64?:
	if flag:
		return 7
	return null

def read_value(flag: bool) -> i64 error[FileError]:
	if flag:
		return 7
	raise FileError.NotFound

def optional_return(flag: bool) -> i64:
	return get maybe_value(flag) else return 11

def try_error_binding(flag: bool) -> i64:
	return try read_value(flag) else err:
		return 13

def main() -> i64:
	got: i64 = optional_return(true) * 10 + optional_return(false)
	caught: i64 = try_error_binding(true) * 10 + try_error_binding(false)
	return got + caught - 100
""")




def gen_get_else_raise():
    """`x: T = get OPT else raise E.Tag` -- a `raise` recovery on a monadic unwrap.

    `raise` TERMINATES, but the recovery parser only treated return/break/continue that
    way; everything else was parsed as a value FALLBACK and folded into a Refinement node,
    which types the recovered expression by a value the branch never produces. The branch
    that makes unwrapping the optional sound was lost.

    Probed on both the present and absent path through a `catch`, so a recovery that does
    not actually raise changes the answer: 30 + 7 = 37.
    """
    yield ("get_else_raise", """
error MemoryError:
	OutOfMemory

def helper(n: i64) -> i64?:
	return 3 if n > 0 else null

def checked(n: i64) -> i64 error[MemoryError]:
	v: i64 = get helper(n) else raise MemoryError.OutOfMemory
	return v * 10

def run(n: i64) -> i64:
	return catch checked(n):
		ok:
			ok
		error e:
			7

def main() -> i64:
	return run(1) + run(-1)
""")




def gen_nullable_extern_ref_get():
    """`p: T& = get memchr(...) else raise E.Tag` over a NULLABLE-REFERENCE extern.

    stage0 represents `-> heap T&?` as a bare ptr with null meaning absent, so the extern
    registers as a plain Ref and the `get` path -- which tests for an Optional -- declined.
    Ref-ness alone is not enough to accept: stage0 REJECTS `get` on a non-nullable `T&`, so
    the marker for `?` is carried from the parser through FnTable.returns_nullable.

    memchr is the nullable source rather than a failing malloc: a huge malloc DOES return
    null at -O0 but the optimizer assumes success at -O2, which made an earlier version of
    this fixture report a spurious MISMATCH. memchr's answer is decided by the data.

    Both branches are real -- 'b' is in "abc", 'z' is not -- folded to 5*10+3 = 53, so a
    present-check with the wrong polarity changes the answer.
    """
    yield ("nullable_extern_ref_get", """
error MemoryError:
\tNotThere

extern memchr(s: cstr, c: i32, n: usize) -> heap void&?

def find_byte(c: i32) -> i64 error[MemoryError]:
\thit: heap void& = get memchr("abc", c, 3.usize()) else raise MemoryError.NotThere
\t_ = hit
\treturn 5

def attempt(c: i32) -> i64:
\treturn catch find_byte(c):
\t\tok:
\t\t\tok
\t\terror e:
\t\t\t3

def main() -> i64:
\treturn attempt(98) * 10 + attempt(122)
""")




def gen_labelled_call_through_fn_alias():
    """`runner(y: 7, x: <do-block>)` where `runner: fn(i64,i64)->i64 = add`.

    A `fn(...)` TYPE carries parameter types but no parameter NAMES, so there was nothing to
    reorder labels against and the call declined (it had earlier passed them POSITIONALLY,
    a silent wrong answer). The local now remembers which function it aliases, and the
    labels resolve against that function's parameter names.

    `add` SUBTRACTS and the labels are given in reverse order, so a lowering that ignores
    the labels yields 7-30 = -23 instead of 30-7 = 23.
    """
    yield ("labelled_call_through_fn_alias", """
def add(x: i64, y: i64) -> i64:
	return x - y

def build() -> i64:
	runner: fn(i64, i64) -> i64 = add
	return runner(y: 7, x: do:
		seed = 30
		seed
	)

def main() -> i64:
	return build()
""")




def gen_shadowing_assignment_declaration():
    """`acc = acc + 4` inside a nested block, where `acc` is already bound outside.

    stage1 declined this, treating an already-bound name as "not a declaration". stage0's
    rule is that `=` NEVER mutates -- `<-` is the mutation operator -- so the inner form
    reads the outer binding and declares a NEW one that dies with the block.

    The fixture makes the two readings differ: probe(true)*10 + probe(false) is 11 under
    shadowing and 51 if the assignment mutated the outer binding.
    """
    yield ("shadowing_assignment_declaration", """
def probe(flag: bool) -> i64:
	acc: mutable i64 = 1
	if flag:
		acc = acc + 4
	return acc

def main() -> i64:
	return probe(true) * 10 + probe(false)
""")




def gen_proof_block_erasure():
    """`assert C by:` and `proof C:` -- proof blocks whose BODY is compile-time only.

    Both parse to the same node, with the GOAL riding as body[0] and the proof steps after
    it. stage0 lowers the goal as an ordinary runtime contract check and emits nothing for
    the body; stage1 declined the whole block because the kind was unhandled.

    Three distinct spellings (assert-by, proof, `ensure ... by scoped:`) with different
    return arithmetic, summed to 46, so a block whose goal was dropped or whose body leaked
    into the emitted code changes the answer.
    """
    yield ("proof_block_erasure", """
lemma weaken(x: i64):
	requires x >= 10
	ensure x >= 5
	pass

def use(n: i64) -> i64:
	assert n >= 5 by:
		assert(n >= 10)
		weaken(n)
	return n

def proven(n: i64) -> i64:
	proof n >= 5:
		assert(n >= 10)
		weaken(n)
	return n + 1

def scoped_ensure(n: i64) -> i64:
	ensure result >= 5 by scoped:
		assert(result >= 10)
		weaken(result)
	return n + 10

def main() -> i64:
	return use(12) + proven(20) + scoped_ensure(3)
""")




def gen_first_query():
    """`first VAR in ITER where COND` -- the query whose result is an Optional.

    Two things were missing. The lowering itself (min/max were the only Optional-producing
    folds), and -- the reason a correct lowering still declined -- `first` was absent from
    comprehension_is_extremum, so emit_expression re-emitted it at the PAYLOAD type and the
    comprehension emitter saw `expected` = i64 instead of i64?.

    The probe list is [-3, 7, 5, -1]: `first` answers 7 where any extremal fold answers 5,
    so a min/max-shaped lowering yields 53 instead of 73. The second list has no match, so
    the absent path is exercised too.
    """
    yield ("first_query", """
def first_positive(items: darray[i64]) -> i64?:
	return first item in items where item > 0

def probe(items: darray[i64]) -> i64:
	f: i64? = first_positive(items)
	if f is hit:
		return hit
	return 3

def main() -> i64:
	a: darray[i64] = [-3, 7, 5, -1]
	b: darray[i64] = [-3, -5]
	return probe(a) * 10 + probe(b)
""")




def gen_refined_type_alias():
    """`type Lane4 = u32 is InRange[0, 3]` and `type Pct = i64 where ...` -- REFINED aliases.

    Both erase at runtime (stage0 lowers a `Lane4` parameter as a plain i32 and emits no
    check), but neither target is a type EXPRESSION: the `is` form is a Binary, and the
    fallback head heuristic keeps the last Ident in the span, which is the LAW's name. The
    alias stayed Unmodeled, so every function mentioning it declined -- including ones that
    only did arithmetic on the value.

    Both spellings are exercised, one as an ARRAY INDEX (30) and one in arithmetic (23),
    summing to 53 -- so an alias resolved to the wrong width or a dropped index changes it.
    """
    yield ("refined_type_alias", """
law InRange(self: u32, lo: u32, hi: u32) = self >= lo and self <= hi

type Lane4 = u32 is InRange[0, 3]
type Pct = i64 where 0 <= self and self <= 100

struct Vec4:
	lanes: mutable array[u32, 4]

def read_lane(v: Vec4&, lane: Lane4) -> u32:
	return v.lanes[lane]

def scale(p: Pct) -> i64:
	return p * 2 + 1

def main() -> i64:
	v: Vec4 = Vec4{lanes: [10, 20, 30, 40]}
	return read_lane(&v, 2.u32()).i64() + scale(11)
""")




def gen_builtin_string_surface():
    """Two independent gaps on the byte-array / string-view surface.

    `text[1]` on a `u8[4]` returned the raw i8 without converting to the EXPECTED type, so
    a `-> char` (or plain `-> i64`) context failed the return path's type-identity guard and
    the function declined -- while the same expression with an explicit `.i64()` compiled.
    The sibling optional-ref read one branch above already did the conversion.

    `sview[LO, HI]` is a LENGTH-BOUNDED view whose bounds are a type-level refinement with
    no representation (stage0 lowers it to a plain %StringView), but the annotation resolver
    had no case for it, so it stayed Unmodeled and the unbounded spelling was the only one
    that worked.

    Distinct indices and a subtraction, so a wrong element or a wrong width changes the
    answer: 66 - 67 + 120 - 100 = 19.
    """
    yield ("builtin_string_surface", """
def first_char(text: u8[4]) -> char:
	return text[1]

def wide(text: u8[4]) -> i64:
	return text[2]

def view_char(text: sview[0, 4]) -> char:
	return text[1]

def main() -> i64:
	buf: array[u8, 4] = [65.u8(), 66.u8(), 67.u8(), 68.u8()]
	return first_char(buf).i64() - wide(buf) + view_char("wxyz").i64() - 100
""")




def gen_fixed_array_slice_to_view():
    """`text[1:3]` on a `u8[4]` -- slicing a FIXED ARRAY into a `view[T]`.

    The fat-view slice path handled only darray sources; an array source fell through to a
    guard that declines every container (that guard is load-bearing -- the cstr byte-slice
    path below it byte-GEPs the container header and miscompiles). Unlike a darray there is
    no items pointer to extract: the array IS the storage, so the view points into the
    array's own slot, which is stage0's lowering too.

    The two slice elements are read back with DISTINCT weights (23), so an off-by-one in
    the start offset or a length computed from the wrong end changes the answer.
    """
    yield ("fixed_array_slice_to_view", """
def probe(text: u8[4]) -> i64:
	part: view[u8] = text[1:3]
	return part[0].i64() * 10 + part[1].i64()

def main() -> i64:
	buf: array[u8, 4] = [1.u8(), 2.u8(), 3.u8(), 4.u8()]
	return probe(buf)
""")




def gen_view_iteration():
    """`for x in v:` over a `view[T]`, from both a darray slice and a fixed-array slice.

    A view is a `{ptr data, i64 len}` VALUE, not a header in memory like a darray, so the
    loop emitter's darray branch could not take it and nothing else did. View INDEXING
    worked all along, which is how the gap stayed hidden -- it only shows up when the same
    view is iterated.

    Each loop folds its elements positionally (total*10 + x), so a reversed traversal, an
    off-by-one length, or a dropped element changes the answer: 23 and 23.
    """
    yield ("view_iteration", """
def from_darray(xs: darray[i64]) -> i64:
	part: view[i64] = xs[1:3]
	total: mutable i64 = 0
	for b in part |total|:
		total <- total * 10 + b
	return total

def from_array(text: u8[4]) -> i64:
	part: view[u8] = text[1:3]
	total: mutable i64 = 0
	for b in part |total|:
		total <- total * 10 + b.i64()
	return total

def main() -> i64:
	xs: darray[i64] = [1, 2, 3, 4]
	buf: array[u8, 4] = [1.u8(), 2.u8(), 3.u8(), 4.u8()]
	return from_darray(xs) + from_array(buf)
""")


GENERATORS = [
    gen_darray_as_cstr,
    gen_is_bracketed_alternation,
    gen_is_grouped_alternation,
    gen_extern_error_return_not_an_export,
    gen_unified_else_recovery,
    gen_get_else_raise,
    gen_nullable_extern_ref_get,
    gen_labelled_call_through_fn_alias,
    gen_shadowing_assignment_declaration,
    gen_proof_block_erasure,
    gen_first_query,
    gen_refined_type_alias,
    gen_builtin_string_surface,
    gen_fixed_array_slice_to_view,
    gen_view_iteration,
]
