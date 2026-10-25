#!/usr/bin/env bash
# A malformed empty source or destination family must not cause a secondary Try
# mismatch when the opposite side names a different error family.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

fail() {
    echo "try malformed empty destination smoke FAIL: $1" >&2
    exit 1
}

FIXTURE="$REPO_ROOT/test/repro/try_error_malformed_empty_destination_different_source.elisa"
set +e
stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1)"
stage0_status=$?
set -e
[[ "$stage0_status" -ne 0 ]] || fail "Stage0 accepted the malformed empty destination"
[[ $(grep -cF 'error[...] requires at least one qualified error tag' <<< "$stage0_output") -eq 2 ]] \
    || fail "Stage0 did not report exactly two primary malformed-set diagnostics:\n$stage0_output"
! grep -qF 'cannot propagate' <<< "$stage0_output" \
    || fail "Stage0 added a secondary Try mismatch for the malformed destination:\n$stage0_output"

stage1_output="$("$RPT" < "$FIXTURE")"
grep -q '^D 2$' <<< "$stage1_output" \
    || fail "Stage1 reported an unexpected diagnostic count:\n$stage1_output"
[[ $(grep -cF 'error[...] requires at least one qualified error tag' <<< "$stage1_output") -eq 2 ]] \
    || fail "Stage1 did not preserve the two primary malformed-set diagnostics:\n$stage1_output"
! grep -qF 'cannot propagate' <<< "$stage1_output" \
    || fail "Stage1 added a secondary Try mismatch for the malformed destination:\n$stage1_output"

echo "try malformed empty subset smoke OK: malformed source and destination suppress unrelated coverage mismatches"
