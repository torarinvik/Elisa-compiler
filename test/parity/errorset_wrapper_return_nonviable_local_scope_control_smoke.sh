#!/usr/bin/env bash
# EWR must not borrow an imported family when Core binds an incompatible local name.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

FIXTURE="$REPO_ROOT/test/repro/errorset_wrapper_return_nonviable_local_scope_control.elisa"
set +e
stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1)"
stage0_status=$?
set -e
[[ "$stage0_status" -ne 0 ]] || {
  printf 'EWR nonviable-local control expected Core argument diagnostics:\n%s\n' "$stage0_output" >&2
  exit 1
}
stage0_rows="$(printf '%s\n' "$stage0_output" \
  | sed -E -n 's#^.*:([0-9]+):[0-9]+[^:]*: return type expects.*$#L\1#p' \
  | LC_ALL=C sort)"
stage0_argument_rows="$(printf '%s\n' "$stage0_output" \
  | sed -E -n 's#^.*:([0-9]+):[0-9]+[^:]*: .*expects bool, got i64.*$#L\1#p' \
  | LC_ALL=C sort)"
stage1_output="$("$RPT" < "$FIXTURE")"
stage1_rows="$(printf '%s\n' "$stage1_output" \
  | sed -E -n 's#^[[:space:]]*L([0-9]+) cannot propagate.*$#L\1#p' \
  | LC_ALL=C sort)"
stage1_argument_rows="$(printf '%s\n' "$stage1_output" \
  | sed -E -n 's#^[[:space:]]*L([0-9]+) argument [0-9]+ to "(choose|plain)" expects bool, got i64.*$#L\1#p' \
  | LC_ALL=C sort)"

[[ -z "$stage0_rows" ]] || {
  printf 'Core unexpectedly selected an imported family for the local name:\n%s\n%s\n' "$stage0_rows" "$stage0_output" >&2
  exit 1
}
[[ "$stage0_argument_rows" == $'L28\nL31' ]] || {
  printf 'Core did not bind both local bool callables and report their i64 argument mismatches:\n%s\n%s\n' "$stage0_argument_rows" "$stage0_output" >&2
  exit 1
}
[[ "$stage1_argument_rows" == $'L28\nL31' ]] || {
  printf 'Stage1 did not retain both local bool-callable argument mismatches:\n%s\n%s\n' "$stage1_argument_rows" "$stage1_output" >&2
  exit 1
}
[[ -z "$stage1_rows" ]] || {
  printf 'EWR borrowed an imported family after Core bound the local name:\n%s\n%s\n' "$stage1_rows" "$stage1_output" >&2
  exit 1
}

printf 'errorset wrapper nonviable-local scope control smoke OK\n'
