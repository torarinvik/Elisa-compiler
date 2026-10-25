#!/usr/bin/env bash
# A concrete imported infallible overload outranks a local generic fallible overload.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

fail() {
    echo "errorset wrapper infallible-overload smoke FAIL: $1" >&2
    exit 1
}

FIXTURE="$REPO_ROOT/test/repro/errorset_wrapper_return_infallible_cross_scope.elisa"
set +e
stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1)"
stage0_status=$?
set -e
[[ "$stage0_status" -eq 0 ]] || fail "Core rejected the concrete infallible overload: $stage0_output"

stage1_output="$("$RPT" < "$FIXTURE")"
grep -q '^P 0$' <<< "$stage1_output" \
    || fail "Stage1 did not parse the overload fixture: $stage1_output"
grep -q '^D 0$' <<< "$stage1_output" \
    || fail "Stage1 reported a mismatch for the selected infallible overload: $stage1_output"
! grep -q 'cannot propagate' <<< "$stage1_output" \
    || fail "EWR propagated an error from the unselected fallible overload: $stage1_output"

echo "errorset wrapper infallible-overload smoke OK: Core receiver ranking is honored"
