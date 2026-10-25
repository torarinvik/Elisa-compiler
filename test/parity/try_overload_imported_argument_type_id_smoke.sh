#!/usr/bin/env bash
# An imported nested call must select its concrete outer Try overload family.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

fail() {
    echo "try imported argument TypeId smoke FAIL: $1" >&2
    exit 1
}

FIXTURE="$REPO_ROOT/test/repro/try_overload_imported_argument_type_id.elisa"
set +e
stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1)"
stage0_status=$?
set -e
[[ "$stage0_status" -ne 0 ]] || fail "Stage0 accepted the wrong overloaded ErrorSet family"
stage0_rows="$(printf '%s\n' "$stage0_output" \
    | sed -E -n 's#^.*:([0-9]+):[0-9]+[^:]*: cannot propagate.*$#L\1#p' \
    | LC_ALL=C sort)"
expected_rows=$'L24'
[[ "$stage0_rows" == "$expected_rows" ]] || fail "Stage0 did not report the imported bool overload's ErrorSet: $stage0_output"
grep -q 'cannot propagate BoolFault from a function returning IntegerFault' <<< "$stage0_output" \
    || fail "Stage0 selected the wrong ErrorSet family: $stage0_output"

stage1_output="$("$RPT" < "$FIXTURE")"
grep -q '^D 1$' <<< "$stage1_output" || fail "Stage1 reported an unexpected diagnostic count: $stage1_output"
stage1_rows="$(printf '%s\n' "$stage1_output" \
    | sed -E -n 's#^[[:space:]]*L([0-9]+) cannot propagate.*$#L\1#p' \
    | LC_ALL=C sort)"
[[ "$stage1_rows" == "$expected_rows" ]] || fail "Stage1 missed the imported nested-call family mismatch: $stage1_output"
grep -q 'cannot propagate BoolFault from a function returning IntegerFault' <<< "$stage1_output" \
    || fail "Stage1 selected the wrong ErrorSet family: $stage1_output"

echo "try imported argument TypeId smoke OK"
