#!/usr/bin/env bash
# Variadic positional extras retain the selected family; invalid named/forwarded
# shapes contribute no family after Core diagnoses the selected variadic winner.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

fail() {
  echo "errorset wrapper variadic-arguments smoke FAIL: $1" >&2
  exit 1
}

FIXTURE="$REPO_ROOT/test/repro/errorset_wrapper_return_variadic_arguments.elisa"
set +e
stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1)"
stage0_status=$?
set -e
[[ "$stage0_status" -ne 0 ]] || fail "Stage0 accepted the family mismatch and invalid variadic calls"
grep -Fq 'named arguments and explicit bundle applications are not supported for variadic function "collect"' <<< "$stage0_output" \
  || fail "Stage0 did not reject named arguments to the selected variadic function: $stage0_output"
grep -Fq 'call argument forwarding `..` is not supported for variadic function "collect"' <<< "$stage0_output" \
  || fail "Stage0 did not reject forwarding to the selected variadic function: $stage0_output"
stage0_rows="$(printf '%s\n' "$stage0_output" \
  | sed -E -n 's#^.*:([0-9]+):[0-9]+[^:]*: return type expects.*$#L\1#p' \
  | LC_ALL=C sort)"

stage1_output="$("$RPT" < "$FIXTURE")"
stage1_rows="$(printf '%s\n' "$stage1_output" \
  | sed -E -n 's#^[[:space:]]*L([0-9]+) cannot propagate.*$#L\1#p' \
  | LC_ALL=C sort)"
expected_rows=$'L24'

[[ "$stage0_rows" == "$expected_rows" ]] \
  || fail "Stage0 did not retain the positional variadic family's mismatch alone: $stage0_output"
[[ "$stage1_rows" == "$expected_rows" ]] \
  || fail "Stage1 dropped the positional variadic family or propagated an invalid shape: $stage1_output"
[[ $(grep -cF 'cannot propagate' <<< "$stage1_output") == 1 ]] \
  || fail "Stage1 emitted a family diagnostic for an invalid variadic shape: $stage1_output"
grep -q '^D 1$' <<< "$stage1_output" \
  || fail "Stage1 did not report exactly one selected-family mismatch: $stage1_output"

echo "errorset wrapper variadic-arguments smoke OK"
