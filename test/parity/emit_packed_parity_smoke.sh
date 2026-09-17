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

echo "emit_packed parity: $same exact, $differ divergent"
[ "$differ" -eq 0 ] || { echo "emit_packed parity FAILED"; exit 1; }
echo "emit_packed parity OK"
