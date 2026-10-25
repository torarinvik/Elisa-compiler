#!/usr/bin/env bash
# Nested direct-call receiver types and forwarded Try calls must preserve safe family lookup.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

fail() {
  echo "try nested and forwarded calls smoke FAIL: $1" >&2
  exit 1
}

FIXTURE="$REPO_ROOT/test/repro/try_overload_nested_and_forwarded_calls.elisa"
set +e
stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1)"
stage0_status=$?
set -e
[[ "$stage0_status" -ne 0 ]] || fail "Stage0 missed the nested-call or forwarded-singleton wrong-family controls"
stage0_rows="$(printf '%s\n' "$stage0_output" \
  | sed -E -n 's#^.*:([0-9]+):[0-9]+[^:]*: cannot propagate.*$#L\1#p' \
  | LC_ALL=C sort)"
expected_rows=$'L27\nL36'
[[ "$stage0_rows" == "$expected_rows" ]] \
  || fail "Stage0 did not select the public nested-call family and preserve forwarded singleton inference: $stage0_output"
if grep -qE 'try requires a fallible expression|is private to module|undefined identifier' <<< "$stage0_output"; then
  fail "Stage0 lost a private-call suppression or forwarded family boundary: $stage0_output"
fi

stage1_output="$("$RPT" < "$FIXTURE")"
stage1_rows="$(printf '%s\n' "$stage1_output" \
  | sed -E -n 's#^[[:space:]]*L([0-9]+) cannot propagate.*$#L\1#p' \
  | LC_ALL=C sort)"
grep -q '^D 2$' <<< "$stage1_output" \
  || fail "Stage1 did not report exactly the nested-call and forwarded-singleton controls: $stage1_output"
[[ "$stage1_rows" == "$expected_rows" ]] \
  || fail "Stage1 did not preserve the same public family controls: $stage1_output"
if grep -qE 'try requires a fallible expression|is private to module|undefined identifier' <<< "$stage1_output"; then
  fail "Stage1 lost a private-call suppression or forwarded family boundary: $stage1_output"
fi

echo "try nested and forwarded calls smoke OK"
