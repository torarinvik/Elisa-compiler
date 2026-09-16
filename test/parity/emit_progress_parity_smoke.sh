#!/usr/bin/env bash
# `-emit progress` BYTE PARITY, RATCHETED.
#
# Every rule stage1 implements was MEASURED against stage0, not inferred:
#   * `obligations=Loop:N` counts WHILE loops only — a bounded `for i in 0..<3` is finite by
#     construction and contributes nothing.
#   * `evidence=progress` when every loop advances: condition `var OP bound` with OP in
#     {<, <=, >, >=} (NOT `!=`) and a TOP-LEVEL body assignment moving `var` toward it
#     (`n <- n + k` / `n += k`, and the `-` forms for `>`). Nested inside an `if` does NOT
#     count. `trusted Unsafe.NonProgress` gives `evidence=unsafe-nonprogress`;
#     `trusted Unsafe.BlockMain` sets unsafe_block_main; `@main_thread` sets main_thread.
#     A DECLARED `can[Unsafe.NonProgress]` sets nothing — only the trusted form.
#   * summaries print ALPHABETICALLY, stable for overloads (which share a name and each get
#     their own line).
#
# The ratchet exists because stage0's evidence analysis is RICHER than these rules: the std's
# `while (…) and a.end.next != null: a.end <- a.end.next` discharges by structural list
# descent, which stage1 does not model. stage1 is CONSERVATIVE there — it reports
# `evidence=none` and MORE warnings, never claiming progress it cannot show — so the failure
# direction is over-warning, not a missed liveness obligation.
#
# `blocking` and `blocking_path` are emitted false/none: they hold that value in ALL 56
# corpus fixtures, so there is no witness to derive their rule from.
set -uo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
export ELISA_CORE REPO_ROOT
source "$REPO_ROOT/test/parity/resolve_elisac.sh"

BASELINE_FILE="$REPO_ROOT/test/fixtures/emit_progress.baseline"
baseline="$(tr -d '[:space:]' < "$BASELINE_FILE")"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

same=0
total=0
for src in "$REPO_ROOT"/test/repro/*.elisa "$REPO_ROOT"/test/fixtures/ast/*.elisa; do
    name="$(basename "$src" .elisa)"
    "$ELISACORE_BIN" -emit progress "$src" </dev/null > "$WORK/$name.s0" 2>/dev/null || continue
    bash "$REPO_ROOT/scripts/elisac_stage1.sh" -emit progress -o "$WORK/$name.s1" "$src" >/dev/null 2>&1 || continue
    total=$((total + 1))
    cmp -s "$WORK/$name.s0" "$WORK/$name.s1" && same=$((same + 1))
done

if [ "$same" -lt "$baseline" ]; then
    echo "emit_progress parity FAILED: $same byte-identical of $total, ratchet requires >= $baseline"
    exit 1
fi
echo "emit_progress parity OK: $same fixtures byte-identical of $total (ratchet $baseline)"
