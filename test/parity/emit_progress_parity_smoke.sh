#!/usr/bin/env bash
# Require exact progress-report parity and retain the focused step-safety checks.
set -uo pipefail
shopt -s nullglob

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
export ELISA_CORE REPO_ROOT
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/emit_parity_lib.sh"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

same=0
failed=0
rejected=0
for src in "$REPO_ROOT"/test/repro/*.elisa "$REPO_ROOT"/test/fixtures/ast/*.elisa; do
    name="$(basename "$src" .elisa)"
    if s0 -emit progress "$src" </dev/null > "$WORK/$name.s0" 2> "$WORK/$name.s0.err"; then
        :
    else
        status=$?
        if [ "$status" -gt 2 ]; then
            echo "  FAIL $src: Stage0 -emit progress exited $status" >&2
            cat "$WORK/$name.s0.err" >&2
            failed=$((failed + 1))
        else
            echo "  UNCOMPARABLE $src: Stage0 rejected input (exit $status)" >&2
            rejected=$((rejected + 1))
        fi
        continue
    fi
    if ! s1 -emit progress -o "$WORK/$name.s1" "$src" > /dev/null 2> "$WORK/$name.s1.err"; then
        echo "  FAIL $src: Stage1 -emit progress failed" >&2
        cat "$WORK/$name.s1.err" >&2
        failed=$((failed + 1))
        continue
    fi
    if cmp -s "$WORK/$name.s0" "$WORK/$name.s1"; then
        same=$((same + 1))
    else
        echo "  FAIL $src: progress output differs" >&2
        failed=$((failed + 1))
    fi
done

# This fixture specifically guards step direction: zero and wrong-sign steps must remain
# unwitnessed, while positive literal steps with the matching update operator count.
step_fixture="$WORK/progress_step_signs.s1"
if ! s1 -emit progress -o "$step_fixture" "$REPO_ROOT/test/repro/progress_step_signs.elisa" >/dev/null 2>&1 || [ ! -s "$step_fixture" ]; then
    echo "emit_progress parity FAILED: progress_step_signs fixture did not produce a Stage1 report"
    exit 1
fi
if ! grep -q '^warnings: 19$' "$step_fixture" || [ "$(grep -c 'evidence=none' "$step_fixture")" -ne 19 ] || [ "$(grep -c 'evidence=progress' "$step_fixture")" -ne 6 ]; then
    echo "emit_progress parity FAILED: progress_step_signs did not classify all 19 unproven and 6 valid steps as expected"
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
if ! grep -q '^  valid_compound_increment_parenthesized_positive_step: obligations=Loop:1 evidence=progress ' "$step_fixture"; then
    echo "emit_progress parity FAILED: normalized parenthesized compound step was not accepted as progress"
    exit 1
fi
if ! grep -q '^  valid_explicit_increment_parenthesized_positive_step: obligations=Loop:1 evidence=progress ' "$step_fixture"; then
    echo "emit_progress parity FAILED: normalized parenthesized explicit step was not accepted as progress"
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

if [ "$((same + failed + rejected))" -eq 0 ]; then
    echo "emit_progress parity FAILED: no fixtures found" >&2
    exit 1
fi
if [ "$((same + failed))" -eq 0 ]; then
    echo "emit_progress parity FAILED: no fixtures were comparable" >&2
    exit 1
fi
if [ "$failed" -ne 0 ]; then
    echo "emit_progress parity FAILED: $same matched, $failed failed, $rejected Stage0-rejected"
    exit 1
fi
echo "emit_progress parity OK: $same matched, $rejected Stage0-rejected"
