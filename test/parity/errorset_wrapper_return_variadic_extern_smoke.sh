#!/usr/bin/env bash
# A variadic extern's primitive receiver must beat an incompatible extern sibling.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

fail() {
  echo "errorset wrapper variadic-extern smoke FAIL: $1" >&2
  exit 1
}

FIXTURE="$REPO_ROOT/test/repro/errorset_wrapper_return_variadic_extern.elisa"
set +e
stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1)"
stage0_status=$?
set -e
[[ "$stage0_status" -ne 0 ]] || fail "Stage0 accepted the mismatched selected variadic-extern family"
stage0_rows="$(printf '%s\n' "$stage0_output" \
  | sed -E -n 's#^.*:([0-9]+):[0-9]+[^:]*: return type expects.*$#L\1#p' \
  | LC_ALL=C sort)"

stage1_output="$("$RPT" < "$FIXTURE")"
stage1_rows="$(printf '%s\n' "$stage1_output" \
  | sed -E -n 's#^[[:space:]]*L([0-9]+) cannot propagate.*$#L\1#p' \
  | LC_ALL=C sort)"
expected_rows=$'L20'

[[ "$stage0_rows" == "$expected_rows" ]] \
  || fail "Stage0 did not select the i64 variadic extern's ErrorSet: $stage0_output"
[[ "$stage1_rows" == "$expected_rows" ]] \
  || fail "Stage1 did not preserve the i64 variadic extern's ErrorSet over the cstr sibling: $stage1_output"
grep -q 'cannot propagate.*SelectedFault' <<< "$stage1_output" \
  || fail "Stage1 did not report the selected i64 extern family: $stage1_output"
[[ $(grep -cF 'cannot propagate' <<< "$stage1_output") == 1 ]] \
  || fail "Stage1 emitted an unexpected ErrorSet diagnostic: $stage1_output"

echo "errorset wrapper variadic-extern smoke OK"
