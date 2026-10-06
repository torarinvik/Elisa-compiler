#!/usr/bin/env bash
# `-emit packed` — the packed lowering profile and each packed enum's ROW LAYOUT.
#
# EXACT parity is demanded wherever the two compilers' layouts agree:
#   * a unit with no packed enum (which is all 56 corpus fixtures), and
#   * a packed enum with NO `common:` block.
#
# A COMMON-CARRYING enum is a deliberate, documented layout difference: stage1 places commons
# INLINE in the row, stage0 keeps them in a SIDE TABLE (see codegen_stmt_match.elisa ~460 and
# the packed-common-field-row-divergence memory). `-emit packed` is a DESCRIPTION of the
# layout the compiler actually uses, so stage1 reports its own — in stage0's own vocabulary,
# which already has an `inline row_field=N` form. For those the gate asserts stage1 is
# SELF-CONSISTENT rather than equal to stage0:
#   row bytes == 8 (tag) + 8*commons + 8*widest_payload_words, side-table words == 0,
#   and common k at row field 1+k.
# That catches a regression in either direction without pretending the layouts agree.
set -uo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
export ELISA_CORE REPO_ROOT
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/emit_parity_lib.sh"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

same=0
differ=0
rejected=0

exact() {
    local label="$1"; local src="$2"
    # STDOUT only: the report goes to stdout and semantic WARNINGS to stderr, so folding
    # them together made three corpus fixtures "diverge" on stage0's own warning text.
    s0 -emit packed "$src" </dev/null > "$WORK/s0" 2>/dev/null || { echo "SKIP $label (stage0 declined)"; return; }
    # stage0's `-emit packed` skips the safety analyses, so a repro NEGATIVE reaches the report
    # there while stage1 rejects it. This gate compares LAYOUT REPORTS: the defect it owns is
    # stage1 declining `-emit packed` for a program its own full compile accepts. Whether the
    # program should be accepted at all (stage1's stricter safety verdicts) is gated elsewhere.
    s1 -emit packed -o "$WORK/s1" "$src" >/dev/null 2>&1 || {
        if ! s1 -emit obj -o "$WORK/s1.o" "$src" >/dev/null 2>&1; then
            rejected=$((rejected + 1)); echo "SKIP $label (stage1 rejects the program)"; return
        fi
        differ=$((differ + 1)); echo "FAILED $label: stage1 compiles it but emitted no packed report"; return; }
    if cmp -s "$WORK/s0" "$WORK/s1"; then
        same=$((same + 1))
    else
        differ=$((differ + 1)); echo "DIFF $label:"; diff "$WORK/s0" "$WORK/s1" | head -8
    fi
}

# 1. The corpus: no packed enums anywhere, so `enums: none` must match exactly.
for src in "$REPO_ROOT"/test/repro/*.elisa "$REPO_ROOT"/test/fixtures/ast/*.elisa; do
    exact "$(basename "$src" .elisa)" "$src"
done

# 2. A packed enum with NO commons — layouts agree, so exact parity.
cat > "$WORK/nocommon.elisa" <<'EOF'
packed enum E:
    A(x: i64)
    B(y: i64, z: i64)

def main() -> i64:
    return 0
EOF
exact "packed-no-commons" "$WORK/nocommon.elisa"

# 3. Common-carrying: EXACT parity. This section used to pin stage1's own inline-commons
# row (`row bytes: 40`, `inline row_field=N`) as a self-consistency check while the two
# layouts deliberately differed; stage1 has since adopted stage0's side-table layout and the
# reports are byte-identical, so the hand-written expectations had rotted into a permanent
# red the moment the gate stopped being skipped (2026-09-16).
cat > "$WORK/commons.elisa" <<'EOF'
packed enum E:
    common:
        t: u32
        u: i64
    A(x: i64)
    B(y: i64, z: i64)

def main() -> i64:
    return 0
EOF
exact "packed-commons" "$WORK/commons.elisa"

# 4. RECURSIVE enums: EXACT parity. stage0 (packedModeForPackedEnum) gives the dynamic AoS
# row ONLY to a plain `enum` promoted by recursion (RecursivePlain) without `layout(soa)`;
# a declared `packed enum` and `layout(soa)` keep canonical variant-sparse. stage1 used to
# put EVERY recursive enum in AoS (`aos`, 12 bytes vs stage0's `variant-sparse`, 16), counted
# the AoS common prefix in 4-byte words instead of stage0's ceil-over-8, and sized sparse
# payloads by FIELD count instead of ceil(ABI size / 8) (`A(x: i32, y: i32)` is one word).
recursive_case() {
    local label="$1"; shift
    printf '%s\n' "$@" "" "def main() -> i64:" "    return 0" > "$WORK/$label.elisa"
    exact "$label" "$WORK/$label.elisa"
}
recursive_case "recursive-packed" "packed enum Node:" "    Leaf(v: i64)" "    Pair(left: Node, right: Node)"
recursive_case "recursive-packed-inline-u32" "packed enum Node:" "    common:" "        @storage(inline)" "        t: u32" "    Leaf(v: i64)" "    Pair(left: Node, right: Node)"
recursive_case "recursive-packed-inline-u8-u32" "packed enum Node:" "    common:" "        @storage(inline)" "        t: u8" "        s: u32" "    Leaf(v: i64)" "    Pair(left: Node, right: Node)"
recursive_case "recursive-soa" "enum Node layout(soa):" "    Leaf(v: i64)" "    Pair(left: Node, right: Node)"
recursive_case "recursive-plain" "enum Node:" "    Leaf(v: i64)" "    Pair(left: Node, right: Node)"
recursive_case "recursive-plain-inline-i64" "enum Node:" "    common:" "        @storage(inline)" "        t: i64" "        s: u32" "    Leaf(v: i64)" "    Pair(left: Node, right: Node)"
recursive_case "packed-subword-payload" "packed enum E:" "    A(x: i32, y: i32)" "    B(z: i64)"
# Report order is SOURCE order: the promoted plain enum registers after the packed one.
recursive_case "recursive-plain-before-packed" "enum Tree:" "    Leaf(v: i64)" "    Pair(left: Tree, right: Tree)" "" "packed enum Shape:" "    common:" "        a: u32" "    Circle(r: i64)" "    Rect(w: i64, h: i64)"

echo "emit_packed parity: $same exact, $differ divergent, $rejected rejected by stage1"
[ "$differ" -eq 0 ] || { echo "emit_packed parity FAILED"; exit 1; }
echo "emit_packed parity OK"
