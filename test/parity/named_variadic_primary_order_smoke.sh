#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
fixture="$REPO_ROOT/test/repro/named_variadic_primary_order.elisa"
set +e
core="$("$ELISACORE_BIN" -emit semantic "$fixture" 2>&1)"
status=$?
set -e
expected='named arguments and explicit bundle applications are not supported for variadic function "variadic_first"'
unique='named arguments and explicit bundle applications are not supported for variadic function "only"'
[[ "$status" -ne 0 && $(grep -cF "$expected" <<< "$core") == 1 && $(grep -cF "$unique" <<< "$core") == 2 && "$core" != *'variadic function "fixed_first"'* && "$core" != *'variadic function "conditional"'* ]] || {
  printf 'Unexpected Stage0 diagnostics:\n%s\n' "$core" >&2
  exit 1
}
report="$("$RPT" < "$fixture")"
[[ "$(printf '%s\n' "$report" | sed -n '/^D /p')" == 'D 3' && "$report" == *"L17 $expected"* && $(grep -cF "$unique" <<< "$report") == 2 ]] || {
  printf 'Unexpected Stage1 diagnostics:\n%s\n' "$report" >&2
  exit 1
}
echo 'named variadic primary order smoke OK'
