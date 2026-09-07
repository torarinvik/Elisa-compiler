# Scope smoke — GENERIC and HANDLE types: `id[T]` typed handles, shape parameters, a phantom
# parameter no field mentions, inference through a shaped container, and the field-row bug that
# only the FIRST struct to trigger a given instantiation could see.


# 33. `id[T]` TYPED HANDLES. Three gaps in one shape: `id[T]` did not resolve (it erases
#     to a u32 backing, verified against stage0's `define i64 @to_index(i32 %0)`); a
#     `type X = id[T]` ALIAS resolved to the REFERENT struct, because the alias head
#     heuristic keeps the LAST Ident in the target span (`Slot`, not `id`); and `!x` was
#     lowered as boolean NOT when stage0 makes it the ID-UNWRAP operator, rejecting it on
#     anything else ("id unwrap operator requires id[T] operand, got i64"). Unwraps two
#     distinct handles and sums them, so a bool-not lowering cannot land on 42.
differential id_handle_unwrap_and_alias "$(cat <<'EOF'
struct Slot:
    v: mutable i64


type MyId = id[Slot]


def to_index(x: MyId) -> usize:
    return (!x).usize() - 1


def sum_two(a: MyId, b: MyId) -> i64:
    can Abort.Panic:
        return to_index(a).i64() + to_index(b).i64() + 1


def main() -> i64:
    can Abort.Panic, Unsafe.PointerCast:
        raw_a: u32 = 7
        raw_b: u32 = 36
        trusted Unsafe.PointerCast:
            return sum_two(raw_a.cast[MyId], raw_b.cast[MyId])
EOF
)" 42

# 34. SHAPE-parameterized types (`cstr[shape_in]`, `darray[u8, shape_buf]`). A shape is a
#     type-level refinement with NO representation — stage0 lowers both to a plain `ptr`,
#     identical to the unshaped spelling. stage1 failed to resolve the annotation at all,
#     which declined the function at DECLARATION level, with no statement trace to point
#     at: 25 runtime functions went down on this one gap. Uses both spellings and reads
#     real data through each, so an erasure that lost the element type would not answer 42.
differential shape_parameterized_types "$(cat <<'EOF'
def shaped_len(s: cstr[shape_in]) -> i64 can[Abort.Panic]:
    return s.len


def shaped_sum(xs: darray[u8, shape_buf]&) -> i64 can[Abort.Panic]:
    total: mutable i64 = 0
    for b in xs |total|:
        total <- total + b.i64()
    return total


def main() -> i64:
    can Memory.Allocate, Abort.Panic:
        bytes: mutable darray[u8] = [10, 20, 9]
        return shaped_len("abc") + shaped_sum(&bytes)
EOF
)" 42

# 35. A PHANTOM generic parameter: `Guard[Held]` where `Held` is declared NOWHERE and
#     `struct Guard[S]` never mentions `S` in a field. stage0 instantiates it anyway
#     (`%MutexGuard__Held`); stage1 rejected any unresolved type argument up front, which
#     declined every guard-returning lock primitive. An argument the fields DO use still
#     fails — substituting it leaves the field Unmodeled and the existing field check
#     declines, one step later.
differential phantom_generic_parameter "$(cat <<'EOF'
struct Guard[S]:
    handle: mutable void&?


struct Lock:
    handle: mutable void&?


def take(mu: mutable Lock&) -> Guard[Held]:
    g: Guard[Held] = zeroed
    return g


def release(g: Guard[Held]) -> i64:
    return 42


def main() -> i64:
    can Abort.Panic:
        l: mutable Lock = Lock{handle: null}
        return release(take(&l))
EOF
)" 42

# A REF return type followed by a trailing `can[...]` grant: `can` is a plain identifier
# to the lexer, so the postfix `&` used to be reclassified as an infix bitwise AND and the
# whole return annotation resolved to Unmodeled, dropping the function.
differential ref_return_with_can_clause "$(cat <<'EOF'
struct Cell:
    v: mutable i64


def pick(c: Cell&) -> Cell& can[Abort.Panic]:
    return c


def pick_i64(n: i64&) -> i64& can[Abort.Panic]:
    return n


def main() -> i64:
    can Abort.Panic:
        c: mutable Cell = Cell{v: 40}
        k: mutable i64 = 2
        r: Cell& = pick(&c)
        n: i64& = pick_i64(&k)
        return r.v + n
EOF
)" 42

# `fn_name.cast[void&]` takes a FUNCTION's ADDRESS — how the runtime hands a C callback to
# pthread_create/sigaction. A function name is not a value in scope, so the source type came
# back Unmodeled and the enclosing statement declined.
differential cast_function_name_to_pointer "$(cat <<'EOF'
def worker(arg: mutable void&?) -> mutable void&?:
    return arg


def other(arg: mutable void&?) -> mutable void&?:
    return null


def install() -> i64 can[Abort.Panic]:
    p: void& = worker.cast[void&]
    q: void&? = other.cast[void&?]
    same: void& = worker.cast[void&]
    hit: i64 = 40 if p == same and p != null else 0
    return hit + (2 if q != null else 0)


def main() -> i64:
    can Abort.Panic:
        return install()
EOF
)" 42

# A PROPAGATING `try` (no `else`) on a generic error call with EXPLICIT type arguments. The
# bracket makes the callee an Index/IndexN rather than an Ident, so the Ident-only dispatch
# never fired and the inference-based helper had no argument to recover T from. Covers both
# the statement form and the `return try …` value form, plus a void-success instantiation.
differential propagating_try_explicit_generic "$(cat <<'EOF'
error RuntimeError:
    Boom


def gen_id[T](x: T) -> T error[RuntimeError]:
    return x


def gen_void[T](x: T) -> void error[RuntimeError]:
    return


def gen_boom[T](x: T) -> T error[RuntimeError]:
    raise RuntimeError.Boom


def good(x: i64) -> i64 error[RuntimeError]:
    can Abort.Panic:
        try gen_void[i64](x)
        return try gen_id[i64](x)


def bad(x: i64) -> i64 error[RuntimeError]:
    can Abort.Panic:
        return try gen_boom[i64](x)


def main() -> i64:
    can Abort.Panic:
        ok: i64 = try good(40) else 0
        recovered: i64 = try bad(99) else 2
        return ok + recovered
EOF
)" 42

# An OPTIONAL pointer reinterpreted as a DIFFERENT optional pointer. Nullability is
# preserved rather than discarded, so unlike the unwrapping cast this needs no narrowing
# proof — but that only holds if ABSENCE SURVIVES the cast, which is what both arms check
# (a re-tagged non-heap payload would pin `true` and turn null into a present-but-null ref).
differential cast_optional_pointer_to_optional_pointer "$(cat <<'EOF'
struct Node:
    v: mutable i64


struct Holder:
    handle: mutable void&?


def absent_stays_absent() -> i64 can[Abort.Panic]:
    h: mutable Holder = Holder{handle: null}
    n: mutable heap Node&? = h.handle.cast[heap Node&?]
    return 0 if n != null else 20


def present_round_trips(p: mutable void&) -> i64 can[Abort.Panic]:
    h: mutable Holder = Holder{handle: p}
    n: mutable heap Node&? = h.handle.cast[heap Node&?]
    return 0 if n == null else 22


def main() -> i64:
    can Abort.Panic, Unsafe.PointerCast:
        node: mutable Node = Node{v: 1}
        return absent_stays_absent() + present_round_trips((&node).cast[void&])
EOF
)" 42

# Generic-argument INFERENCE through a SHAPED container parameter (`darray[T, shape_in]&`),
# the spelling the std uses on every in-place container helper. The shape argument makes the
# annotation an IndexN, so the single-argument darray/view unify branches never matched and
# T stayed unbound, failing inference for the whole call.
differential infer_generic_through_shaped_container "$(cat <<'EOF'
def shaped_first[T](da: darray[T, shape_in]&, fallback: T) -> T:
    return da[0] if da.count > 0 else fallback


def shaped_count[T](da: mutable darray[T, shape_in]&, bump: T) -> usize:
    return da.count


def main() -> i64:
    can Abort.Panic, Memory.Allocate:
        xs: mutable darray[i64] = [40]
        got: i64 = shaped_first(&xs, 0)
        return got + shaped_count(&xs, 0).i64() + 1
EOF
)" 42

# `.MyId()` — a conversion to an INTEGER-BACKED HANDLE ALIAS (`type X = id[T]`) rather than
# to a builtin scalar. scalar_type_of_name says nothing about it, so the call fell through to
# UFCS, found no function of that name, and declined. The resolution is deliberately limited
# to integer-backed aliases so a same-named function still wins UFCS for every other alias.
differential convert_to_handle_alias "$(cat <<'EOF'
struct Slot:
    v: mutable i64


type MyId = id[Slot]


def __cast__(value: u32) -> MyId:
    return value.cast[MyId]


def make(index: usize) -> MyId:
    return (index + 1).u32().MyId()


def main() -> i64:
    can Abort.Panic:
        first: MyId = make(0.usize())
        last: MyId = make(40.usize())
        return first.u32().i64() + last.u32().i64()
EOF
)" 42

# Resolving a struct member can INSTANTIATE a generic struct, and that instantiation pushes
# its own field rows onto the same table mid-loop. `field_start` was captured BEFORE the
# member loop, so the FIRST struct to trigger a given instantiation had its field_start
# pointing into the instantiation's rows (later structs hit the memo and looked fine, which
# is why this read as a type-specific bug). Checks VALUES of the fields either side of the
# generic one, since a wrong field_start can also resolve to a wrong index rather than decline.
differential struct_field_start_across_generic_instantiation "$(cat <<'EOF'
struct Cell[T]:
    value: mutable T


struct First:
    a: mutable i64
    slot: mutable Cell[i64]
    b: mutable i64


struct Second:
    c: mutable i64
    slot: mutable Cell[i64]


def bump(s: mutable Cell[i64]&) -> i64:
    return s.value


def main() -> i64:
    can Abort.Panic:
        f: mutable First = zeroed
        f.a <- 100
        f.slot.value <- 7
        f.b <- 200
        s: mutable Second = zeroed
        s.c <- 300
        s.slot.value <- 3
        hit: mutable i64 = 0
        hit <- hit + 10 if f.a == 100 and f.b == 200 else hit
        hit <- hit + 10 if s.c == 300 else hit
        return hit + bump(&f.slot) * 2 + bump(&s.slot) * 2 + 2
EOF
)" 42
