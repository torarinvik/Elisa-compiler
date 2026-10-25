#!/usr/bin/env bash
# A missing-parameter infallible sibling must not shadow Core's named defaulted winner.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

fail() {
  echo "errorset wrapper named-call infallible-underflow smoke FAIL: $1" >&2
  exit 1
}

FIXTURE="$REPO_ROOT/test/repro/errorset_wrapper_return_named_call_infallible_underflow.elisa"
set +e
stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1)"
stage0_status=$?
set -e
[[ "$stage0_status" -ne 0 ]] || fail "Stage0 accepted the wrapper's different ErrorSet"
stage0_rows="$(printf '%s\n' "$stage0_output" \
  | sed -E -n 's#^.*:([0-9]+):[0-9]+[^:]*: return type expects.*$#L\1#p' \
  | LC_ALL=C sort)"

stage1_output="$("$RPT" < "$FIXTURE")"
stage1_rows="$(printf '%s\n' "$stage1_output" \
  | sed -E -n 's#^[[:space:]]*L([0-9]+) cannot propagate.*$#L\1#p' \
  | LC_ALL=C sort)"
expected_rows=$'L22'

[[ "$stage0_rows" == "$expected_rows" ]] \
  || fail "Stage0 did not keep the named fallible defaulted primary: $stage0_output"
[[ "$stage1_rows" == "$expected_rows" ]] \
  || fail "Stage1 let the unresolved infallible sibling shadow the selected family: $stage1_output"
[[ $(grep -cF 'cannot propagate' <<< "$stage1_output") == 1 ]] \
  || fail "Stage1 emitted an unexpected ErrorSet diagnostic: $stage1_output"

echo "errorset wrapper named-call infallible-underflow smoke OK"
