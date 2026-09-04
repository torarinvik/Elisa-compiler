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
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/structpy-tree}"
export ELISA_CORE REPO_ROOT
source "$REPO_ROOT/test/parity/resolve_elisac.sh"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

same=0
differ=0

exact() {
    local label="$1"; local src="$2"
    # STDOUT only: the report goes to stdout and semantic WARNINGS to stderr, so folding
    # them together made three corpus fixtures "diverge" on stage0's own warning text.
    "$ELISACORE_BIN" -emit packed "$src" </dev/null > "$WORK/s0" 2>/dev/null || { echo "SKIP $label (stage0 declined)"; return; }
    bash "$REPO_ROOT/scripts/elisac_stage1.sh" -emit packed -o "$WORK/s1" "$src" >/dev/null 2>&1 || {
        differ=$((differ + 1)); echo "FAILED $label: stage1 emitted nothing"; return; }
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

# 3. Common-carrying: stage1's own layout, checked for self-consistency.
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
bash "$REPO_ROOT/scripts/elisac_stage1.sh" -emit packed -o "$WORK/c1" "$WORK/commons.elisa" >/dev/null 2>&1 || {
    echo "FAILED packed-commons: stage1 emitted nothing"; differ=$((differ + 1)); }
# The typed row is `{i32 tag, pad[4], u32, pad[4], i64, [2 x i64]}`. Each
# common occupies one word-aligned slot so the legacy packed runtime can read
# it by word while the compiler preserves its declared type.
check_line() {
    grep -Fqx "$1" "$WORK/c1" || { echo "FAILED packed-commons: missing line: $1"; differ=$((differ + 1)); }
}
check_line "  row bytes: 40"
check_line "  common prefix words: 2"
check_line "  side-table common words: 0"
check_line "    - t: u32 inline row_field=1"
check_line "    - u: i64 inline row_field=2"
check_line "  variants: A, B"

echo "emit_packed parity: $same exact, $differ divergent"
[ "$differ" -eq 0 ] || { echo "emit_packed parity FAILED"; exit 1; }
echo "emit_packed parity OK"
