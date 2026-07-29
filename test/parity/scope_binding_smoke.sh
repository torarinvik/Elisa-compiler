#!/usr/bin/env bash
# Stage1 backend smoke: local SCOPE, `is`-binding SLOTS, and match ALTERNATION arms,
# asserted by exit code.
#
# These are backend gaps the gen3 bootstrap exposed — cases a fixture gate cannot see by
# inspection, because the
# programs compile clean and then return the wrong answer (or segfault), because a load
# reads an alloca that the taken path never stored. Both were found only when gen2 tried
# to compile the compiler, and both are checked DIFFERENTIALLY: stage0 is the oracle, so
# a case that starts passing for the wrong reason still has to agree with stage0.
#
#   1. OR-CHAINED `is` BINDINGS. `e is A(x) or e is B(x)` short-circuits, so only the
#      alternative that matched runs. Giving each alternative its own slot and resolving
#      the body's `x` to the last one declared reads a slot nothing stored. stage0 opens
#      ONE entry-block slot per bound name for the whole condition; stage1 now does too.
#
#   2. SIBLING-BLOCK SHADOWING. A declaration inside a block must not outlive it. The
#      backend scope is a flat append-only list scanned BACKWARDS, so a leftover inner
#      declaration makes a LATER use of the same name resolve to the inner slot — which
#      the later path never stored. This is what killed gen2 on the compiler itself:
#      `emit_statement_loops` declares `int64_type` in the darray-`for` branch and the
#      range-`for` branch below it then allocated with that undominated slot.
#
#   3. MATCH ALTERNATION. `"u8" | "i8" | "bool": 1` — an arm with several literal options.
#      stage1 declined the whole function (which DROPS it, so the link fails), rather than
#      miscompiling it. Every option is compared and the results OR'd.
#
# Every compiled binary runs under a timeout: a scope bug can produce a spinning loop
# rather than a wrong answer, and an untimed gate hangs with it.
RUN() {
    if command -v timeout >/dev/null 2>&1; then timeout 10 "$@"; else "$@"; fi
}
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISACORE_BIN="${ELISACORE_BIN:-$HOME/.elisac/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
RUNTIME_OBJ="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"

[ -x "$ELISACORE_BIN" ] || { echo "scope_binding_smoke SKIP: no stage0 at $ELISACORE_BIN"; exit 0; }
[ -x "$STAGE1" ] || { echo "scope_binding_smoke SKIP: no stage1 seed at $STAGE1"; exit 0; }
[ -f "$RUNTIME_OBJ" ] || { echo "scope_binding_smoke SKIP: no runtime object at $RUNTIME_OBJ"; exit 0; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
pass=0
fail=0

# Compile `$2` with BOTH compilers, run both, and require stage1 == stage0 == `$3`.
differential() {
    local name="$1" src="$2" want="$3"
    printf '%s' "$src" > "$WORK/$name.elisa"

    if ! "$ELISACORE_BIN" -emit obj -o "$WORK/$name.s0.o" "$WORK/$name.elisa" >"$WORK/$name.s0.log" 2>&1; then
        echo "  FAIL $name: stage0 did not compile the case"; sed -n '1,5p' "$WORK/$name.s0.log"; fail=$((fail + 1)); return
    fi
    if ! clang -Wl,-dead_strip -o "$WORK/$name.s0" "$WORK/$name.s0.o" "$RUNTIME_OBJ" >>"$WORK/$name.s0.log" 2>&1; then
        echo "  FAIL $name: stage0 object did not link"; sed -n '1,5p' "$WORK/$name.s0.log"; fail=$((fail + 1)); return
    fi
    RUN "$WORK/$name.s0"; local s0=$?

    if ! ELISA_STAGE1_BIN="$STAGE1" bash "$ROOT/scripts/elisac_stage1.sh" -o "$WORK/$name.s1.o" "$WORK/$name.elisa" >"$WORK/$name.s1.log" 2>&1; then
        echo "  FAIL $name: stage1 did not compile the case"; sed -n '1,5p' "$WORK/$name.s1.log"; fail=$((fail + 1)); return
    fi
    if ! clang -Wl,-dead_strip -o "$WORK/$name.s1" "$WORK/$name.s1.o" "$RUNTIME_OBJ" >>"$WORK/$name.s1.log" 2>&1; then
        echo "  FAIL $name: stage1 object did not link"; sed -n '1,5p' "$WORK/$name.s1.log"; fail=$((fail + 1)); return
    fi
    RUN "$WORK/$name.s1"; local s1=$?

    if [ "$s0" != "$want" ]; then
        echo "  FAIL $name: stage0 (the ORACLE) returned $s0, expected $want — the case itself is wrong"
        fail=$((fail + 1)); return
    fi
    if [ "$s1" != "$s0" ]; then
        echo "  FAIL $name: stage1 returned $s1, stage0 returned $s0"
        fail=$((fail + 1)); return
    fi
    pass=$((pass + 1))
}

# 1. An or-chain whose alternatives bind the SAME name at DIFFERENT payload slots
#    (`inner` is slot 1 in Tag, slot 0 in Wrap), so reading the wrong slot is visible.
#    The FIRST alternative matches, so the second's test never runs.
differential or_bind_first_alternative "$(cat <<'EOF'
module Ast:
    enum Node layout(handle: u32):
        pass

    enum Expr is Node:
        Leaf(value: i64)
        Tag(label: i64, inner: Expr)
        Wrap(inner: Expr)


using Ast


def unwrap(node: Expr) -> i64:
    if node is Expr.Tag(label, inner) or node is Expr.Wrap(inner):
        if inner is Expr.Leaf(value):
            return value
        return -1
    return -2


def build_tag() -> Expr:
    leaf: Expr = Expr.Leaf(7)
    return (Expr.Tag(3, leaf))


def main() -> i64:
    return unwrap(build_tag())
EOF
)" 7

# 2. The SECOND alternative matches — the mirror case, so a fix that simply always reads
#    the first alternative's slot fails here.
differential or_bind_second_alternative "$(cat <<'EOF'
module Ast:
    enum Node layout(handle: u32):
        pass

    enum Expr is Node:
        Leaf(value: i64)
        Tag(label: i64, inner: Expr)
        Wrap(inner: Expr)


using Ast


def unwrap(node: Expr) -> i64:
    if node is Expr.Tag(label, inner) or node is Expr.Wrap(inner):
        if inner is Expr.Leaf(value):
            return value
        return -1
    return -2


def build_wrap() -> Expr:
    leaf: Expr = Expr.Leaf(9)
    return (Expr.Wrap(leaf))


def main() -> i64:
    return unwrap(build_wrap())
EOF
)" 9

# 3. A block-local declaration must not outlive its block: the trailing `return outer`
#    is emitted AFTER the branch's shadowing declaration, so a flat scope resolves it to
#    the branch's slot. main() takes the path that never entered the branch.
differential sibling_block_shadow "$(cat <<'EOF'
def pick(n: i64) -> i64:
    outer: i64 = 33
    if n > 0:
        outer: i64 = 11
        return outer
    return outer


def main() -> i64:
    return pick(0)
EOF
)" 33

# 4. The shadowed branch still has to work when it IS taken.
differential sibling_block_shadow_taken "$(cat <<'EOF'
def pick(n: i64) -> i64:
    outer: i64 = 33
    if n > 0:
        outer: i64 = 11
        return outer
    return outer


def main() -> i64:
    return pick(1)
EOF
)" 11

# 5. A VALUE block's trailing expression is still INSIDE the block, so it must see the
#    block's own locals. This is the case that must NOT be scoped away — getting it wrong
#    makes the compiler decline the function rather than miscompile it.
differential block_value_sees_block_locals "$(cat <<'EOF'
def compute(n: i64) -> i64:
    scale: mutable i64 = n
    total: i64 = |scale|
        doubled: i64 = scale * 2
        doubled + 1
    return total


def main() -> i64:
    return compute(20)
EOF
)" 41

# 6. An alternation arm over an sview scrutinee. `width("i16")` takes the second arm's
#    SECOND option and `width("u8")` the first arm's first, so an implementation that only
#    ever compares one option per arm fails.
differential match_alternation_arms "$(cat <<'EOF'
def width(type_name: sview) -> i64:
    return match type_name:
        "u8" | "i8" | "bool": 1
        "u16" | "i16": 2
        "u32" | "i32": 4
        _: 8


def main() -> i64:
    return width("i16") * 10 + width("u8")
EOF
)" 21

# 7. The alternation fall-through: nothing matches, so the catch-all arm has to win.
differential match_alternation_default "$(cat <<'EOF'
def width(type_name: sview) -> i64:
    return match type_name:
        "u8" | "i8" | "bool": 1
        "u16" | "i16": 2
        _: 8


def main() -> i64:
    return width("f64")
EOF
)" 8

# 8. `ptr != null` / `ptr == null` on a BARE pointer. A `void&` has no {i1,T} optional
#    tag — null IS the absent value — so the test is a plain pointer compare. stage1 only
#    accepted Optional operands here and declined (and therefore DROPPED) every std
#    function guarding a raw pointer, e.g. `if state_bits != null:`.
differential null_compare_bare_pointer "$(cat <<'EOF'
def probe(state_bits: mutable void&) -> i64:
    if state_bits != null:
        return 7
    return 3


def probe_eq(state_bits: mutable void&) -> i64:
    if state_bits == null:
        return 1
    return 9


def main() -> i64:
    can Unsafe.PointerCast, Abort.Panic:
        x: mutable i64 = 5
        bits: mutable void& = (&x).cast[mutable void&]
        return probe(bits) * 10 + probe_eq(bits)
EOF
)" 79

# 9. `xs.items` — the darray header's element-storage POINTER. stage1 typed it Unmodeled
#    (only `.count` was known), so `assert s.indices.items != null` declined and DROPPED
#    every std function guarding its storage that way. Both branches are exercised: an
#    empty darray has no storage, a pushed one does, so a constant-folded answer fails.
differential darray_items_pointer "$(cat <<'EOF'
struct Store:
    indices: mutable darray[usize]


def has_storage(s: Store&) -> bool:
    return s.indices.items != null


def probe(s: Store&) -> i64:
    assert s.indices.items != null
    assert s.indices.count > 0
    return 4


def main() -> i64:
    empty: mutable Store = Store{indices: []}
    filled: mutable Store = Store{indices: []}
    filled.indices.push(1.usize())
    empty_flag: i64 = 1 if has_storage(empty) else 0
    return probe(filled) * 10 + empty_flag
EOF
)" 40

# 10. EARLY-RETURN narrowing. `X return if PATH == null` only falls through when the
#     condition was FALSE, so PATH is non-null below it and may be taken as a plain ref.
#     stage1 recorded narrowing for if-THEN arms only, so the guard shape the std region
#     and fixed-buffer helpers all open with declined — DROPPING the function. Both a
#     present and an absent buffer are passed, so a narrowing that is simply assumed
#     (rather than proven by the guard) gives the wrong answer on the absent one.
differential early_return_guard_narrowing "$(cat <<'EOF'
struct Buf:
    data: mutable u8&?


def first_byte(b: Buf&) -> i64:
    0 return if b.data == null
    p: mutable u8& = b.data
    return p.i64()


def main() -> i64:
    storage: mutable u8[4] = zeroed
    storage[0] <- 9
    b: mutable Buf = Buf{data: &storage[0]}
    empty: mutable Buf = Buf{data: null}
    return first_byte(b) * 10 + first_byte(empty)
EOF
)" 90

# 11. WHILE-condition narrowing. The condition holds INSIDE the body, exactly as in an
#     `if`'s then-arm, so `while cursor != null:` lets the body take `cursor` as a plain
#     ref. stage1 recorded narrowing for `if` only, so the std's region walks — which take
#     the loop-carried optional as a ref on the body's first line — declined. Walking three
#     nodes means a body that ran zero or once still gives the wrong sum.
differential while_condition_narrowing "$(cat <<'EOF'
struct Node:
    value: i64
    next: mutable Node&?


def total(head: mutable Node&?) -> i64:
    sum: mutable i64 = 0
    cursor: mutable Node&? = head
    while cursor != null |sum, cursor|:
        here: mutable Node& = cursor
        sum <- sum + here.value
        cursor <- here.next
    return sum


def main() -> i64:
    c: mutable Node = Node{value: 3, next: null}
    b: mutable Node = Node{value: 2, next: &c}
    a: mutable Node = Node{value: 1, next: &b}
    return total(&a)
EOF
)" 6

# 12. A narrowed OPTIONAL-of-pointer LOCAL reinterpreted by `.cast[T&]` — the std's
#     *_or_panic allocator shape. Gated on the narrowing proof AND on a plain-Ident source:
#     the same unwrap on a struct FIELD read compiles but returns the wrong answer, so that
#     shape is deliberately still declined. Compares the unwrapped address against the one
#     passed in, so an unwrap that yields a wrong-but-non-null pointer fails.
differential narrowed_optional_local_cast "$(cat <<'EOF'
def unwrap_addr(raw: mutable void&?) -> uintptr:
    can Abort.Panic:
        assert raw != null
        trusted Unsafe.PointerCast:
            return raw.cast[void&].cast[u8&].uintptr()


def main() -> i64:
    can Unsafe.PointerCast, Abort.Panic:
        storage: mutable u8[8] = zeroed
        direct: uintptr = (&storage[0]).cast[u8&].uintptr()
        opt: mutable void&? = (&storage[0]).cast[mutable void&]
        return 1 if unwrap_addr(opt) == direct else 0
EOF
)" 1

# 13. `.uintptr()` on a ref is the ADDRESS; `.i64()` is the POINTEE. stage1 dereferenced
#     for BOTH, so `&a[0]` and `&a[4]` reported the same address — a SILENT miscompile with
#     no decline and no link error. Invisible to the self-host: the compiler only ever takes
#     `&xs[0]`, where a dereferenced address still looks plausible. The two bytes are given
#     DIFFERENT values so a fix that swapped the two rules also fails.
differential ref_uintptr_is_address_not_pointee "$(cat <<'EOF'
def main() -> i64:
    can Unsafe.PointerCast, Abort.Panic:
        local: mutable u8[16] = zeroed
        local[0] <- 7
        local[4] <- 9
        p0: u8& = &local[0]
        p4: u8& = &local[4]
        addr_gap: i64 = (p4.uintptr() - p0.uintptr()).usize().i64()
        byte0: i64 = p0.i64()
        byte4: i64 = p4.i64()
        gap_ok: i64 = 1 if addr_gap == 4 else 0
        b0_ok: i64 = 1 if byte0 == 7 else 0
        b4_ok: i64 = 1 if byte4 == 9 else 0
        return gap_ok * 100 + b0_ok * 10 + b4_ok
EOF
)" 111

# 14. The same address rule reached through a struct FIELD's fixed array, which is the shape
#     the std allocators use (`&a.storage[i]`).
differential struct_field_array_element_address "$(cat <<'EOF'
struct Buf:
    storage: mutable u8[16]


def main() -> i64:
    can Unsafe.PointerCast, Abort.Panic:
        b: mutable Buf = zeroed
        f0: uintptr = (&b.storage[0]).cast[u8&].uintptr()
        f4: uintptr = (&b.storage[4]).cast[u8&].uintptr()
        differ: i64 = 1 if f0 != f4 else 0
        gap: i64 = (f4 - f0).usize().i64()
        return differ * 100 + gap
EOF
)" 104

# 15. `for x in CALL()` — iterating a darray a function RETURNED. A call result has no
#     header address, so the loop has to spill the value; stage1 declined instead, and that
#     one construct dropped `Easm.verify_module`, which every easm_* program reaches. Worth
#     26 of the 29 corpus programs stage1 could not build. Sums distinct values so a loop
#     that runs the wrong number of times fails.
differential for_over_call_result "$(cat <<'EOF'
def make() -> darray[i64]:
    can Memory.Allocate, Abort.Panic:
        out: mutable darray[i64] = []
        out.push(1)
        out.push(2)
        out.push(4)
        return out


def total() -> i64:
    can Memory.Allocate, Abort.Panic:
        sum: mutable i64 = 0
        for v in make() |sum|:
            sum <- sum + v
        return sum


def main() -> i64:
    return total()
EOF
)" 7

# 16. `.count` on a CALL RESULT. Same shape as case 15 — a darray read through a value
#     with no header address, needing a spill. It dropped `Easm.parse_layout_module`, the
#     last shared easm symbol, worth 10 more corpus programs.
differential darray_count_on_call_result "$(cat <<'EOF'
def make() -> darray[i64]:
    can Memory.Allocate, Abort.Panic:
        out: mutable darray[i64] = []
        out.push(1)
        out.push(2)
        return out


def main() -> i64:
    can Memory.Allocate, Abort.Panic:
        return make().count.i64()
EOF
)" 2

# 18. The same unwrap through a struct FIELD (`a.data: mutable u8&?`) — the std fixed-buffer
#     allocator shape. Excluded for several rounds on a "10 vs 20" measurement that was
#     itself wrong: that fixture ran through `.uintptr()`, which was returning the pointee.
#     Checks a pointer INSIDE the buffer and one OUTSIDE, so an unwrap yielding a plausible
#     but wrong base fails.
differential narrowed_optional_field_cast "$(cat <<'EOF'
struct Buf:
    data: mutable u8&?
    capacity: mutable usize


def owns(a: Buf&, ptr: void&) -> bool:
    false return if a.data == null

    trusted Unsafe.PointerCast:
        base: uintptr = a.data.cast[u8&].uintptr()
        raw: uintptr = ptr.cast[u8&].uintptr()
        limit: uintptr = base + a.capacity.uintptr()
        return raw >= base and raw < limit


def main() -> i64:
    can Unsafe.PointerCast, Abort.Panic:
        storage: mutable u8[16] = zeroed
        b: mutable Buf = Buf{data: &storage[0], capacity: 16.usize()}
        inside: bool = owns(b, (&storage[4]).cast[void&])
        outside_target: mutable i64 = 0
        outside: bool = owns(b, (&outside_target).cast[void&])
        return 10 if inside and not outside else 20
EOF
)" 10

# 19. A STRING LITERAL passed to a `T&` extern parameter. declare_extern records every
#     provenance-bearing extern param as `void&` — the `&` is known, the referent is not —
#     and the literal path required a `u8` referent, so `snprintf(…, "%llu", …)` declined
#     and took its caller with it. Asserts the formatted LENGTH, so a literal lowered to
#     the wrong pointer gives the wrong count rather than passing silently.
# 19. A STRING LITERAL passed to a `T&` extern parameter. declare_extern records every
#     provenance-bearing extern param as `void&` — the `&` is known, the referent is not —
#     and the literal path required a `u8` referent, so `snprintf(…, "%llu", …)` declined
#     and took its caller down with it. Asserts the formatted LENGTH, so a literal lowered
#     to the wrong pointer gives a wrong count rather than passing silently.
differential string_literal_to_ref_extern_param "$(cat <<'EOF'
extern snprintf(buf: mutable u8&?, bufsize: usize, fmt: u8&, ...) -> int can[Console.Format]


def digits(value: u64) -> i64:
    can Console.Format, Abort.Panic:
        len: int = snprintf(null, 0.usize(), "%llu", value)
        return len.i64()


def main() -> i64:
    return digits(12345.u64())
EOF
)" 5

# 20. A fixed-array GLOBAL whose extent is a named const (`i64[CAP]`), not a literal.
#     The annotation accepted only Expr.IntLit, so the global never registered and every
#     read and write of it declined — which is how the runtime's five trace/cache tapes
#     dropped ~20 functions. Writes TWO distinct slots and sums them, so an extent folded
#     to the wrong bound (or a base that is not the global) gives a wrong total rather
#     than passing on a single lucky slot.
differential array_global_const_extent "$(cat <<'EOF'
const CAP: usize = 8


global mutable tape: i64[CAP] = zeroed


def put(index: usize, value: i64) -> void:
    tape[index] <- value


def get(index: usize) -> i64:
    return tape[index]


def main() -> i64:
    put(0.usize(), 7)
    put((CAP - 1.usize()), 35)
    return get(0.usize()) + get((CAP - 1.usize()))
EOF
)" 42

# 21. `xs.items[i] <- v` — a WRITE through the element-storage pointer of a BORROWED
#     `darray[T]&` (how stores_core writes its region table). A darray is not a Struct, so
#     both chain resolvers bailed and the assignment declined. Writes through `.items` but
#     reads back through ORDINARY indexing, and leaves one slot untouched, so a store to
#     the wrong base is caught rather than confirmed by its own read.
differential darray_items_write "$(cat <<'EOF'
def fill(xs: mutable darray[i64]&, at: usize, value: i64) -> void can[Abort.Panic]:
    assert xs.items != null
    xs.items[at] <- value


def main() -> i64:
    can Memory.Allocate, Abort.Panic:
        xs: mutable darray[i64] = [1, 2, 3]
        fill(&xs, 0.usize(), 10)
        fill(&xs, 2.usize(), 30)
        return xs[0] + xs[1] + xs[2]
EOF
)" 42

# 22. A const extent on an annotation whose HEAD IS NOT A BARE NAME (`heap Entry&?[NB]`).
#     Case 20 covers `i64[CAP]`, which dispatches on the named path; a qualified element
#     type takes the OTHER branch, which still required a literal. The runtime's two string
#     caches are declared exactly this way. Reads slot 3, so an extent folded
#     to the wrong bound traps rather than passing.
differential array_global_const_extent_qualified_head "$(cat <<'EOF'
const NB: usize = 4


struct Entry:
    tag: mutable i64


global mutable cache: heap Entry&?[NB] = zeroed


def peek(bucket: usize) -> i64 can[Abort.Panic]:
    entry: mutable heap Entry&? = cache[bucket]
    if entry == null:
        return 0
    return entry.tag


def main() -> i64:
    can Abort.Panic, Unsafe.PointerCast:
        a: mutable Entry = Entry{tag: 7}
        cache[0] <- (&a).cast[heap Entry&]
        return peek(0.usize()) * 6 + peek(1.usize()) + peek(3.usize())
EOF
)" 42

# 23. `p == q` on two REFERENCES is ADDRESS IDENTITY (`arena == &perm_arena` asks whether
#     this IS the permanent arena). A ref operand otherwise auto-dereferences, so the
#     tempting reading is a pointee compare — this case pins the real one: two refs to
#     DISTINCT variables holding the SAME value must compare unequal, and two refs to the
#     same variable equal. A pointee compare returns 6, an address compare 40.
differential ref_equality_is_address_identity "$(cat <<'EOF'
def same(a: i64&, b: i64&) -> i64:
    if a == b:
        return 1
    return 0


def main() -> i64:
    can Abort.Panic:
        x: mutable i64 = 5
        y: mutable i64 = 5
        return same(&x, &x) * 40 + same(&x, &y) * 6 + 2
EOF
)" 42

# 24. The same rule through a STRUCT ref against the address of a global — the runtime's
#     `register_perm_string_len(...) if arena == &perm_arena` shape, which declined and
#     took int_to_string_into with it. The mutating branch must fire for the global and
#     NOT for the local, so an always-true or always-false compare is caught either way.
differential ref_equality_struct_global "$(cat <<'EOF'
struct Box:
    n: mutable i64


global mutable well_known: Box = zeroed


def note(b: mutable Box&) -> void:
    b.n <- b.n + 1


def touch(b: mutable Box&) -> i64:
    note(b) if b == &well_known
    return b.n


def main() -> i64:
    can Abort.Panic:
        other: mutable Box = Box{n: 5}
        return touch(&well_known) * 10 + touch(&other)
EOF
)" 15

# 25. `s.len` on a CSTR. It reads like a field, but a cstr is a bare pointer — stage0
#     CALLS ctx_strlen. This is why the std's FNV hash `for ch in s[0:s.len]` declined on
#     the BOUND: slicing a cstr and iterating an sview both already worked. Sums the bytes
#     of a 3-char string, so a length off by one (or a pointer read as a length) is caught
#     rather than yielding a plausible total.
differential cstr_len_is_strlen_call "$(cat <<'EOF'
def hash_it(s: cstr) -> u64 can[Abort.Panic]:
    h: mutable u64 = 0.u64()
    for ch in s[0:s.len]:
        h <- h + ch.u64()
    return h


def main() -> i64:
    can Abort.Panic:
        # A + B + C = 65 + 66 + 67 = 198. A length short by one drops 67; a length long
        # by one reads past the terminator. Either way the total moves off 42.
        return hash_it("ABC").i64() - 156
EOF
)" 42

# 26. `==`/`!=` between an OPTIONAL ref and a plain ref — the arena walks its region list
#     with `while current != null and current != region`. stage0 niche-optimizes an
#     optional pointer to a bare pointer and compares directly; stage1 compares the
#     payload pointer out of its {i1, ptr}. Walks to a target that IS in the list (must
#     stop at index 2, not run off the end at 3) and one that is NOT (must reach the end),
#     so a compare stuck at either always-true or always-false is caught.
differential optional_ref_vs_ref_equality "$(cat <<'EOF'
struct Chunk:
    count: mutable i64
    next: mutable heap Chunk&?


def walk(head: mutable heap Chunk&?, target: heap Chunk&) -> i64 can[Abort.Panic]:
    index: mutable i64 = 0
    current: mutable heap Chunk&? = head
    trusted Unsafe.AssumeProgress:
        while current != null and current != target:
            current <- current.next
            index <- index + 1
    return index


def main() -> i64:
    can Abort.Panic, Unsafe.PointerCast:
        c: mutable Chunk = Chunk{count: 3, next: null}
        b: mutable Chunk = Chunk{count: 2, next: (&c).cast[heap Chunk&]}
        a: mutable Chunk = Chunk{count: 1, next: (&b).cast[heap Chunk&]}
        head: mutable heap Chunk&? = (&a).cast[heap Chunk&]
        found: i64 = walk(head, (&c).cast[heap Chunk&])
        outside: mutable Chunk = Chunk{count: 9, next: null}
        missing: i64 = walk(head, (&outside).cast[heap Chunk&])
        return found * 20 + missing - 1
EOF
)" 42

if [ "$fail" -ne 0 ]; then
    echo "scope_binding_smoke FAILED: $pass passed, $fail failed" >&2
    exit 1
fi
echo "scope_binding_smoke OK: $pass/$pass" >&2
