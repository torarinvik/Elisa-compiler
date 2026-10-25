#!/usr/bin/env bash
# A lone imported concrete declaration does not trigger Core's overload rewrite.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

FIXTURE="$REPO_ROOT/test/repro/errorset_wrapper_return_no_overload_set_scope_control.elisa"
set +e
stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1)"
stage0_status=$?
set -e
if [[ "$stage0_status" -ne 0 ]]; then
  printf 'EWR no-overload control expected Core to keep lexical Consumer.choose:\n' >&2
  printf '%s\n' "$stage0_output" >&2
  exit 1
fi

stage1_output="$("$RPT" < "$FIXTURE")"
grep -q '^P 0$' <<< "$stage1_output" || {
  printf 'Stage1 did not parse the EWR no-overload control:\n%s\n' "$stage1_output" >&2
  exit 1
}
grep -q '^D 0$' <<< "$stage1_output" || {
  printf 'Stage1 reported an unexpected EWR error for the lexical overload:\n%s\n' "$stage1_output" >&2
  exit 1
}
! grep -q 'cannot propagate' <<< "$stage1_output" || {
  printf 'EWR imported the unselected Provider error family:\n%s\n' "$stage1_output" >&2
  exit 1
}

printf 'errorset wrapper no-overload scope control smoke OK\n'
