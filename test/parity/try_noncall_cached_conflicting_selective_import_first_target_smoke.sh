#!/usr/bin/env bash
# Conflicting selective imports must keep Core's first target in cached Try facts.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

fail() {
    echo "try noncall cached conflicting-import smoke FAIL: $1" >&2
    exit 1
}

FIXTURE="$REPO_ROOT/test/repro/try_noncall_cached_conflicting_selective_import_first_target.elisa"
set +e
stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1)"
stage0_status=$?
set -e
[[ "$stage0_status" -ne 0 ]] || fail "Stage0 accepted the conflicting selective imports"
grep -q 'conflicting import.*"origin"' <<< "$stage0_output" \
    || fail "Stage0 did not report the selective alias conflict: $stage0_output"
stage0_rows="$(printf '%s\n' "$stage0_output" \
    | sed -E -n 's#^.*:([0-9]+):[0-9]+[^:]*: cannot propagate.*$#L\1#p' \
    | LC_ALL=C sort)"
stage1_output="$("$RPT" < "$FIXTURE")"
stage1_rows="$(printf '%s\n' "$stage1_output" \
    | sed -E -n 's#^[[:space:]]*L([0-9]+) cannot propagate.*$#L\1#p' \
    | LC_ALL=C sort)"
expected_rows='L28'

[[ "$stage0_rows" == "$expected_rows" ]] || fail "Stage0 did not propagate the first source family: $stage0_rows; output: $stage0_output"
[[ $(grep -cF 'cannot propagate' <<< "$stage0_output") == 1 ]] || fail "Stage0 reported an unexpected Try diagnostic count: $stage0_output"
grep -q 'cannot propagate ProviderA.SourceError from a function returning Consumer.Fault' <<< "$stage0_output" \
    || fail "Stage0 did not select ProviderA.origin as the first imported target: $stage0_output"
[[ $(grep -cF 'cannot propagate' <<< "$stage1_output") == 1 ]] || fail "Stage1 did not report exactly one first-target mismatch: $stage1_output"
[[ "$stage1_rows" == "$expected_rows" ]] || fail "Stage1 selected a later conflicting source family: $stage1_output"
grep -q 'cannot propagate ProviderA.SourceError from a function returning Consumer.Fault' <<< "$stage1_output" \
    || fail "Stage1 did not select ProviderA.origin as the first imported target: $stage1_output"

echo "try noncall cached conflicting-import smoke OK: the first alias supplies SourceError"
