#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
fixture="$REPO_ROOT/test/repro/callback_qualified_error_family.elisa"
set +e
core_output="$("$ELISACORE_BIN" -emit semantic "$fixture" 2>&1)"
core_status=$?
set -e
[[ "$core_status" -ne 0 && "$core_output" == *'cannot propagate A.Fault from a function returning B.Fault'* ]] || {
  printf 'Stage0 did not distinguish the callback error families:\n%s\n' "$core_output" >&2
  exit 1
}
report="$("$RPT" < "$fixture")"
[[ "$(printf '%s\n' "$report" | sed -n '/^D /p')" == 'D 1' && "$report" == *'L11 cannot propagate Fault from a function returning Fault'* ]] || {
  printf 'Stage1 did not distinguish the callback error families:\n%s\n' "$report" >&2
  exit 1
}
echo 'qualified callback error family smoke OK'
