#!/usr/bin/env python3
"""Adversarial differential generators — mutable-ref rebinding, ref-returning calls, `lmut` places, the builtins
(`clone`, `copy`, the darray growth methods), shorthand `.Variant` tests,
brace membership and record update

Each generator yields (name, source) pairs; adversarial_differential.py runs them.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from adversarial_harness import ROOT




def gen_mutable_ref_local_rebind():
    """`r: mutable T& = v; r <- v2` -- the LOCAL BINDING itself was declared `mutable`,
    which stage0 treats as REBINDING the reference (assigning a new T&-typed value to
    the binding) rather than writing through it -- a plain non-Ref value on the RHS is
    rejected ("cannot assign int to mutable i64&"). stage1's codegen had no way to tell
    a mutable-declared local from a non-mutable one (Scope tracked name/slot/type only,
    no mutability bit at all) and performed write-through unconditionally for ANY
    Ref-typed `<-` target -- a genuine PERMISSIVE divergence (stage1 silently ACCEPTED
    and ran `ref <- 5` on a `mutable i64&` local, writing 5 through instead of
    rejecting), confirmed to predate this entire session via a throwaway worktree.

    Fixed by adding Scope.local_is_mutable, a bit set ONLY at the one VarDecl shape that
    can spell `mutable` on a Ref-typed annotation at all (type_contains_token already
    existed in the backend for exactly this check); every other local stays at the
    pushed default `false`, so the pre-existing write-through behavior for a
    non-mutable-declared Ref local (the overwhelmingly common case) is unchanged by
    construction. See defer-function-cleanup-scope-gap and mutable-ref-local-rebind-gap
    in the memory notes for how this was found (interaction-axis testing) and the
    corrected-vs-original write-through-ref-gap record.
    """
    yield ("mutable_ref_local_rebind_rejects_plain_value", """
global mutable g: mutable i64 = 100

def main() -> i64:
    ref: mutable i64& = &g
    ref <- 5
    return g
""")
    yield ("mutable_ref_local_rebind_via_call_result_rejects_plain_value", """
global mutable g: i64 = 42

def get_ref() -> mutable i64&:
    return &g

def main() -> i64:
    r: mutable i64& = get_ref()
    r <- 99
    return g
""")
    yield ("mutable_ref_local_rebind_accepts_new_reference", """
global mutable g1: mutable i64 = 1
global mutable g2: mutable i64 = 2

def main() -> i64:
    r: mutable i64& = &g1
    r <- &g2
    return g1 + g2
""")




def gen_ref_returning_call_deref():
    """A function declared `-> T&` whose call result lands in a VALUE context (`x: T =
    f()`, not `x: T& = f()`) must be DEREFERENCED — storing the raw pointer's bit pattern
    into a T-typed slot is a silent WRONG ANSWER, not a decline, and was invisible to
    self-hosting (the compiler's own source apparently never triggers this exact shape).
    """
    yield ("ref_returning_call_deref_global", """
global mutable g: i64 = 42

def get_ref() -> i64&:
    return &g

def main() -> i64:
    v1: i64 = get_ref()
    return v1
""")
    yield ("ref_returning_call_deref_struct_field", """
struct Pair:
    a: i64
    b: i64

def store_get(s: Pair&, h: bool) -> i64&:
    return &s.a if h else &s.b

def main() -> i64:
    p: Pair = Pair{a: 10, b: 20}
    v1: i64 = store_get(p, true)
    v2: i64 = store_get(p, false)
    return v1 * 1000 + v2
""")
    yield ("ref_returning_call_still_works_as_ref", """
global mutable g: i64 = 42

def get_ref() -> i64&:
    return &g

def main() -> i64:
    r: i64& = get_ref()
    v: i64 = r
    return v
""")
    yield ("ref_returning_call_struct_pointee_still_declines", """
struct Pair:
    a: i64
    b: i64

global mutable g: Pair = Pair{a: 10, b: 20}

def get_ref() -> Pair&:
    return &g

def main() -> i64:
    v: Pair = get_ref()
    return v.a
""")
    yield ("ref_returning_call_as_argument", """
global mutable g: i64 = 42

def get_ref() -> i64&:
    return &g

def show(v: i64) -> i64:
    return v * 2

def main() -> i64:
    return show(get_ref())
""")
    yield ("ref_returning_call_in_arithmetic", """
global mutable g: i64 = 42

def get_ref() -> i64&:
    return &g

def main() -> i64:
    return get_ref() + 1
""")




def gen_lmut_place_required():
    """`lmut T` parameters need a mutable PLACE, not a value — stage0 enforces this
    (docs/120 §10) and stage1 was silently missing two shapes of it, both PERMISSIVE gaps
    (stage0 rejects, stage1 built clean). Every program below must FAIL to build under BOTH
    compilers; a stage1 accept here is exactly the bug.

    1. `DiagnosticKind.LmutMutationNotReassignment` (check_lmut_mutation_reassignment.elisa)
       carried severity 0 in semantic_api_severity.elisa. The driver only exits 1 on
       severity-1 findings (`continue if Semantic::diagnostic_severity(diagnostic) != 1`,
       src/driver/elisac.elisa), so this diagnostic — though computed correctly — never
       blocked a build. A bare statement call that threads an `lmut` struct parameter
       without a reassignment (`bump(c)` instead of `c <- bump(c)`) compiled clean.
    2. check_lmut_value_arg.elisa's place-tracking reused the shared `is_primitive_type_name`
       helper, which folds `sview`/`cstr`/`dstr` in with the true scalars — correct for ITS
       OTHER callers (e.g. `.sview()`/`.cstr()` are real builtin conversion method names) but
       wrong here: those three spellings are STRUCTS, and stage0 requires a mutable place for
       an `lmut sview`/`lmut cstr`/`lmut dstr` parameter exactly like any user struct
       ("argument 1 to f expects mutable sview&, got sview"). A by-value sview/cstr/dstr
       local passed to such a parameter was never flagged.
    """
    yield ("lmut_mutation_bare_call_not_reassignment", """
struct Counter:
    n: i64

def bump(c: lmut Counter) -> void:
    pass

def main() -> i64:
    c: mutable Counter = Counter{n: 1}
    bump(c)
    return c.n
""")
    yield ("lmut_value_arg_sview_needs_place", """
def bump(s: lmut sview) -> void:
    pass

def main() -> i64:
    x: sview = "hi"
    bump(x)
    return 0
""")
    yield ("lmut_value_arg_cstr_needs_place", """
def bump(s: lmut cstr) -> void:
    pass

def main() -> i64:
    x: cstr = "hi"
    bump(x)
    return 0
""")
    yield ("lmut_value_arg_dstr_needs_place", """
def bump(s: lmut dstr) -> void:
    pass

def main() -> i64:
    x: dstr = "hi"
    bump(x)
    return 0
""")




def gen_flags_const_enum_sview():
    """`Flags[T]` requires T to be a const enum (check_flags_const_enum.elisa). Its own
    `flags_is_primitive` helper lists every definitely-not-a-const-enum spelling to reject
    (`Flags[i64]`, `Flags[bool]`, ...) and explicitly includes `cstr`/`dstr` — but not
    `sview`, even though sview is exactly the same kind of builtin non-const-enum type.
    stage0 rejects `Flags[sview]` with "Flags[T] expects a const enum type argument, got
    sview"; stage1 silently accepted it (a PERMISSIVE gap) until sview was added alongside
    cstr/dstr in the primitive list.
    """
    yield ("flags_const_enum_sview_rejected", f"""
include "{ROOT}/elisacore_std/collections.elisa"

def f(x: Flags[sview]&) -> bool:
    return true

def main() -> i64:
    return 0
""")




def gen_char_literal_never_fits_sview():
    """`literal_never_fits` (resolve_types.elisa) is the oracle-verified impossible-pair
    matrix deciding whether a literal can NEVER initialize a declared primitive type. Its
    "string"/"int"/"bool" branches all route the string family through the shared
    `is_string_type_name` helper (cstr/dstr/sview together), but the "char" branch
    hand-enumerated only `cstr`/`dstr` and dropped `sview` — even though a char literal
    can no more initialize an sview than a cstr/dstr. stage0 rejects `x: sview = 'a'`
    ("variable x expects sview, got char"); stage1 silently accepted it (PERMISSIVE gap)
    until the char branch was switched to `is_string_type_name` like its siblings.
    """
    yield ("char_literal_into_sview_rejected", """
def main() -> i64:
    x: sview = 'a'
    return 0
""")




def gen_clone_builtin_move_wrapped_source():
    """`clone[darray[T]](src)` where `src` is an `sview` parameter and T != u8 cannot widen
    a byte view into a T-element container (check_clone_builtin.elisa's CloneElemMismatch).
    The check's own source-argument matcher only recognised a BARE `Expr.Ident` — a
    `move src`-wrapped argument (a very ordinary way to pass an owned/linear-tracked
    parameter) skipped the match entirely. In a `return`-position call the separate
    CloneOwnerRequired check happens to also fire and mask this (both compilers still
    reject), but bound to a plain local — the shape here — nothing else catches it: stage0
    rejects ("clone cannot clone sview into darray[u32] in v1"), stage1 silently accepted
    the `move`-wrapped form (a PERMISSIVE gap) until the source-argument matcher unwrapped
    `Paren`/`Move` first.
    """
    yield ("clone_move_wrapped_sview_into_darray_u32", """
def f(src: sview) -> i64:
    x: darray[u32] = clone[darray[u32]](move src)
    return 0

def main() -> i64:
    return 0
""")




def gen_shorthand_member_is():
    """`x is .Variant` -- the leading-dot enum shorthand, whose enum comes from the
    expected type. The parser gives it its own node (Expr.ShorthandMember) while every
    `is` variant-test path in the backend matches Expr.Field, so the shorthand fell
    through all of them and DECLINED: the form was simply unimplemented in codegen
    (`grep ShorthandMember src/backend` found nothing).

    stage0 permits the shorthand for CONST enums only -- on a payload enum it errors
    `shorthand member ".Circle" requires an expected const enum type`. Both spellings
    are pinned here, including `is not` (which the parser desugars to
    Unary(Not, <is>)), and a const enum whose VALUES differ from its ordinals, since
    the compare is against the member's value.

    See shorthand-member-const-enum-only.md -- notably that stage0's `-emit obj`
    ACCEPTS the payload-enum form its `-emit llvm` rejects, so obj-exit-0 alone is not
    proof a form is legal.
    """
    yield ("shorthand_member_is_const_enum", """
const enum Tok of i32:
	IDENT = 7
	NUMBER = 9

def classify(kind: Tok) -> i64:
	return 1 if kind is .IDENT else 0

def negate(kind: Tok) -> i64:
	return 10 if kind is not .IDENT else 20

def main() -> i64:
	return classify(Tok.IDENT) + classify(Tok.NUMBER) * 2 + negate(Tok.NUMBER) + negate(Tok.IDENT)
""")




def gen_builtin_view_type_name():
    """`size_of(view[i32])` -- the builtin container type name `view` used where the
    resolver walks a TYPE as a value expression. seed_builtins registered `darray`,
    `dict`, `set` and `array` but not `view`, so it alone reported `undefined
    identifier 'view'` while its siblings resolved.

    Pinned alongside a struct `size_of` so the numeric answers (not just acceptance)
    are compared. Note the argument is strictly a TYPE: stage0 rejects both
    `size_of(NoSuchType)` ("unknown type") and `size_of(x)` for a value `x`, so this
    could NOT be fixed by skipping the argument the way offset_of's field selector is
    skipped -- that would have accepted an undefined type name and gone PERMISSIVE.
    """
    yield ("builtin_view_type_name_size_of", """
struct Padded:
	tag: i8
	value: i32

def padded_size() -> usize:
	return size_of(Padded)

def view_size() -> usize:
	return size_of(view[i32])

def main() -> i64:
	return padded_size().i64() * 100 + view_size().i64()
""")




def gen_void_return_call():
    """`return helper()` where helper is `-> void`, from a `-> void` function --
    returning a VOID-typed call rather than falling off the end.

    stage1 CRASHED on this (SIGTRAP, no diagnostic). The operand is void-typed, so
    LLVMBuildRet emitted `ret void <badref>` -- malformed IR that slipped past the
    return-type identity check (void == void, so the types "match") and then trapped
    LLVM during object emission. The bare-`return` path was always correct; only the
    return-WITH-VALUE path was wrong.

    Pinned through a mutable ref so the relayed call's SIDE EFFECT is observed twice,
    not merely that the program compiles.
    """
    yield ("void_return_call_relay", """
def bump(slot: mutable i64&) -> void:
	slot <- slot + 7
	return

def relay(slot: mutable i64&) -> void:
	return bump(slot)

def main() -> i64:
	total: mutable i64 = 0
	relay(&total)
	relay(&total)
	return total
""")


def gen_copy_array_builtin():
    """`copy[array[T, N]](src)` -- a value copy into a fixed-size array. The backend had
    NO handling of `copy` whatsoever, so every use declined.

    A fixed array is an LLVM first-class aggregate VALUE, so the copy is just the value:
    no buffer to duplicate, nothing to alias. The dangerous shape (a runtime-length
    source, where a shallow copy WOULD alias) cannot reach codegen -- check_copy_builtin
    rejects a darray source and any non-array[T, N] target first.

    The fixture MUTATES the duplicate and reads BOTH back, so aliasing would change the
    answer rather than merely compiling: a true copy gives 1*100 + 99, an aliased one
    would give 99*100 + 99.
    """
    yield ("copy_array_builtin_is_value_copy", """
def dup(src: array[u8, 4]) -> array[u8, 4]:
	return copy[array[u8, 4]](src)

def main() -> i64:
	original: mutable array[u8, 4] = [1, 2, 3, 4]
	duplicate: mutable array[u8, 4] = dup(original)
	duplicate[0] <- 99
	return original[0].i64() * 100 + duplicate[0].i64()
""")




def gen_discarded_darray_growth_methods():
    """`_ = xs.resize(n)` / `.truncate(n)` / `.clear()`. These return the receiver for
    chaining, so they are DISCARDED via `_ =` rather than written as bare statements.

    The STATEMENT emitter lowers all three, but emit_expression models none of them, so
    the discarded spelling declined while the bare-statement spelling compiled --
    `reserve` was the only one with a dedicated discard path. Fixed by delegating the
    discard to the statement emitter (a discarded call IS a statement expression).

    Note the discard of a METHOD call folds to Stmt.Assign, not Stmt.VarDecl: an
    equivalent guard added to the VarDecl discard path turned out to be dead code and was
    dropped. Both discard sites exist, so check which one a given spelling reaches.

    Each case returns the resulting COUNT, so a lowering that compiled but resized wrongly
    would still fail.
    """
    for method, expected in (("resize(5.usize())", 5), ("truncate(1.usize())", 1), ("clear()", 0)):
        label = method.split("(")[0]
        yield (f"discarded_darray_{label}", f"""
def main() -> i64:
	xs: mutable darray[i64] = []
	xs.push(7)
	xs.push(8)
	xs.push(9)
	_ = xs.{method}
	return xs.count.i64()
""")




def gen_brace_membership_ranges():
    """`x in {1..=3, 5..<7}` -- a brace membership set containing RANGE candidates.

    Membership lowers to an OR-chain of ICmp EQ over the candidates. A range is not a
    scalar, so emit_expression declined it and killed the ENTIRE chain: every membership
    set containing a range declined, while the all-scalar form (`x in {1, 2, 3}`)
    compiled. Ranges now lower as `x >= lo and x <(=) hi`, synthesized as expressions and
    routed back through emit_expression so the signed-vs-unsigned compare choice is not
    duplicated.

    The fixture folds membership over probes 0..=7 into a BITMASK, so inclusive-vs-
    exclusive boundary errors change the answer rather than merely compiling: `..=`
    must include 3 and `..<` must exclude 7. Expected 118 (0b01110110), which fits in a
    byte so exit-status truncation cannot mask a mismatch.
    """
    yield ("brace_membership_ranges", """
def keep(value: i64) -> bool:
	return value in {1..=3, 5..<7}

def main() -> i64:
	total: mutable i64 = 0
	for probe in 0..=7:
		total <- total * 2 + (1 if keep(probe) else 0)
	return total
""")
    # Leading-dot shorthand CANDIDATES (`kind in {.IF, .LET}`). Same OR-chain, but
    # emit_expression knows only the qualified `Enum.Variant` spelling, so each
    # shorthand candidate declined. Resolved through the same helper the `is` path
    # uses. Expected 6 (0b110): IF and LET are members, IDENT is not.
    #
    # NOT pinned: `kind in {.IF..=IDENT}` -- a range whose UPPER bound is a BARE
    # unqualified enum member rather than a shorthand. That needs bare-ident-in-enum
    # -context resolution, which is a separate gap and still declines.
    yield ("brace_membership_shorthand_members", """
const enum TokenKind of u32:
	IF
	LET
	IDENT

def keep(kind: TokenKind) -> bool:
	return kind in {.IF, .LET}

def main() -> i64:
	total: mutable i64 = 0
	total <- total * 2 + (1 if keep(TokenKind.IF) else 0)
	total <- total * 2 + (1 if keep(TokenKind.LET) else 0)
	total <- total * 2 + (1 if keep(TokenKind.IDENT) else 0)
	return total
""")




def gen_checked_index_else():
    """`get xs[i] else FALLBACK` -- a BOUNDS-CHECKED darray index.

    This is NOT the Refinement node the other `get ... else` forms use: the SUBSCRIPT
    postfix consumes the `else` itself (accept_subscript_else), producing
    `Binary(Index(xs, i), TokenKind.Else, FALLBACK)`, which `get` then wraps in a GetElse
    with an EMPTY recovery list. `grep TokenKind.Else src/backend` found nothing at all --
    the checked-index operator was simply unimplemented in codegen.

    The fixture reads two IN-RANGE indices and one PAST THE END, weighting them by powers
    of 3 so every position contributes distinctly: 1*27 + 2*9 + 7 = 52, small enough that
    exit-status truncation cannot mask a mismatch. A lowering that ignored the bounds test
    would read past the end instead of yielding 7.
    """
    yield ("checked_index_else_darray", """
def at(xs: darray[i64]&, i: usize) -> i64:
	return get xs[i] else 7

def main() -> i64:
	xs: mutable darray[i64] = []
	xs.push(1)
	xs.push(2)
	return at(xs, 0.usize()) * 27 + at(xs, 1.usize()) * 9 + at(xs, 2.usize())
""")




def gen_record_update():
    """`base{field = v}` -- a RECORD UPDATE: the base value with named fields overridden
    and every other field COPIED. `grep RecordUpdate src/backend` found nothing, so the
    form was unimplemented in codegen (and the typer had no case either, so an annotated
    destination could not infer it).

    The fixture updates the MIDDLE field of three and reads all three back, so the
    copy-the-rest half is what the answer depends on: 1*100 + 9*10 + 3 = 193. A lowering
    that zeroed untouched fields instead of copying them would give 90. Fits in a byte,
    so exit-status truncation cannot mask a mismatch.
    """
    yield ("record_update_copies_untouched_fields", """
struct Acc:
	first: i64
	second: i64
	third: i64

def bump(base: Acc, v: i64) -> Acc:
	return base{second = v}

def main() -> i64:
	start: Acc = Acc{first: 1, second: 2, third: 3}
	updated: Acc = bump(start, 9)
	return updated.first * 100 + updated.second * 10 + updated.third
""")


GENERATORS = [
    gen_mutable_ref_local_rebind,
    gen_ref_returning_call_deref,
    gen_lmut_place_required,
    gen_flags_const_enum_sview,
    gen_char_literal_never_fits_sview,
    gen_clone_builtin_move_wrapped_source,
    gen_shorthand_member_is,
    gen_builtin_view_type_name,
    gen_void_return_call,
    gen_copy_array_builtin,
    gen_discarded_darray_growth_methods,
    gen_brace_membership_ranges,
    gen_checked_index_else,
    gen_record_update,
]
