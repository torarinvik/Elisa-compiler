#!/usr/bin/env bash
# A later argument type error does not replace Core's selected overload family.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

fail() {
  echo "errorset wrapper later-argument mismatch rank smoke FAIL: $1" >&2
  exit 1
}

FIXTURE="$REPO_ROOT/test/repro/errorset_wrapper_return_later_argument_mismatch_rank.elisa"
set +e
stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1)"
stage0_status=$?
set -e
[[ "$stage0_status" -ne 0 ]] || fail "Stage0 accepted the mismatched later argument"
grep -qE 'argument 2 .*expects bool, got i64' <<< "$stage0_output" \
  || fail "Stage0 did not report the concrete overload's later-argument mismatch: $stage0_output"
stage0_rows="$(printf '%s\n' "$stage0_output" \
  | sed -E -n 's#^.*:([0-9]+):[0-9]+[^:]*: return type expects.*$#L\1#p' \
  | LC_ALL=C sort)"

stage1_output="$("$RPT" < "$FIXTURE")"
stage1_rows="$(printf '%s\n' "$stage1_output" \
  | sed -E -n 's#^[[:space:]]*L([0-9]+) cannot propagate.*$#L\1#p' \
  | LC_ALL=C sort)"
expected_rows=$'L22'

[[ "$stage0_rows" == "$expected_rows" ]] \
  || fail "Stage0 did not retain ConcreteFault after the later-argument error: $stage0_output"
[[ "$stage1_rows" == "$expected_rows" ]] \
  || fail "Stage1 lost the selected ConcreteFault family after the later-argument error: $stage1_output"
[[ $(grep -cF 'cannot propagate' <<< "$stage1_output") == 1 ]] \
  || fail "Stage1 reported an unexpected ErrorSet family: $stage1_output"

echo "errorset wrapper later-argument mismatch rank smoke OK"
