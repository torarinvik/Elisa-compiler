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

# 27. `p.cast[uintptr]` where p is an OPTIONAL pointer — the string-length cache compares
#     `entry.ptr.cast[uintptr] == ptr.cast[uintptr]`. Only a plain pointer source was
#     accepted. stage0 holds an optional pointer as a bare pointer, so its ptrtoint reads
#     the same value stage1 gets from payload field 1. Checked BOTH ways: the address
#     taken through the optional must equal the one taken directly (so extracting the tag
#     field, or the whole aggregate, fails), and an ABSENT optional must convert to 0.
differential optional_pointer_uintptr_cast "$(cat <<'EOF'
def addr_opt(p: u8&?) -> uintptr:
    trusted Unsafe.PointerCast:
        return p.cast[uintptr]


def main() -> i64:
    can Abort.Panic, Unsafe.PointerCast:
        storage: mutable u8[8] = zeroed
        direct: uintptr = (&storage[4]).uintptr()
        via_opt: uintptr = addr_opt(&storage[4])
        absent: uintptr = addr_opt(null)
        total: mutable i64 = 0
        if direct == via_opt:
            total <- total + 40
        if absent == 0.uintptr():
            total <- total + 2
        return total
EOF
)" 42

# 28. Field access through a PLAIN (non-heap) optional ref. The optional field paths were
#     scoped to `heap T&?` for want of a stage0 precedent; stores_rows supplies one with
#     `&variant_rows.rows` on a `PackedStoreVariantRows&?`, which stage0 compiles. Reads
#     the SECOND field both by value and by address, and weights it so a chain that lands
#     on the FIRST field (100) answers 700 rather than 42.
differential field_through_plain_optional_ref "$(cat <<'EOF'
struct Pair:
    first: mutable i64
    second: mutable i64


def read_second(p: Pair&?) -> i64 can[Abort.Panic]:
    assert p != null
    return p.second


def second_addr(p: Pair&?) -> i64 can[Abort.Panic]:
    assert p != null
    slot: i64& = &p.second
    return slot


def main() -> i64:
    can Abort.Panic:
        pair: mutable Pair = Pair{first: 100, second: 6}
        return read_second(&pair) * 6 + second_addr(&pair)
EOF
)" 42

# 29. The two MEANINGS of `<-` on a `T&?` variable, in one fixture, because confusing them
#     miscompiles silently in both directions. `out_value <- 30` writes THROUGH the payload
#     pointer (an out-parameter); `r <- r.next` REBINDS the cursor and the list walk
#     depends on it. stage0 disambiguates on the VALUE type: pointee-typed writes through,
#     pointer-typed rebinds. Write-through contributes 30, the walk 12, the status 0 — a
#     rebind treated as a write-through loses the walk, and the reverse loses the 30.
differential optional_out_param_write_vs_rebind "$(cat <<'EOF'
struct Node:
    v: mutable i64
    next: mutable heap Node&?


def fill_out(out_value: mutable i64&?) -> int can[Abort.Panic]:
    1 return if out_value == null
    out_value <- 30
    return 0


def count_from(head: mutable heap Node&?) -> i64 can[Abort.Panic]:
    n: mutable i64 = 0
    r: mutable heap Node&? = head
    trusted Unsafe.AssumeProgress:
        while r != null:
            n <- n + r.v
            r <- r.next
    return n


def main() -> i64:
    can Abort.Panic, Unsafe.PointerCast:
        slot: mutable i64 = 0
        rc: int = fill_out(&slot)
        b: mutable Node = Node{v: 4, next: null}
        a: mutable Node = Node{v: 8, next: (&b).cast[heap Node&]}
        walked: i64 = count_from((&a).cast[heap Node&])
        return slot + rc.i64() + walked
EOF
)" 42

# 30. Building a `dstr` (which IS a `darray[u8]`) BY HAND, as ctx_fstr_alloc does: install
#     a buffer with the `as &` reborrow spelling on a PLAIN pointer field (only the
#     optional form was handled), then set and read back the two header fields. count and
#     capacity are weighted differently so swapping header indices 1 and 2 answers 69, and
#     the byte written through the INSTALLED buffer must land in the original storage, so
#     a no-op install is caught too.
differential darray_header_build_by_hand "$(cat <<'EOF'
def build() -> i64 can[Memory.Allocate, Abort.Panic, Unsafe.PointerCast]:
    out: mutable dstr = zeroed
    storage: mutable u8[8] = zeroed
    buf: mutable u8& = &storage[0]
    out.items as & <- buf
    out.count <- 5.usize()
    out.capacity <- 32.usize()
    out.items[0] <- 7.u8()
    return out.count.i64() * 2 + out.capacity.i64() + storage[0].i64() - 7


def main() -> i64:
    can Memory.Allocate, Abort.Panic, Unsafe.PointerCast:
        return build()
EOF
)" 42

# 31. A TERNARY narrows its arms, exactly like a statement `if`. The concurrency pool
#     pushes with `node.next <- null if state.workers == null else state.workers.cast[...]`;
#     the else arm could not see that the `== null` test had FAILED, so the cast had no
#     narrowing proof and declined. stage0 rejects that cast unguarded ("invalid cast from
#     mutable void&? to heap Node&"), so the proof is genuinely required. The first push
#     takes the THEN arm and the second the ELSE arm, which must link to the first node —
#     a broken else arm loses 12 and answers 30.
differential ternary_arm_narrowing "$(cat <<'EOF'
struct Node:
    v: mutable i64
    next: mutable heap Node&?


struct State:
    workers: mutable void&?


def push(state: mutable State&, node: mutable heap Node&) -> void can[Abort.Panic, Unsafe.PointerCast]:
    trusted Unsafe.PointerCast:
        node.next <- null if state.workers == null else state.workers.cast[heap Node&]
        state.workers <- node.cast[void&]


def total(state: State&) -> i64 can[Abort.Panic, Unsafe.PointerCast]:
    sum: mutable i64 = 0
    trusted Unsafe.PointerCast, Unsafe.AssumeProgress:
        cursor: mutable heap Node&? = null if state.workers == null else state.workers.cast[heap Node&]
        while cursor != null:
            sum <- sum + cursor.v
            cursor <- cursor.next
    return sum


def main() -> i64:
    can Abort.Panic, Unsafe.PointerCast:
        st: mutable State = State{workers: null}
        a: mutable Node = Node{v: 12, next: null}
        b: mutable Node = Node{v: 30, next: null}
        push(&st, (&a).cast[heap Node&])
        push(&st, (&b).cast[heap Node&])
        return total(&st)
EOF
)" 42

# 32. `.items[i] <- v` where the ELEMENT is an OPTIONAL ref (`darray[heap Node&?]`, what
#     stores_core's region table holds). Reverted once: stage1 then gave an optional ref a
#     16-byte `{i1, ptr}` while the stage0-compiled runtime strides such a darray by 8, so
#     the write corrupted memory — and this very fixture PASSED anyway, because stage1 did
#     both the store and the load, making a wrong stride self-consistent. The stride is now
#     the pointer's, so the case finally tests what it claims. Stores at NON-ADJACENT slots
#     and reads both back.
differential darray_items_write_optional_element "$(cat <<'EOF'
struct Node:
    tag: mutable i64


def fill(xs: mutable darray[heap Node&?]&, at: usize, n: heap Node&?) -> void can[Abort.Panic]:
    assert xs.items != null
    xs.items[at] <- n


def main() -> i64:
    can Memory.Allocate, Abort.Panic, Unsafe.PointerCast:
        a: mutable Node = Node{tag: 7}
        b: mutable Node = Node{tag: 35}
        xs: mutable darray[heap Node&?] = [null, null, null]
        fill(&xs, 0.usize(), (&a).cast[heap Node&])
        fill(&xs, 2.usize(), (&b).cast[heap Node&])
        total: mutable i64 = 0
        if xs[0] is first:
            total <- total + first.tag
        if xs[2] is second:
            total <- total + second.tag
        return total
EOF
)" 42

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

# `sb.extend([0.u8()])` — a LITERAL source (no address to take, so both existing loop paths
# declined on darray_address_of_expr) and `extend` in VALUE position (`return sb.extend(…)`,
# which mutates in place and yields the target). Checks the appended BYTES and the resulting
# count, so a push that drops or duplicates an element fails rather than merely compiling.
differential extend_with_literal_source "$(cat <<'EOF'
def add_two(sb: mutable darray[u8]&) -> void:
    can Memory.Allocate, Abort.Panic:
        sb.extend([7.u8(), 9.u8()])


def add_via_arena(a: mutable Arena&, sb: mutable darray[u8, shape_in]&) -> mutable darray[u8, shape_out]&:
    can Memory.Allocate, Abort.Panic:
        in a:
            return sb.extend([5.u8()])


def main() -> i64:
    can Memory.Allocate, Abort.Panic:
        xs: mutable darray[u8] = [1.u8()]
        add_two(&xs)
        total: mutable i64 = 0
        for b in xs |total|:
            total <- total + b.i64()
        return total + xs.count.i64() * 8 + 1
EOF
)" 42

# A fn TYPE reached three ways that all previously failed, because looks_like_lambda only
# treats `fn(A) -> R` (arrow, no `:`/`=>` body) as a TYPE inside a type annotation, and neither
# a `type X = …` RHS nor a `[...]` reinterpret bracket marked itself as one — so both parsed as
# a CALL to a function named `fn` plus a trailing binary `->`, and no Expr.Lambda ever reached
# annotation_value_type. Covers the alias spelling, `cast` to a fn type, and `call_as`.
# `call_as` is checked by RESULT, so a wrong indirect callee or arity fails rather than compiles.
differential fn_type_alias_cast_and_call_as "$(cat <<'EOF'
type Handler = fn(i64) -> i64


def double(x: i64) -> i64:
    return x * 2


def add_one(x: i64) -> i64:
    return x + 1


def through_alias_param(f: Handler, n: i64) -> i64:
    return f(n)


def through_cast(p: void&, n: i64) -> i64 can[Abort.Panic, Unsafe.PointerCast]:
    f: Handler = p.cast[Handler]
    return f(n)


def through_call_as(p: void&, n: i64) -> i64 can[Abort.Panic, Unsafe.PointerCast, Unsafe.IndirectCall]:
    trusted Unsafe.IndirectCall:
        return p.call_as[fn(i64) -> i64](n)


def main() -> i64:
    can Abort.Panic, Unsafe.PointerCast, Unsafe.IndirectCall:
        a: i64 = through_alias_param(double, 10)
        b: i64 = through_cast(double.cast[void&], 5)
        c: i64 = through_call_as(add_one.cast[void&], 11)
        return a + b + c
EOF
)" 42

# Fn TYPES with REFERENCE params/returns, held in struct FIELDS and called through them.
# Three separate gaps met here: lambda_signature_probe did not consume a bare parameter's
# postfix `&` (so `fn(Cell&) -> Cell&` was not recognized as a fn type at all); the return
# type was recorded as a head TOKEN, so `-> Cell&` resolved to the POINTEE — a wrong type
# rather than a decline, which for an indirect call is an ABI mismatch; and a struct member's
# annotation was not marked a type position, so a fn-typed field silently took the i64
# placeholder. Asserted by VALUE precisely because the return-type bug is silent.
differential fn_type_ref_params_in_struct_fields "$(cat <<'EOF'
struct Cell:
    v: mutable i64


struct Work:
    scale: i64
    op: fn(i64) -> i64
    pick: fn(Cell&) -> Cell&


def triple(x: i64) -> i64:
    return x * 3


def identity(c: Cell&) -> Cell&:
    return c


def run(w: Work&, c: Cell&) -> i64 can[Abort.Panic]:
    got: Cell& = w.pick(c)
    return w.op(got.v) + w.scale


def main() -> i64:
    can Abort.Panic:
        c: mutable Cell = Cell{v: 12}
        w: Work = Work{scale: 6, op: triple, pick: identity}
        return run(&w, &c)
EOF
)" 42

differential static_storage_qualifier "$(cat <<'ELISAEOF'
def from_static(value: static u8&) -> u8&:
    return value.cast[u8&]


def main() -> i64:
    can Abort.Panic, Unsafe.PointerCast:
        text: static u8& = "*"
        a: u8& = from_static(text)
        return a.i64()
ELISAEOF
)" 42

# `match` on a packed-AST node reached through a struct FIELD. The hidden AST-store parameter
# was decided from the DIRECT parameter types only, so a function touching AST nodes only via a
# struct parameter got no store: runtime.active_store_enum stayed -1 and the match declined.
# `via_local` (an AST node passed directly) is the control — it always worked, and adding an
# unused AST parameter to `via_field` also made it compile, which is how the STORE rather than
# the type was identified as the gate. Asserted by value: both arms must contribute.
differential match_packed_ast_through_struct_field "$(cat <<'ELISAEOF'
module Ast:
    enum Node layout(handle: u32):
        pass

    enum Decl is Node:
        Enum(name: sview, count: i64)
        Other(x: i64)

    struct Holder:
        d: Decl
        tag: i64


using Ast


def via_field(h: Ast::Holder&) -> i64:
    can Memory.Allocate, Abort.Panic:
        match h.d:
            Ast::Decl.Enum(name, count):
                return count
            _:
                return 0


def via_local(d: Ast::Decl) -> i64:
    can Memory.Allocate, Abort.Panic:
        match d:
            Ast::Decl.Enum(name, count):
                return count
            _:
                return 0


def main() -> i64:
    can Memory.Allocate, Abort.Panic:
        d: Ast::Decl = (Ast::Decl.Enum("E", 21))
        h: Ast::Holder = Ast::Holder{d: d, tag: 0}
        return via_field(&h) + via_local(d)
ELISAEOF
)" 42

# `x in {A, B, C}` — membership over a BRACE SET. The OR-chain lowering existed but matched
# only an ARRAY literal (Expr.Array); the brace form is Expr.SetLit, so every such test
# declined. The semantic layer uses the brace form heavily
# (`operator in {TokenKind.EqEq, TokenKind.BangEq, …}`). `by_or` is the control: the same
# predicate spelled as an explicit or-chain, so the two must agree, and a member that is NOT
# in the set must yield false.
differential membership_over_brace_set "$(cat <<'ELISAEOF'
enum Kind:
    A
    B
    C
    D


def in_set(k: Kind) -> i64:
    can Abort.Panic:
        return 1 if k in {Kind.A, Kind.B, Kind.C} else 0


def by_or(k: Kind) -> i64:
    can Abort.Panic:
        return 1 if k == Kind.A or k == Kind.B or k == Kind.C else 0


def main() -> i64:
    can Abort.Panic:
        hits: mutable i64 = 0
        hits <- hits + in_set(Kind.A) * 10
        hits <- hits + in_set(Kind.D) * 100
        hits <- hits + by_or(Kind.B) * 30
        hits <- hits + in_set(Kind.C) * 2
        return hits
ELISAEOF
)" 42

# `[c for c in s]` — a list comprehension over an SVIEW (not a range, not a darray).
# The semantic layer's sview_equal collects bytes this way. Checks the COUNT and the
# byte VALUES, so a lowering that walked the wrong length or loaded the wrong stride
# gives a different ANSWER rather than merely compiling.
differential sview_comprehension "$(cat <<'ELISAEOF'
def count_bytes(a: sview) -> i64 can[Memory.Allocate, Abort.Panic]:
    bs: darray[u8] = [c for c in a]
    return bs.count.i64()


def sum_bytes(a: sview) -> i64 can[Memory.Allocate, Abort.Panic]:
    bs: darray[u8] = [c for c in a]
    t: mutable i64 = 0
    i: mutable usize = 0
    while i < bs.count:
        t <- t + bs[i].i64()
        i <- i + 1
    return t


def main() -> i64:
    can Memory.Allocate, Abort.Panic:
        return count_bytes("hello") * 20 + sum_bytes("abc") - 194
ELISAEOF
)" 200

# `name in {"i8", "u8", ...}` — set membership over STRING candidates, the shape the
# semantic layer's type predicates (is_primitive_type, literal_fits_in_type) all use.
# Checks hits AND misses, and a near-miss ("i3", a prefix of a member) so a length-blind
# comparison fails.
#
# LIMIT, on purpose: every probe here is a literal, and identical literals may be merged to
# one global, so this case can NOT distinguish a content comparison from a pointer one.
# Building a pointer-distinct sview needs string_view_slice, which lives in std source these
# self-contained fixtures do not include. The discriminating check is the parse_report
# differential against stage0.
differential sview_set_membership "$(cat <<'ELISAEOF'
def is_prim(name: sview) -> bool:
    can Abort.Panic:
        return name in {"i8", "i16", "i32", "bool", "sview"}


def main() -> i64:
    can Memory.Allocate, Abort.Panic:
        hits: mutable i64 = 0
        hits <- hits + 1 if is_prim("i8") else hits
        hits <- hits + 10 if is_prim("i32") else hits
        hits <- hits + 100 if is_prim("nope") else hits
        hits <- hits + 1000 if is_prim("sview") else hits
        hits <- hits + 10000 if is_prim("i3") else hits
        return hits
ELISAEOF
)" 243   # 1011 truncated mod 256 by the exit code

# `dst.extend([x for x in src])` — extend from a COMPREHENSION. The source is a value with
# no address, and the extend loop re-emits its source once per element as `src[i]`, so a
# lowering that passed the comprehension through unchanged would rebuild the list every
# iteration. This case makes that visible as a WRONG ANSWER rather than just slow code: the
# comprehension filters, so a per-iteration rebuild changes which elements land where.
differential extend_from_comprehension "$(cat <<'ELISAEOF'
def add_evens(dst: mutable darray[i64]&, src: darray[i64]) -> void can[Memory.Allocate, Abort.Panic]:
    dst.extend([x for x in src if x % 2 == 0])


def main() -> i64:
    can Memory.Allocate, Abort.Panic:
        src: mutable darray[i64] = []
        i: mutable i64 = 1
        while i <= 6:
            src.push(i)
            i <- i + 1
        out: mutable darray[i64] = []
        out.push(99)
        add_evens(out, src)
        total: mutable i64 = 0
        j: mutable usize = 0
        while j < out.count:
            total <- total + out[j]
            j <- j + 1
        return out.count.i64() * 10 + total
ELISAEOF
)" 151   # 4 elements (99,2,4,6): 4*10 + (99+2+4+6) = 151

# `for x in xs |acc| -> acc:` — a capture-listed accumulator loop whose body ALSO restates
# the accumulator as a bare-ident statement (and does so per match arm, which is how the
# semantic layer's validate_struct_layouts_range threads its table). The capture mutates in
# place, so both the loop's `-> acc` and the per-branch restatements are no-op annotations.
#
# The value is accumulated across iterations AND a branch is taken per element, so a lowering
# that dropped the body, or ran it once, gives a different ANSWER rather than failing to
# build. Note the sibling form `|n = 0| -> n + x` genuinely threads a value between
# iterations and must keep DECLINING — stage0 gives it a shadowing loop-local, which stage1
# does not model, so accepting it would be a silent wrong answer.
differential accumulator_for_loop "$(cat <<'ELISAEOF'
def score(xs: darray[i64]) -> i64 can[Memory.Allocate, Abort.Panic]:
    acc: mutable i64 = 0
    for x in xs |acc| -> acc:
        if x % 2 == 0:
            acc <- acc + x
            acc
        else:
            acc <- acc + 100
            acc
    return acc


def main() -> i64:
    can Memory.Allocate, Abort.Panic:
        xs: mutable darray[i64] = []
        xs.push(2)
        xs.push(3)
        xs.push(4)
        return score(xs)
ELISAEOF
)" 106   # 2 + 100 + 4

# `match s: "": …` — an EMPTY-STRING pattern on an sview scrutinee. The pattern decoder
# rejected a zero-length span as undecodable, so every function with such an arm was
# dropped. Checks the empty case hits AND that a non-empty scrutinee falls to the default,
# so a decoder that produced a match-anything pattern would fail too. The nested arm also
# pins that an inner sview match inside another match arm works.
differential empty_string_pattern "$(cat <<'ELISAEOF'
def pick(a: sview, b: sview) -> i64 can[Memory.Allocate, Abort.Panic]:
    n: mutable i64 = 0
    match a:
        "x":
            match b:
                "":
                    n <- 1
                _:
                    n <- 2
        _:
            n <- 3
    return n


def main() -> i64:
    can Memory.Allocate, Abort.Panic:
        return pick("x", "") * 100 + pick("x", "q") * 10 + pick("z", "")
ELISAEOF
)" 123

# `for x in xs |n = 0|:` — an INITIALIZED capture. stage0 gives it a SHADOWING loop-local,
# so the OUTER `n` of the same name is untouched after the loop. This case exists because
# getting it wrong is SILENT: emitting the accumulator decl into the enclosing scope makes
# the loop mutate the caller's variable and the function returns the accumulated value
# instead of the original. Measured before the fix: 4 where stage0 gives 100.
#
# The second half pins the OPPOSITE direction — an UNINITIALIZED capture (`|acc|`) names an
# existing outer local and MUST mutate it in place, so over-scoping would break it too. A
# lowering that scoped both, or neither, fails one half of this case.
differential loop_accumulator_scoping "$(cat <<'ELISAEOF'
def shadowed(xs: darray[i64]) -> i64 can[Memory.Allocate, Abort.Panic]:
    n: mutable i64 = 100
    for x in xs |n = 0|:
        n <- n + x
    return n


def in_place(xs: darray[i64]) -> i64 can[Memory.Allocate, Abort.Panic]:
    acc: mutable i64 = 0
    for x in xs |acc| -> acc:
        acc <- acc + x
        acc
    return acc


def main() -> i64:
    can Memory.Allocate, Abort.Panic:
        xs: mutable darray[i64] = []
        xs.push(4)
        xs.push(5)
        return shadowed(xs) + in_place(xs)
ELISAEOF
)" 109   # shadowed keeps 100, in_place accumulates 9

# `a, b, c =` NEWLINE INDENT `for … |accs…| -> a, b, c:` — multi-target destructuring from an
# accumulator loop. This nests TWO blocks: the indented body's tail statement is the loop's own
# header block, so the outer block's statement list is empty and its value is another Block.
# The tuple check used to see that Block and decline every such form in the semantic layer.
#
# Three accumulators of DIFFERENT types (bool, u32, i64) and each is read back, so a lowering
# that bound them in the wrong order or dropped one changes the ANSWER rather than failing to
# build. The loop also filters, so the accumulation has to actually run per element.
differential multi_target_accumulator_destructuring "$(cat <<'ELISAEOF'
def scan(xs: darray[i64]) -> i64 can[Memory.Allocate, Abort.Panic]:
    found, count, total =
        for x in xs |found = false, count: u32 = 0, total = 0| -> found, count, total:
            if x > 2:
                found <- true
                count <- count + 1
                total <- total + x
    return (1000 if found else 0) + count.i64() * 100 + total


def main() -> i64:
    can Memory.Allocate, Abort.Panic:
        xs: mutable darray[i64] = []
        xs.push(1)
        xs.push(3)
        xs.push(5)
        return scan(xs)
ELISAEOF
)" 184   # 1000 + 2*100 + 8 = 1208, truncated mod 256

# `match e: M::EK.A: …` — a MODULE-QUALIFIED enum variant as a match pattern. Pattern.Variant
# carries the path as one dotted string, and the ordinal lookup compared the WHOLE prefix
# before the last dot ("M::EK") against the registered enum name ("EK"), so it never matched
# and every such arm declined. The semantic layer writes all of its Ast enum patterns this way.
# Distinct arm values per variant, so a lookup that resolved to the wrong ordinal changes the
# ANSWER rather than failing to build.
differential module_qualified_enum_pattern "$(cat <<'ELISAEOF'
module M:
    enum EK:
        A
        B
        C


def to_i(e: M::EK) -> i64:
    can Abort.Panic:
        return match e:
            M::EK.A: 7
            M::EK.B: 9
            _:       11


def main() -> i64:
    can Abort.Panic:
        return to_i(M::EK.B) * 10 + to_i(M::EK.C)
ELISAEOF
)" 101

# `e is M::EK.A` — a MODULE-QUALIFIED enum variant in an `is` test. The three `is` forms
# (payload-enum, const-enum, packed) each matched the variant head only as an Expr.Ident, but a
# qualified head parses as Expr.Scope, so all of them missed and the function declined.
# Checks both the hit and the miss.
differential module_qualified_enum_is "$(cat <<'ELISAEOF'
module M:
    enum EK:
        A
        B


def kind_is_a(e: M::EK) -> i64:
    can Abort.Panic:
        return 5 if e is M::EK.A else 3


def main() -> i64:
    can Abort.Panic:
        return kind_is_a(M::EK.A) * 10 + kind_is_a(M::EK.B)
ELISAEOF
)" 53

# `a, b <- b, a` — POSITIONAL parallel assignment, and the guarded form
# `a, b <- b, a if COND`. Two separate defects: the backend had no lowering for an Array RHS
# at all, and the trailing `if` parses as part of the LAST ELEMENT rather than guarding the
# statement, so it arrived as `[b, If(COND, a, Absent)]` — an else-less conditional value with
# no lowering, where stage0 accepts the statement.
#
# A SWAP is the case that catches evaluation order: every RHS value must be emitted before any
# store, or `first` on the right reads the value it was just overwritten with. A lowering that
# interleaved stores returns 22/44 here instead of 21/34.
differential parallel_assignment_and_guard "$(cat <<'ELISAEOF'
def order(a: i64, b: i64, do_swap: bool) -> i64:
    can Abort.Panic:
        first: mutable i64 = a
        second: mutable i64 = b
        first, second <- second, first if do_swap
        return first * 10 + second


def plain(a: i64, b: i64) -> i64:
    can Abort.Panic:
        first: mutable i64 = a
        second: mutable i64 = b
        first, second <- second, first
        return first * 10 + second


def main() -> i64:
    can Abort.Panic:
        return order(1, 2, true) + order(3, 4, false) + plain(1, 2)
ELISAEOF
)" 76   # 21 + 34 + 21

# `for x in xs |lo, hi| -> lo, hi:` — a loop header with a MULTI-name (tuple) yield in
# STATEMENT position. The yield is a no-op annotation there (captures mutate in place), but the
# guard only accepted a single capture Ident, so the tuple form declined outright — it is how
# the semantic layer's multi-accumulator walkers are written.
#
# Both captures are mutated and both are read back, so dropping either half changes the answer.
differential tuple_yield_loop_header "$(cat <<'ELISAEOF'
def walk(xs: darray[i64]) -> i64 can[Memory.Allocate, Abort.Panic]:
    lo: mutable i64 = 100
    hi: mutable i64 = 0
    for x in xs |lo, hi| -> lo, hi:
        lo <- x if x < lo else lo
        hi <- x if x > hi else hi
    return lo * 100 + hi


def main() -> i64:
    can Memory.Allocate, Abort.Panic:
        xs: mutable darray[i64] = []
        xs.push(3)
        xs.push(7)
        return walk(xs)
ELISAEOF
)" 51   # lo=3, hi=7 -> 307 truncated mod 256

# A MIXED capture header: a bare capture (`out`) plus a TYPED initialized accumulator
# (`position: usize = 0`), yielded as a tuple. The bound-name check keyed on UNTYPED VarDecls
# only, so the typed accumulator was not recognised as a name the block binds and the whole
# loop declined.
#
# Note the header must capture `out`: stage0 rejects mutating an outer binding from inside a
# value block (docs/119 E4), even through a call. The loop breaks early, so a lowering that
# mishandled the accumulator would copy the wrong number of elements.
differential typed_accumulator_capture "$(cat <<'ELISAEOF'
def fill(out: mutable darray[i64]&, xs: darray[i64], limit: usize) -> void can[Memory.Allocate, Abort.Panic]:
    for x in xs |out, position: usize = 0| -> out, position:
        break if position >= limit
        out.push(x)
        position <- position + 1


def main() -> i64:
    can Memory.Allocate, Abort.Panic:
        xs: mutable darray[i64] = []
        xs.push(4)
        xs.push(5)
        xs.push(6)
        o: mutable darray[i64] = []
        fill(o, xs, 2)
        return o.count.i64() * 10 + o[1]
ELISAEOF
)" 25

# DEFAULT PARAMETERS omitted at the call site. The parser parsed the default expression and
# DISCARDED it, keeping only a has_default flag, so nothing downstream could fill an omitted
# argument and the call declined on an LLVMCountParams mismatch.
#
# Each call omits a different number of trailing arguments and the three results differ, so a
# lowering that filled the wrong value — or filled positionally out of order — changes the
# ANSWER rather than failing to build.
differential default_parameters "$(cat <<'ELISAEOF'
def scaled(base: i64, factor: i64 = 3, offset: i64 = 5) -> i64:
    return base * factor + offset


def main() -> i64:
    can Abort.Panic:
        return scaled(2) + scaled(2, 4) + scaled(2, 4, 6)
ELISAEOF
)" 38   # 11 + 13 + 14

# `count VAR in XS where COND` — a fold to an integer. The parser DROPPED the query head
# keyword from Expr.Comprehension, so the backend could not tell `count` from `sum`/`min`/`max`
# and declined rather than guess. The head is now recorded in the line-keyed side table.
#
# The count and the container length differ, so a lowering that returned the length (or
# short-circuited like `any` does) gives a different ANSWER.
differential count_quantifier "$(cat <<'ELISAEOF'
def evens(xs: darray[i64]) -> usize can[Memory.Allocate, Abort.Panic]:
    return count x in xs where x % 2 == 0


def main() -> i64:
    can Memory.Allocate, Abort.Panic:
        xs: mutable darray[i64] = []
        xs.push(1)
        xs.push(2)
        xs.push(4)
        xs.push(7)
        return evens(xs).i64() * 10 + xs.count.i64()
ELISAEOF
)" 24   # 2 evens of 4 elements

# `x: T = match OPT: v: … / _: …` — an OPTIONAL scrutinee in VALUE position. A binding arm over
# an optional is a CATCH-ALL: stage0 takes it even when the optional is ABSENT, and `_` is dead.
# The slot emitter accepted only integer/penum/packed/cstr/sview scrutinees, so this declined.
#
# Both halves matter. `sel` never reads the payload, so it pins ARM SELECTION on the absent
# path (a present/absent split would score 2 there, not 1). `val` reads the payload only where
# the optional is PRESENT — deliberately, because the payload of an ABSENT optional is UNDEF in
# stage0 (`v: v + 1` yields 0 there while `v: 5` yields 5), so reading it is undefined
# behaviour and NOT a parity-testable path.
differential optional_value_match "$(cat <<'ELISAEOF'
def pick(n: i64) -> i64? can[Abort.Panic]:
    return n * 2 if n > 0 else null


def sel(n: i64) -> i64:
    can Abort.Panic:
        got: i64 = match pick(n):
            v: 1
            _: 2
        return got


def val(n: i64) -> i64:
    can Abort.Panic:
        got: i64 = match pick(n):
            v: v
            _: 9
        return got


def main() -> i64:
    can Abort.Panic:
        return sel(0) * 100 + val(3) * 10 + val(5)
ELISAEOF
)" 170   # sel(0)=1 (binding arm taken when ABSENT), val(3)=6, val(5)=10

# `phrase = EXPR` — an UNTYPED declaration by FIRST ASSIGNMENT, which stage0 accepts. stage1
# parses it as Stmt.Assign and the handler rejected `=` outright, so it declined. Declares the
# local from the value's inferred type.
#
# The initializer is a TERNARY of f-strings: a value-`if` is context-typed and has no standalone
# type, so the then-arm supplies it. Both branches are exercised and their lengths differ, so
# inferring from the wrong arm or dropping a branch changes the ANSWER.
differential untyped_decl_first_assignment "$(cat <<'ELISAEOF'
def msg(flag: bool, name: sview) -> i64 can[Memory.Allocate, Abort.Panic]:
    phrase = f" of {name}" if flag else f""
    buffer: mutable darray[u8] = []
    buffer.extend(f"x{phrase}")
    return buffer.count.i64()


def main() -> i64:
    can Memory.Allocate, Abort.Panic:
        return msg(true, "ab") * 10 + msg(false, "ab")
ELISAEOF
)" 71   # "x of ab" = 7, "x" = 1

# `match s: "a" | "b":` — an ALTERNATION arm on an sview scrutinee in STATEMENT position. The
# per-arm path tested a single literal, so an OR arm fell through to the decline. Expanded into
# one single-literal arm per option, sharing the body.
#
# Every option of every arm is exercised plus a miss, weighted by position, so dropping an
# option or reordering the arms changes the ANSWER.
differential sview_alternation_statement "$(cat <<'ELISAEOF'
def kind(s: sview) -> i64 can[Memory.Allocate, Abort.Panic]:
    n: mutable i64 = 0
    match s:
        "a" | "b":
            n <- 1
        "c" | "d" | "e":
            n <- 2
        _:
            n <- 3
    return n


def main() -> i64:
    can Memory.Allocate, Abort.Panic:
        return kind("a") * 1000 + kind("b") * 100 + kind("d") * 10 + kind("z")
ELISAEOF
)" 99   # 1123 truncated mod 256

# `f(a) if COND else g(b)` — a TERNARY in STATEMENT position whose arms are side-effecting
# CALLS, not values. Emitting it as a value declines (the arms are void), so it is lowered as
# an if/else running each arm as a statement. The branches append different lengths, so taking
# the wrong one — or running both — changes the ANSWER.
differential ternary_statement_calls "$(cat <<'ELISAEOF'
def build(flag: bool) -> i64 can[Memory.Allocate, Abort.Panic]:
    buffer: mutable darray[u8] = []
    buffer.extend("abcd") if flag else buffer.extend("xy")
    return buffer.count.i64()


def main() -> i64:
    can Memory.Allocate, Abort.Panic:
        return build(true) * 10 + build(false)
ELISAEOF
)" 42

if [ "$fail" -ne 0 ]; then
    echo "scope_binding_smoke FAILED: $pass passed, $fail failed" >&2
    exit 1
fi
echo "scope_binding_smoke OK: $pass/$pass" >&2
