#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
fixture="$REPO_ROOT/test/repro/forwarding_local_module_shadow.elisa"
set +e
core_output="$("$ELISACORE_BIN" -emit semantic "$fixture" 2>&1)"
core_status=$?
set -e
[[ "$core_status" -ne 0 && "$core_output" == *'missing argument for parameter "required"'* ]] || {
  printf 'Stage0 did not diagnose the missing local parameter:\n%s\n' "$core_output" >&2
  exit 1
}
[[ "$core_output" == *'call argument forwarding `..` is not supported for variadic function'* ]] || {
  printf 'Stage0 did not reject forwarding to the local variadic function:\n%s\n' "$core_output" >&2
  exit 1
}
report="$("$RPT" < "$fixture")"
[[ "$(printf '%s\n' "$report" | sed -n '/^D /p')" == 'D 2' && "$report" == *'function "target" is missing argument for parameter "required"'* && "$report" == *'call argument forwarding `..` is not supported for variadic function "spread"'* ]] || {
  printf 'Stage1 did not resolve forwarded calls to the local declarations:\n%s\n' "$report" >&2
  exit 1
}
echo 'forwarding local module shadow smoke OK'
