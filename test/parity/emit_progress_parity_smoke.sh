#!/usr/bin/env bash
# `-emit progress` BYTE PARITY, RATCHETED.
#
# Every rule stage1 implements was MEASURED against stage0, not inferred:
#   * `obligations=Loop:N` counts WHILE loops only — a bounded `for i in 0..<3` is finite by
#     construction and contributes nothing.
#   * `evidence=progress` when every loop advances: condition `var OP bound` with OP in
#     {<, <=, >, >=} (NOT `!=`) and every reachable path that continues the loop moves `var`
#     toward the bound (`n <- n + k` / `n += k`, and the `-` forms for `>`). Updates nested
#     inside `if`/`match` count when every continuing branch advances.
#     `trusted Unsafe.NonProgress` gives `evidence=unsafe-nonprogress`;
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
source "$REPO_ROOT/test/parity/emit_parity_lib.sh"

BASELINE_FILE="$REPO_ROOT/test/fixtures/emit_progress.baseline"
baseline="$(tr -d '[:space:]' < "$BASELINE_FILE")"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

same=0
total=0
for src in "$REPO_ROOT"/test/repro/*.elisa "$REPO_ROOT"/test/fixtures/ast/*.elisa; do
    name="$(basename "$src" .elisa)"
    # Check this focused step-sign fixture against its explicit Stage1 expectations
    # below instead of counting it in the broad Stage0 byte-parity ratchet. Stage0's
    # legacy counting-loop rule accepts a nonzero unsigned literal magnitude with the
    # direction-matched operator; Stage1 represents the i64-min magnitude as negative.
    [ "$name" = "progress_step_signs" ] && continue
    s0 -emit progress "$src" </dev/null > "$WORK/$name.s0" 2>/dev/null || continue
    s1 -emit progress -o "$WORK/$name.s1" "$src" >/dev/null 2>&1 || continue
    total=$((total + 1))
    cmp -s "$WORK/$name.s0" "$WORK/$name.s1" && same=$((same + 1))
done

# This fixture specifically guards step direction: zero and wrong-sign steps must remain
# unwitnessed, while positive literal steps with the matching update operator count.
step_fixture="$WORK/progress_step_signs.s1"
if ! s1 -emit progress -o "$step_fixture" "$REPO_ROOT/test/repro/progress_step_signs.elisa" >/dev/null 2>&1 || [ ! -s "$step_fixture" ]; then
    echo "emit_progress parity FAILED: progress_step_signs fixture did not produce a Stage1 report"
    exit 1
fi
if ! grep -q '^warnings: 21$' "$step_fixture" || [ "$(grep -c 'evidence=none' "$step_fixture")" -ne 21 ] || [ "$(grep -c 'evidence=progress' "$step_fixture")" -ne 4 ]; then
    echo "emit_progress parity FAILED: progress_step_signs did not classify all 21 unproven and 4 valid steps as expected"
    exit 1
fi
if ! grep -q '^  valid_compound_increment: obligations=Loop:1 evidence=progress ' "$step_fixture"; then
    echo "emit_progress parity FAILED: canonical compound increment was not accepted as progress"
    exit 1
fi
if ! grep -q '^  valid_explicit_increment: obligations=Loop:1 evidence=progress ' "$step_fixture"; then
    echo "emit_progress parity FAILED: canonical explicit increment was not accepted as progress"
    exit 1
fi
if ! grep -q '^  valid_compound_decrement: obligations=Loop:1 evidence=progress ' "$step_fixture"; then
    echo "emit_progress parity FAILED: canonical compound decrement was not accepted as progress"
    exit 1
fi
if ! grep -q '^  valid_explicit_decrement: obligations=Loop:1 evidence=progress ' "$step_fixture"; then
    echo "emit_progress parity FAILED: canonical explicit decrement was not accepted as progress"
    exit 1
fi
if ! grep -q '^  unrecognized_compound_decrement_negative_step: obligations=Loop:1 evidence=none ' "$step_fixture"; then
    echo "emit_progress parity FAILED: noncanonical negative step was incorrectly accepted for a decreasing bound"
    exit 1
fi
if ! grep -q '^  unrecognized_compound_increment_negative_subtract: obligations=Loop:1 evidence=none ' "$step_fixture"; then
    echo "emit_progress parity FAILED: noncanonical negative step was incorrectly accepted for an increasing bound"
    exit 1
fi
if ! grep -q '^  unrecognized_explicit_increment_parenthesized_positive_step: obligations=Loop:1 evidence=none ' "$step_fixture"; then
    echo "emit_progress parity FAILED: unsupported parenthesized step was incorrectly accepted as progress"
    exit 1
fi
if ! grep -q '^  compound_decrement_rhs_mimics_explicit_increment: obligations=Loop:1 evidence=none ' "$step_fixture"; then
    echo "emit_progress parity FAILED: compound RHS was incorrectly reinterpreted as an explicit loop update"
    exit 1
fi
if ! grep -q '^  shadow_assignment_mimics_explicit_increment: obligations=Loop:1 evidence=none ' "$step_fixture"; then
    echo "emit_progress parity FAILED: a shadow binding was incorrectly counted as mutating the loop variable"
    exit 1
fi
if ! grep -q '^  positive_magnitude_parses_as_negative_minimum: obligations=Loop:1 evidence=none ' "$step_fixture"; then
    echo "emit_progress parity FAILED: the i64-min literal magnitude was incorrectly accepted as a positive step"
    exit 1
fi
if ! grep -q '^  unary_negative_minimum_step_is_unproven: obligations=Loop:1 evidence=none ' "$step_fixture"; then
    echo "emit_progress parity FAILED: unary-negative i64 minimum was incorrectly accepted as a positive step"
    exit 1
fi

if [ "$same" -lt "$baseline" ]; then
    echo "emit_progress parity FAILED: $same byte-identical of $total, ratchet requires >= $baseline"
    exit 1
fi
echo "emit_progress parity OK: $same fixtures byte-identical of $total (ratchet $baseline)"
