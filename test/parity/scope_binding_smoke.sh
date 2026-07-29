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

if [ "$fail" -ne 0 ]; then
    echo "scope_binding_smoke FAILED: $pass passed, $fail failed" >&2
    exit 1
fi
echo "scope_binding_smoke OK: $pass/$pass" >&2
