#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
fixture="$REPO_ROOT/test/repro/named_literal_argument_types.elisa"
set +e
core_output="$("$ELISACORE_BIN" -emit semantic "$fixture" 2>&1)"
core_status=$?
set -e
left='argument 1 to "sink" expects bool, got int'
right='argument 2 to "sink" expects i64, got bool'
[[ "$core_status" -ne 0 && "$core_output" == *"$left"* && "$core_output" == *"$right"* ]] || {
  printf 'Stage0 did not reject both mismatched named arguments:\n%s\n' "$core_output" >&2
  exit 1
}
report="$("$RPT" < "$fixture")"
[[ "$(printf '%s\n' "$report" | sed -n '/^D /p')" == 'D 2' && "$report" == *"L5 $left"* && "$report" == *"L5 $right"* ]] || {
  printf 'Stage1 did not check the named arguments by formal position:\n%s\n' "$report" >&2
  exit 1
}
echo 'named literal argument types smoke OK'
