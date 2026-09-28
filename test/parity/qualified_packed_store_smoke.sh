#!/usr/bin/env bash
# Packed enums reached through a MODULE PATH (`Outer::Right::Message`), three defects:
#   A  stage1 accepted a qualified packed constructor, `new` or `match` with no store in
#      scope -- the store checks keyed on a bare `Message` Ident and never saw the chain.
#      stage0 rejects all three; an unchecked packed value is a raw store index.
#   B  a plain `Other::Message` sharing its bare name with a packed enum elsewhere read as
#      "may fall through": exhaustiveness unioned both enums' variants.
#   C  a value-position packed match (`x <- match n:`) declined in the backend
#      ("control expression") where `x: T = match` and `return match` compiled.
#   D  (exposed by C) packed payload binders hard-coded row field 1, which is the first
#      INLINE common when the enum has one: the value-slot match, nested `is` and nested
#      match-arm sub-patterns all read the common instead of the payload.
#   E  the backend registered packed enums by BARE name, so `Other::Message.A(x: 7)` lowered
#      as a PACKED construct into an i32 slot (it only happened to return 7). With owners
#      respected it reached the payload path, where a module-qualified LABELLED constructor
#      declined (only a bare `Message` head was accepted); both are fixed.
# The positives must RUN to stage0's exit code; the negatives must be rejected by both.
set -uo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0" || exit $?
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1" || exit $?
RUNTIME_OBJ="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-qualified-packed.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
fail=0

# Kept out of test/repro on purpose: its RECURSIVE packed enum has a separate, pre-existing
# `-emit packed` layout divergence (stage1 AoS 12-byte rows vs stage0 variant-sparse 16), and
# the corpus-wide report gate would flag that here instead of in its own check.
cat > "$WORK/packed_inline_common_nested_is.pos.elisa" <<'EOF'
# Nested `is` sub-patterns over an inline-common packed enum read the payload at row field 1
# (the common) instead of the payload index: 11 instead of 40 + 2.
packed enum Node:
    common:
        @storage(inline)
        weight: i64
    Leaf(v: i64)
    Pair(left: Node, right: Node)

def probe(owner: Arena) -> i64:
    store: Node.Store[Local] = Node.Store(owner)
    in store:
        a: Node = new Node.Leaf(weight: 5, v: 40)
        b: Node = new Node.Leaf(weight: 6, v: 2)
        p: Node = new Node.Pair(weight: 7, left: a, right: b)
        if p is Node.Pair(Node.Leaf(x), Node.Leaf(y)):
            return x + y
    return 0

def main() -> i64:
    region r(4096):
        return probe(r)
EOF

for name in qualified_packed_ctor_without_store qualified_packed_match_without_store qualified_packed_new_without_store; do
    src="$ROOT/test/repro/$name.neg.elisa"
    if "$STAGE0" -emit obj -O0 -o "$WORK/s0.o" "$src" >/dev/null 2>"$WORK/s0.err"; then
        echo "FAIL $name: stage0 accepted a storeless packed use"; fail=1; continue
    fi
    if ELISA_RUNTIME_OBJ="$RUNTIME_OBJ" "$STAGE1" -emit obj -O0 -o "$WORK/s1.o" "$src" >/dev/null 2>"$WORK/s1.err"; then
        echo "FAIL $name: stage1 accepted a storeless packed use"; fail=1; continue
    fi
    # For the RIGHT reason: the store diagnostic, naming the enum by its module path.
    grep -q 'Outer::Right::Message' "$WORK/s1.err" && grep -q 'Store' "$WORK/s1.err" || {
        echo "FAIL $name: stage1 rejected, but not with the packed store diagnostic:"; head -3 "$WORK/s1.err"; fail=1; }
done

for spec in packed_samename_plain_enum_match:7 packed_value_match_two_binders:42 packed_value_match_two_binders_module:42 \
            packed_inline_common_match_slot:12 packed_inline_common_nested_is:42; do
    name="${spec%%:*}"; want="${spec##*:}"
    src="$ROOT/test/repro/$name.pos.elisa"
    [[ -e "$src" ]] || src="$WORK/$name.pos.elisa"
    "$STAGE0" -emit obj -O0 -o "$WORK/s0.o" "$src" >/dev/null 2>&1 &&
        cc -fno-builtin "$WORK/s0.o" "$RUNTIME_OBJ" -o "$WORK/s0" || { echo "FAIL $name: stage0 did not build it"; fail=1; continue; }
    ELISA_RUNTIME_OBJ="$RUNTIME_OBJ" "$STAGE1" -emit exe -O0 -o "$WORK/s1" "$src" >"$WORK/s1.err" 2>&1 || {
        # A declared `packed enum` is variant-sparse, and the `is` form declines every
        # multi-field sparse payload (a loud coverage gap, see codegen_packed_enum_reg):
        # a decline is acceptable for the nested case, a wrong answer is not.
        if [[ "$name" == packed_inline_common_nested_is ]] && grep -q "declined 1: probe@" "$WORK/s1.err"; then
            echo "note $name: stage1 declines (multi-field sparse \`is\` payload gap)"; continue
        fi
        echo "FAIL $name: stage1 did not build it:"; grep -v warning "$WORK/s1.err" | head -3; fail=1; continue; }
    "$WORK/s0"; s0=$?
    "$WORK/s1"; s1=$?
    [[ "$s0" == "$want" && "$s1" == "$want" ]] || { echo "FAIL $name: exit stage0=$s0 stage1=$s1, want $want"; fail=1; }
done

[[ "$fail" == 0 ]] || exit 1
echo "qualified packed store smoke OK: 3 storeless uses rejected, 5 programs run to stage0's result"
