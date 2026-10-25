#!/usr/bin/env bash
# EWR scope selection must keep lexical parent declarations ahead of nested wildcards.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

FIXTURE="$REPO_ROOT/test/repro/errorset_wrapper_return_nested_wildcard_scope_control.elisa"
"$ELISACORE_BIN" -emit semantic "$FIXTURE" >/dev/null
stage1_output="$("$RPT" < "$FIXTURE")"
grep -q '^P 0$' <<< "$stage1_output" || {
  printf 'Stage1 did not parse the nested-wildcard scope control:\n%s\n' "$stage1_output" >&2
  exit 1
}
grep -q '^D 0$' <<< "$stage1_output" || {
  printf 'EWR did not preserve Consumer.wrap over Api.wrap:\n%s\n' "$stage1_output" >&2
  exit 1
}
! grep -q 'cannot propagate' <<< "$stage1_output" || {
  printf 'EWR selected the nested wildcard over its lexical parent:\n%s\n' "$stage1_output" >&2
  exit 1
}

printf 'errorset wrapper nested-wildcard scope control smoke OK\n'
