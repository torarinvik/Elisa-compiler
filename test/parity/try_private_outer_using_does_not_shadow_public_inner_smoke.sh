#!/usr/bin/env bash
# An inaccessible inherited wildcard candidate must not shadow a visible nested candidate.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

fail() {
    echo "try private outer using smoke FAIL: $1" >&2
    exit 1
}

FIXTURE="$REPO_ROOT/test/repro/try_private_outer_using_does_not_shadow_public_inner.elisa"
if ! stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1)"; then
    fail "Stage0 rejected the visible nested using candidate: $stage0_output"
fi
if grep -qE 'is private to module|cannot propagate|try requires a fallible expression' <<< "$stage0_output"; then
    fail "Stage0 did not skip the inaccessible inherited callable: $stage0_output"
fi

stage1_output="$("$RPT" < "$FIXTURE")"
if grep -qE 'is private to module|cannot propagate|try requires a fallible expression' <<< "$stage1_output"; then
    fail "Stage1 did not skip the inaccessible inherited callable: $stage1_output"
fi

echo "try private outer using smoke OK: visible nested candidate wins"
