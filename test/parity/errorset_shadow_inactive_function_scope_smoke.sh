#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT
source "$REPO_ROOT/test/parity/build_parse_report.sh"

report="$("$RPT" < "$REPO_ROOT/test/repro/errorset_shadow_inactive_function_scope.elisa")"
warning_count="$(grep -c 'shadows the declared error set' <<< "$report" || true)"
if [[ "$warning_count" != 1 ]]; then
  printf 'ErrorSet static-scope smoke failed; only the active function should warn (got %s):\n%s\n' \
    "$warning_count" "$report" >&2
  exit 1
fi

printf 'ErrorSet inactive-function shadow smoke OK\n'
