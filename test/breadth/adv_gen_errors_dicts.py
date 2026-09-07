#!/usr/bin/env python3
"""Adversarial differential generators — packed index-profile commons, named arguments through an `fn` field alias,
payload-carrying error sets, `try` on the right of a binary operator, linear
consume markers, catch arms that return, and the dict entry API

Each generator yields (name, source) pairs; adversarial_differential.py runs them.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))




def gen_packed_index_profile_commons():
    """`@packed_profile(retained_reads)` on an enum that declares COMMON fields.

    This declined for two generations of wrong diagnosis. The visible symptom was a
    SEGFAULT (139 where stage0 answers 28), and it was attributed to stage0 keeping commons
    in a side table while stage1 stores them inline -- so the gate stayed, waiting on the
    side-word runtime entry points.

    That layout difference is real but NOT observable: a store never crosses compilers, and
    stage1's writer, row LLVM type and row STRIDE already agree on the inline arrangement.
    The actual bug was ARITY -- the common-field read emitted the variant-sparse reader's
    three-argument call against this profile's four-parameter
    `ctx_packed_store_read_index_word(arena, index, state, word)`.

    Both a WIDE multi-field variant and a single-field one are read back, and the commons are
    summed alongside the payload, so a common read at the wrong word cannot pass.
    """
    yield ("packed_index_profile_commons", """
@packed_profile(retained_reads)
packed enum Expr:
	common:
		span: int
		cost: int
	Leaf(value: int)
	Wide(first: int, second: int, third: int)
	End

def fold(node: Expr, frozen: Expr.Store[Frozen]) -> int:
	match node in frozen:
		Expr.Wide(first: first, second: second, third: third):
			return node.span + node.cost + first + second + third
		Expr.Leaf(value: value):
			return node.span + node.cost + value
		Expr.End:
			return 0

def main() -> int:
	region scratch(256)
	store: Expr.Store[Local] = Expr.Store(scratch)
	wide: Expr = new[store] Expr.Wide(span: 7, cost: 11, first: 2, second: 3, third: 5)
	leaf: Expr = new[store] Expr.Leaf(span: 1, cost: 2, value: 40)
	frozen: Expr.Store[Frozen] = freeze(move store)
	out: int = fold(wide, frozen) + fold(leaf, frozen)
	destroy scratch
	return out
""")






def gen_named_args_through_fn_field_alias():
    """`box.run(y: 7, x: 30)` where `run: fn(i64, i64) -> i64` was set from a named function.

    A `fn(i64, i64)` type carries no parameter NAMES, so the labels cannot be resolved from the
    field's type alone. stage0 recovers them by resolving the alias back to its target: it
    answers 23 for `sub` called as `(y: 7, x: 30)` — i.e. 30 - 7, reordered, not 7 - 30.

    stage1 handled this for a fn-typed LOCAL and declined for a fn-typed FIELD. Declining was
    the honest default: passing the labelled arguments positionally instead is a SILENT WRONG
    ANSWER, not a crash, which is exactly what this fixture is shaped to catch — `sub` is
    non-commutative, and the two orders give 23 and -23.

    The positional call is generated alongside so a reorder that fires when it must not is
    caught too.
    """
    yield ("named_args_through_fn_field_alias", """
struct CallbackBox:
	run: fn(i64, i64) -> i64

def sub(x: i64, y: i64) -> i64:
	return x - y

def labelled() -> i64:
	box: CallbackBox = CallbackBox{run: sub}
	return box.run(y: 7, x: 30)

def positional() -> i64:
	box: CallbackBox = CallbackBox{run: sub}
	return box.run(30, 7)

def main() -> i64:
	return labelled() * 100 + positional()
""")





def gen_payload_carrying_error_set():
    """`error E:` with a PAYLOAD-carrying variant — stage0 returns a STRUCT, not an i32 code.

    Measured from stage0's IR: a FIELDLESS set returns a bare `i32` (what stage1 always
    emitted), and a set with any payload variant returns
    `%ErrSet__E = { i32 tag, <every variant's fields concatenated> }` — slots are NOT
    overlapped, tags are 1-based (0 = success), and other variants' slots are `undef`.

    Three paths are exercised because they are three DIFFERENT emitters and the first attempt
    got only one of them right:
      - the payload raise (insertvalue tag + each field at `1 + preceding field counts + i`),
      - a FIELDLESS raise in the same set, which must still build the struct (the ABI is per
        SET, not per variant),
      - the SUCCESS return, which kept emitting `ret i32 0` from a function whose signature
        now says struct. LLVM did not reject that: it ran correctly at -O0 and MISCOMPILED at
        -O2, reading the success value back as 0 instead of 3.

    The fieldless set is generated alongside so a change that switches ABI unconditionally is
    caught too.
    """
    yield ("payload_carrying_error_set", """
error BackendError:
	UnsupportedType(span: i64, code: i32)
	Other

def fail(span: i64) -> i64 error[BackendError]:
	raise BackendError.UnsupportedType(span, 7)

def fail_bare() -> i64 error[BackendError]:
	raise BackendError.Other

def ok(v: i64) -> i64 error[BackendError]:
	return v

def recover(span: i64) -> i64:
	return catch fail(span):
		lowered:
			lowered
		error e:
			9

def recover_bare() -> i64:
	return catch fail_bare():
		lowered:
			lowered
		error e:
			40

def recover_ok() -> i64:
	return catch ok(3):
		lowered:
			lowered
		error e:
			99

def main() -> i64:
	return recover(5) * 100 + recover_bare() + recover_ok()
""")
    yield ("fieldless_error_set_keeps_i32", """
error PlainError:
	Missing
	Other

def fail_plain() -> i64 error[PlainError]:
	raise PlainError.Missing

def ok_plain(v: i64) -> i64 error[PlainError]:
	return v

def main() -> i64:
	a: i64 = catch fail_plain():
		lowered:
			lowered
		error e:
			6
	b: i64 = catch ok_plain(11):
		lowered:
			lowered
		error e:
			99
	return a * 100 + b
""")





def gen_try_as_right_binary_operand():
    """`return value + (try f(x))` — a propagating `try` as the RIGHT operand of a binary.

    stage1 already hoisted a try that was the LEFT operand, and a try that WAS the whole
    returned expression, but declined it on the right — which is where stage0's own corpus
    puts it (`value + (try recursive_pair_node_sum(next))`).

    The hoist evaluates the call BEFORE the left operand, so it is allowed only when the
    operator does not short-circuit and the left operand is side-effect-free (an ident or an
    int literal). The `and`/`or` case is generated here too: hoisting out of a short-circuit
    would call the function where the source says it must not, and that program must keep
    answering what stage0 answers either way.

    BOTH paths are exercised — the success path (35) and the propagating error path (1) —
    because a hoist that loses the error branch still returns the right number on success.
    """
    yield ("try_as_right_binary_operand", """
error DiskError:
	Missing

def inner(v: i64) -> i64 error[DiskError]:
	if v == 0:
		raise DiskError.Missing
	return v * 10

def outer(v: i64) -> i64 error[DiskError]:
	return 5 + (try inner(v))

def run(v: i64) -> i64:
	return catch outer(v):
		lowered:
			lowered
		error e:
			1

def main() -> i64:
	return run(3) + run(0)
""")
    yield ("try_operand_short_circuit", """
error DiskError:
	Missing

def flag(v: i64) -> bool error[DiskError]:
	if v == 0:
		raise DiskError.Missing
	return v > 1

def both(v: i64) -> bool error[DiskError]:
	return v > 100 and (try flag(v))

def either(v: i64) -> bool error[DiskError]:
	return v > 100 or (try flag(v))

def check_and(v: i64) -> i64 error[DiskError]:
	ok: bool = try both(v)
	if ok:
		return 7
	return 3

def check_or(v: i64) -> i64 error[DiskError]:
	ok: bool = try either(v)
	if ok:
		return 7
	return 3

def run_and(v: i64) -> i64:
	return catch check_and(v):
		lowered:
			lowered
		error e:
			1

def run_or(v: i64) -> i64:
	return catch check_or(v):
		lowered:
			lowered
		error e:
			1

def main() -> i64:
	return run_and(0) * 1000 + run_and(200) * 100 + run_or(200) * 10 + run_or(0)
""")





def gen_linear_consume_marker_is_a_pointer():
    """`x as ! <- (free(x))` — the linear-consume assignment, and the `T!` return it consumes.

    Two bugs, one shape:

    - `extern_return_is_pointer` scanned the return type for `&` only, so
      `-> heap u8!` was declared returning `i8` where stage0 declares `ptr` (both
      `-> heap u8!` and a bare `-> u8!` lower to `ptr`). The caller then emitted
      `store i8 %call, ptr %buffer` — ONE BYTE written over a pointer slot. That compiles
      clean and corrupts the pointer, which is why this fixture round-trips a real
      `malloc`/`free` rather than a stub: a mangled pointer reaches the allocator.

    - `PLACE as ! <- v` resolved its place through struct_chain_address, which wants a field
      chain, so a bare LOCAL declined and took the enclosing `defer block:` and the whole
      function with it. stage0 lowers the form to a plain store into the local's slot — the
      `as !` is a linear-typing annotation with no codegen of its own.
    """
    yield ("linear_consume_marker_is_a_pointer", """
extern malloc(size: usize) -> mutable heap u8&? can[Memory.Allocate]
@link_name(free)
extern sfree_bytes(ptr: heap u8&) -> heap u8! can[Memory.Release]

def alloc_and_free(n: i64) -> i64:
	can Memory.Allocate, Memory.Release:
		buffer: mutable heap u8&? = null
		defer block:
			if buffer != null:
				buffer as ! <- (sfree_bytes(buffer))

		raw: heap u8&? = malloc(32)
		buffer <- raw
		if buffer == null:
			return -1
		return n + 5

def main() -> i64:
	can Memory.Allocate, Memory.Release:
		return alloc_and_free(30)
""")





def gen_catch_arm_that_returns():
    """A `catch` arm that TERMINATES instead of yielding: `error e: return 1`.

    `arm_value_expression` models an arm body as a single `Stmt.Expr`, so a `return` arm
    answered null and the whole catch declined — in DECLARATION position, where "on error,
    leave the function" is the natural spelling. stage0 accepts it.

    Such an arm stores nothing and never branches to catch.done; the `ret` is the arm block's
    terminator. The returned value is emitted at the enclosing function's return type, which
    the body emitter now records on Runtime because the expression emitters have no statement
    context of their own.

    Two cases, because they take different branches: the enclosing function may be ORDINARY
    (plain `ret`) or itself ERROR-returning (store through the out-param, then return the
    success code). Both success and error paths of the inner call are exercised, and the bool
    case is included because it was the shape that first surfaced this.
    """
    yield ("catch_arm_that_returns", """
error DiskError:
	Missing

def num(v: i64) -> i64 error[DiskError]:
	if v == 0:
		raise DiskError.Missing
	return v * 2

def flag(v: i64) -> bool error[DiskError]:
	if v == 0:
		raise DiskError.Missing
	return v > 1

def run_num(v: i64) -> i64:
	r: i64 = catch num(v):
		lowered:
			lowered
		error e:
			return 1
	return r + 5

def run_flag(v: i64) -> i64:
	r: bool = catch flag(v):
		lowered:
			lowered
		error e:
			return 1
	return 7 if r else 3

def main() -> i64:
	return run_num(3) * 1000 + run_num(0) * 100 + run_flag(5) * 10 + run_flag(0)
""")
    yield ("catch_arm_that_returns_inside_error_fn", """
error DiskError:
	Missing

error OuterError:
	Failed

def num(v: i64) -> i64 error[DiskError]:
	if v == 0:
		raise DiskError.Missing
	return v * 2

def wrap(v: i64) -> i64 error[OuterError]:
	r: i64 = catch num(v):
		lowered:
			lowered
		error e:
			return 41
	return r + 5

def main() -> i64:
	a: i64 = catch wrap(3):
		lowered:
			lowered
		error e:
			90
	b: i64 = catch wrap(0):
		lowered:
			lowered
		error e:
			91
	return a * 100 + b
""")




def gen_dict_entry_api():
    """`d.entry(k)` and its four members — the dict ENTRY api.

    stage0 materialises a three-word `{dict, key, cached}` aggregate (cached being
    `arena_dict_get_mut__T(d, k)`) and extracts from it at the very next instruction, at
    every use. stage1 recognises the CHAIN instead: `.found` is `icmp ne cached, null`,
    `.value` IS cached, and `.insert(v)` / `.get_or_insert(v)` branch on cached and call
    `arena_dict_put__T` / `arena_dict_get_or_insert__T` only on the miss side.

    The program declares its OWN cut-down dict surface, which is the second half of what
    made this decline: those helpers are `[T]` with the key fixed, one type parameter, while
    the dict's type-argument tuple is `(K, T)` — and instantiation requires exactly one
    argument per parameter. They also carry no `_or_panic` wrapper, so the frictionless name
    stage1 prefers resolves to nothing. Both fall back here, matching stage0's mangling
    (`arena_dict_get_or_insert__i64`, the value type alone).

    The helpers are stubs returning null, so every `.found` is false and every `.insert`
    takes the miss branch — which is exactly what makes the arithmetic below discriminating:
    a `.found` that read the wrong word, an insert branch inverted, or a `.value` that failed
    to narrow all move the total.
    """
    yield ("dict_entry_api", """
def arena_dict_get[T](m: dict[cstr[key_shape], T]&, key: cstr[key_shape]) -> T&?:
	return null

def arena_dict_get_mut[T](m: mutable dict[cstr[key_shape], T]&, key: cstr[key_shape]) -> mutable T&?:
	return null

def arena_dict_put[T](a: mutable Arena&, m: mutable dict[cstr[key_shape], T]&, key: cstr[key_shape], value: T) -> mutable T&?:
	return null

def arena_dict_get_or_insert[T](a: mutable Arena&, m: mutable dict[cstr[key_shape], T]&, key: cstr[key_shape], value: T) -> mutable T&?:
	return null

def build(owner: Arena) -> i64:
	alloc: mutable Arena& = (&owner).cast[mutable Arena&]
	total: mutable i64 = 0
	in alloc:
		values: mutable dict[cstr[key_shape], i64] = zeroed
		total <- total + 1 if values.entry("a").found
		total <- total + 2 if not values.entry("b").found
		_ = values.entry("c").insert(7)
		_ = values.entry("d").get_or_insert(9)
		total <- total + 4 if values.entry("e").value is present
		total <- total + 8 if values.get_or_insert("f", 11) is inserted
		slot = values.entry("g").get_or_insert(13)
		total <- total + 16 if slot is bound
		return total
	return total

def main() -> i64:
	owner: Arena = zeroed
	return build(owner)
""")




def gen_payload_enum_labelled_fields():
    """`Shape.Rect(h: 5, w: 2)` — a multi-field payload-enum constructor with LABELS.

    stage1 read the arguments POSITIONALLY and ignored the labels, so out-of-order fields
    were stored swapped. That is a SILENT WRONG ANSWER, not a decline: the constructor
    still emitted, and the program simply computed something else (stage0 59, stage1 47).
    Found by probing the payload-enum analogue of a packed-constructor question, not by the
    corpus -- a wrong answer is invisible to a decline census by construction.

    Fixed by routing the fields through `named_argument_index`, the same reorder the
    fn-typed call paths already do, over the variant's own field names.

    The fixture keeps a DECLARATION-ORDER call beside the reordered one so a fix that
    always permutes is caught too, and weights the four fields by distinct powers of two so
    any single swap moves the total.
    """
    yield ("payload_enum_labelled_fields", """
enum Shape:
	Circle(r: i32)
	Rect(w: i32, h: i32)

def main() -> i64:
	a: Shape = Shape.Rect(w: 3, h: 4)
	b: Shape = Shape.Rect(h: 5, w: 2)
	t: mutable i64 = 0
	if a is Shape.Rect(aw, ah):
		t <- t + aw.i64() * 1 + ah.i64() * 2
	if b is Shape.Rect(bw, bh):
		t <- t + bw.i64() * 4 + bh.i64() * 8
	return t
""")


GENERATORS = [
    gen_packed_index_profile_commons,
    gen_named_args_through_fn_field_alias,
    gen_payload_carrying_error_set,
    gen_try_as_right_binary_operand,
    gen_linear_consume_marker_is_a_pointer,
    gen_catch_arm_that_returns,
    gen_dict_entry_api,
    gen_payload_enum_labelled_fields,
]
