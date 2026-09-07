# Scope smoke — reference IDENTITY: `p == q` on two references asks whether they are the SAME
# object, `.uintptr()` on a ref is its ADDRESS while `.i64()` is its pointee, `s.len` on a cstr
# is a call rather than a field, and `<-` on a `T&?` means two different things.


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
