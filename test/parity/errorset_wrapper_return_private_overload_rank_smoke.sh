#!/usr/bin/env bash
# EWR must decline private receiver-ranked winners, keep weaker private overloads from
# hiding a public concrete winner, and ignore private overloads that cannot match.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

FIXTURE="$REPO_ROOT/test/repro/errorset_wrapper_return_private_overload_rank.elisa"
set +e
stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1)"
stage0_status=$?
set -e
[[ "$stage0_status" -ne 0 ]] || {
  printf 'EWR private-overload rank smoke expected Core diagnostics:\n%s\n' "$stage0_output" >&2
  exit 1
}
grep -qF 'is private to module' <<< "$stage0_output" || {
  printf 'Core did not select and reject the inaccessible private winner:\n%s\n' "$stage0_output" >&2
  exit 1
}
stage0_rows="$(printf '%s\n' "$stage0_output" \
  | sed -E -n 's#^.*:([0-9]+):[0-9]+[^:]*: return type expects.*$#L\1#p' \
  | LC_ALL=C sort)"
stage1_output="$("$RPT" < "$FIXTURE")"
stage1_rows="$(printf '%s\n' "$stage1_output" \
  | sed -E -n 's#^[[:space:]]*L([0-9]+) cannot propagate.*$#L\1#p' \
  | LC_ALL=C sort)"
expected_rows=$'L24\nL57\nL60\nL63'

[[ "$stage0_rows" == "$expected_rows" ]] || {
  printf 'Core return-type diagnostics differ for the rank and incompatible-private controls:\n%s\n%s\n' "$stage0_rows" "$stage0_output" >&2
  exit 1
}
[[ "$stage1_rows" == "$expected_rows" ]] || {
  printf 'Stage1 EWR diagnostics differ; private rank blockers and incompatible-private fallbacks must match Core:\n%s\n%s\n' "$stage1_rows" "$stage1_output" >&2
  exit 1
}

printf 'errorset wrapper private-overload rank smoke OK\n'
