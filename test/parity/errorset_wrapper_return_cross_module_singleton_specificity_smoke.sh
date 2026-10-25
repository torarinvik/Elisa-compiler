#!/usr/bin/env bash
# A lone imported candidate does not activate Core's overload rewrite, so the local
# generic wins and EWR must ignore the unselected imported error family.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

FIXTURE="$REPO_ROOT/test/repro/errorset_wrapper_return_cross_module_singleton_specificity.elisa"
stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1)"
grep -qF 'return Consumer::choose(value)' <<< "$stage0_output" || {
  printf 'Core did not keep lexical Consumer.choose for the one-per-module control:\n%s\n' "$stage0_output" >&2
  exit 1
}
stage1_output="$("$RPT" < "$FIXTURE")"

grep -q '^P 0$' <<< "$stage1_output" || {
  printf 'Stage1 did not parse the EWR cross-module singleton control:\n%s\n' "$stage1_output" >&2
  exit 1
}
grep -q '^D 0$' <<< "$stage1_output" || {
  printf 'Stage1 imported the unselected Provider error family:\n%s\n' "$stage1_output" >&2
  exit 1
}
! grep -q 'cannot propagate' <<< "$stage1_output" || {
  printf 'Stage1 reported an unexpected propagation error:\n%s\n' "$stage1_output" >&2
  exit 1
}

printf 'errorset wrapper cross-module singleton scope control smoke OK\n'
