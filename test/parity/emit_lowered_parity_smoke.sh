#!/usr/bin/env bash
# `-emit lowered` BYTE PARITY, RATCHETED.
#
# stage0's `lowered` is fmt of the ANALYSED AST: its analyser desugars the tree IN PLACE
# (UFCS method calls to free calls, overloaded names to their `__ovl__` form, address-of
# insertion) and lowered prints the result. stage1's semantic layer does not mutate the AST
# that way, so this emits the UNLOWERED rendering.
#
# That is exactly right wherever no lowering applies — 41 of 56 corpus fixtures have
# byte-identical `fmt` and `lowered` output from stage0 itself — and honestly different
# where it does. The gate ratchets the identical count rather than claiming a parity stage1
# does not have; raising it is a one-line commit when the desugarings land.
#
# Note stage0's `-emit fmt` and `-emit lowered` were SWAPPED until 2026-08-14 (fmt printed
# the desugared tree and lowered the raw one) — see the stage0-fmt-was-not-a-formatter memory
# before trusting any older measurement of either.
set -uo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/structpy-tree}"
export ELISA_CORE REPO_ROOT
source "$REPO_ROOT/test/parity/resolve_elisac.sh"

BASELINE_FILE="$REPO_ROOT/test/fixtures/emit_lowered.baseline"
baseline="$(tr -d '[:space:]' < "$BASELINE_FILE")"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

same=0
total=0
for src in "$REPO_ROOT"/test/repro/*.elisa "$REPO_ROOT"/test/fixtures/ast/*.elisa; do
    name="$(basename "$src" .elisa)"
    "$ELISACORE_BIN" -emit lowered "$src" </dev/null > "$WORK/$name.s0" 2>/dev/null || continue
    bash "$REPO_ROOT/scripts/elisac_stage1.sh" -emit lowered -o "$WORK/$name.s1" "$src" >/dev/null 2>&1 || continue
    total=$((total + 1))
    cmp -s "$WORK/$name.s0" "$WORK/$name.s1" && same=$((same + 1))
done

if [ "$same" -lt "$baseline" ]; then
    echo "emit_lowered parity FAILED: $same byte-identical of $total, ratchet requires >= $baseline"
    exit 1
fi
echo "emit_lowered parity OK: $same fixtures byte-identical of $total (ratchet $baseline)"
