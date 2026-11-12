#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
fixture="$REPO_ROOT/test/repro/named_argument_invalid_shape.elisa"
set +e
core="$("$ELISACORE_BIN" -emit semantic "$fixture" 2>&1)"
status=$?
set -e
[[ "$status" -ne 0 && $(grep -c 'parameter "value" is specified more than once' <<< "$core") == 2 && "$core" == *'function "needs_two" is missing argument for parameter "left"'* && $(grep -c 'argument 2 to "defaulted" expects i64, got bool' <<< "$core") == 1 ]] || {
  printf 'Unexpected Stage0 diagnostics:\n%s\n' "$core" >&2
  exit 1
}
report="$("$RPT" < "$fixture")"
[[ "$(printf '%s\n' "$report" | sed -n '/^D /p')" == 'D 4' && $(grep -c 'parameter "value" is specified more than once' <<< "$report") == 2 && "$report" == *'function "needs_two" is missing argument for parameter "left"'* && $(grep -c 'argument 2 to "defaulted" expects i64, got bool' <<< "$report") == 1 ]] || {
  printf 'Unexpected Stage1 diagnostics:\n%s\n' "$report" >&2
  exit 1
}
echo 'named argument invalid shape smoke OK'
