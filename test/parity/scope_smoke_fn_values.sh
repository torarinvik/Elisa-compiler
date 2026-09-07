# Scope smoke — `machine over`, generic function REFERENCES used as values (including the
# phantom-argument and cast-source forms), and FIELD CHAINS through a reference field, read and
# written.


# `machine over INPUT while COND:` — the parser already DESUGARS a machine into a hoisted
# mode enum plus a while/if-chain, so no backend feature was missing. What was missing is that
# the synthesized `Decl.Enum` went into pending_decls only: the backend registers enums from the
# FILE METADATA pools (register_enums_from_metadata never looks at the Decl), so
# `__MachineMode_0.Before` resolved Unmodeled and the untyped mode-var declaration declined —
# dropping every function containing a machine, resolve.elisa's check_function among them.
#
# The arms may only mutate the driven resource, so the finding is reported through a helper
# call, exactly as check_function does with `table.diagnostics`.
differential machine_over_while "$(cat <<'ELISAEOF'
def note(sink: mutable darray[i64]&, value: i64) -> void can[Abort.Panic, Memory.Allocate]:
    sink.push(value)


def count_after(flags: darray[bool], sink: mutable darray[i64]&) -> void can[Abort.Panic, Memory.Allocate]:
    index: mutable usize = 0
    machine over flags[index] while index < flags.count:
        state Before
        state After
        start Before

        Before, true:
            index <- index + 1
            -> After
        Before, _:
            index <- index + 1
            -> Before
        After, true:
            index <- index + 1
            -> After
        After, _:
            note(sink, index.i64())
            index <- index + 1
            -> After


def main() -> i64:
    can Abort.Panic, Memory.Allocate:
        flags: mutable darray[bool] = []
        flags.push(false)
        flags.push(true)
        flags.push(false)
        flags.push(false)
        sink: mutable darray[i64] = []
        count_after(flags, sink)
        total: mutable i64 = sink.count.i64() * 10
        for s in sink |total|:
            total <- total + s
        return total
ELISAEOF
)" 25

# A GENERIC FUNCTION REFERENCE used as a VALUE rather than called. The bare-Ident form already
# passes its raw handle at a `fn` expectation, but with explicit type arguments the bracket
# makes it an Index/IndexN, which fell to the indexing paths and declined. pool_submit1's body
# opens with exactly this shape (`ctx_task_from_raw[R, Pending]`).
differential generic_fn_reference_value "$(cat <<'ELISAEOF'
def wrap[R](v: R) -> R:
    return v


def use(n: i64) -> i64:
    f: fn(i64) -> i64 = wrap[i64]
    return f(n) + 1


def main() -> i64:
    return use(41)
ELISAEOF
)" 42

# The same reference with TWO type arguments, one of which is a PHANTOM type-state that is
# never used in a field. Rejecting an unresolved type argument here would decline this; the
# instantiation is what decides, exactly as instantiate_generic_struct does for `MutexGuard[Held]`.
differential generic_fn_reference_phantom_arg "$(cat <<'ELISAEOF'
struct Slot:
    ignored: i64


struct Box[T, S]:
    handle: mutable uintptr
    state: mutable void&?


def box_from_raw[R, S](raw: Box[void&?, S]) -> Box[R, S]:
    out: Box[R, S] = zeroed
    out.handle <- raw.handle
    out.state <- raw.state
    return out


def make[A, R](arg: A) -> Box[R, Slot]:
    can Abort.Panic, Memory.Allocate:
        from_raw: fn(Box[void&?, Slot]) -> Box[R, Slot] = box_from_raw[R, Slot]
        raw: Box[void&?, Slot] = zeroed
        raw.handle <- 7.uintptr()
        return from_raw(raw)


def main() -> i64:
    can Abort.Panic, Memory.Allocate:
        b: Box[i64, Slot] = make[i64, i64](3)
        return b.handle.i64() + 35
ELISAEOF
)" 42

# Generic type-argument INFERENCE through a fn-typed parameter. `apply_once(dbl, 21)` binds A
# from the second argument, but R appears ONLY inside `fn(A) -> R`, so it stayed unbound and the
# whole call declined. unify_annotation takes a ValueType and a fn-type annotation cannot be
# matched against one, so the actual's signature is resolved where the argument expression is
# still in hand — from the interned Fn pools for a local of fn type, or from the FnTable for a
# bare function name. `ctx_concurrency_work1_new(fn, arg)` infers R this way and no other.
differential generic_infer_through_fn_param "$(cat <<'ELISAEOF'
def apply_once[A, R](f: fn(A) -> R, arg: A) -> R:
    return f(arg)


def dbl(x: i64) -> i64:
    return x * 2


def main() -> i64:
    return apply_once(dbl, 21)
ELISAEOF
)" 42

# `fn.cast[uintptr]` — a FN value reinterpreted as an address, how a callback is stashed in a
# work record (ConcurrencyWorkStart1.fn_bits). A fn value is a pointer at the LLVM level, so it
# is the same ptrtoint the pointer sources take; allowed at the cast site rather than by
# widening type_is_pointer, which also decides the optional NICHE layout.
differential fn_value_cast_to_uintptr "$(cat <<'ELISAEOF'
def dbl(x: i64) -> i64:
    return x * 2


def bits_of[A, R](f: fn(A) -> R) -> uintptr:
    can Unsafe.PointerCast:
        return f.cast[uintptr]


def main() -> i64:
    can Unsafe.PointerCast:
        return 42 if bits_of(dbl) != 0.uintptr() else 7
ELISAEOF
)" 42

# A GENERIC function reference as a CAST SOURCE: `entry[A, R].cast[void&]`, how pool_submit_raw
# is handed a monomorphized C entry point. The bare-Ident function-name source was already
# handled; the bracket makes this an Index/IndexN, which that path cannot see. Instantiating at
# the cast site also DECLARES the instantiation the callback reaches at runtime.
differential generic_fn_reference_cast_source "$(cat <<'ELISAEOF'
def entry[A, R](p: void&) -> i64:
    can Unsafe.PointerCast:
        return 1


def take(p: void&) -> i64:
    can Unsafe.PointerCast:
        return 41 if p.cast[uintptr] != 0.uintptr() else 0


def go[A, R]() -> i64:
    can Unsafe.PointerCast:
        return take(entry[A, R].cast[void&]) + 1


def main() -> i64:
    can Unsafe.PointerCast:
        return go[i64, i64]()
ELISAEOF
)" 42

# `c.at <- c.at.next` where `at` is a `heap Node&?` FIELD — a SILENT MISCOMPILE, not a decline.
# The receiver type was unwrapped to the pointee struct, but struct_chain_address hands back the
# address OF THE SLOT for a field receiver, and that slot holds a POINTER. GEPing it walked the
# OUTER struct: at field position 0 the GEP is a no-op, so this compiled to `c.at <- c.at` and
# the cursor never advanced; with a padding field first it silently read the NEIGHBOURING field
# instead. That is what spun arena_alloc forever in the stage1-built runtime object.
#
# Both layouts are pinned, because the two failures look nothing alike: without `pad` stage1
# returned 49 (loop ran to its bound), with `pad` it returned 40 (one bogus step).
differential field_chain_through_ref_field "$(cat <<'ELISAEOF'
struct Node:
    next: mutable heap Node&?
    value: mutable i64


struct Cursor:
    at: mutable heap Node&?
    steps: mutable i64


def advance(c: mutable Cursor&) -> i64:
    can Abort.Panic:
        trusted Unsafe.AssumeProgress:
            while c.at != null and c.steps < 10:
                c.at <- c.at.next
                c.steps <- c.steps + 1
        return c.steps


def main() -> i64:
    can Abort.Panic, Unsafe.PointerCast:
        n3: mutable Node = Node{next: null, value: 3}
        n2: mutable Node = Node{next: (&n3).cast[heap Node&], value: 2}
        n1: mutable Node = Node{next: (&n2).cast[heap Node&], value: 1}
        c: mutable Cursor = Cursor{at: (&n1).cast[heap Node&], steps: 0}
        return advance(&c) + 39
ELISAEOF
)" 42

# Same walk with the ref field at a NON-ZERO offset, where the bug read the neighbouring field
# rather than degenerating into a no-op.
differential field_chain_through_ref_field_offset "$(cat <<'ELISAEOF'
struct Node:
    pad: mutable i64
    next: mutable heap Node&?
    value: mutable i64


struct Cursor:
    at: mutable heap Node&?
    steps: mutable i64


def advance(c: mutable Cursor&) -> i64:
    can Abort.Panic:
        trusted Unsafe.AssumeProgress:
            while c.at != null and c.steps < 10:
                c.at <- c.at.next
                c.steps <- c.steps + 1
        return c.steps


def main() -> i64:
    can Abort.Panic, Unsafe.PointerCast:
        n3: mutable Node = Node{pad: 0, next: null, value: 3}
        n2: mutable Node = Node{pad: 0, next: (&n3).cast[heap Node&], value: 2}
        n1: mutable Node = Node{pad: 0, next: (&n2).cast[heap Node&], value: 1}
        c: mutable Cursor = Cursor{at: (&n1).cast[heap Node&], steps: 0}
        return advance(&c) + 39
ELISAEOF
)" 42

# The WRITE twin of field_chain_through_ref_field: `c.at.value <- v` stores THROUGH a ref
# field. struct_chain_address hands back the address OF THE SLOT for a field receiver, so the
# store landed in the OUTER struct. This is the one that made the stage1-built runtime object
# corrupt its own Region bookkeeping (`a.end.count <- a.end.count + size` in arena_alloc), and
# it took the gate against that runtime from 66/78 to 78/78 on its own.
differential field_chain_write_through_ref_field "$(cat <<'ELISAEOF'
struct Node:
    next: mutable heap Node&?
    value: mutable i64


struct Holder:
    at: mutable heap Node&?
    seen: mutable i64


def bump(h: mutable Holder&) -> i64:
    can Abort.Panic:
        assert h.at != null
        h.at.value <- h.at.value + 5
        h.seen <- h.seen + 1
        return h.at.value * 10 + h.seen


def main() -> i64:
    can Abort.Panic, Unsafe.PointerCast:
        n: mutable Node = Node{next: null, value: 3}
        h: mutable Holder = Holder{at: (&n).cast[heap Node&], seen: 0}
        r: i64 = bump(&h)
        return r + n.value - 40
ELISAEOF
)" 49

# A semantic-check scope must end with the loop body too. A darray local in an earlier
# loop must not shadow the scalar binder of a later loop with the same name; the old firm
# argument checker left both its local-type and typestate channels flat and rejected this
# valid program before code generation.
differential loop_binder_after_container_local "$(cat <<ELISAEOF
include "$ROOT/elisacore_std/elisacore_runtime.elisa"

def take(value: i64) -> i64:
    return value

def main() -> i64:
    can Memory.Allocate, Abort.Panic:
        total: mutable i64 = 0
        for disks in 3..<5:
            moves: mutable darray[i64] = []
            moves.push(disks)
            total <- total + moves.count.i64()
        for moves in 1..<3:
            total <- total + take(moves)
        return total
ELISAEOF
)" 5
