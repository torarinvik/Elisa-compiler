#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT="$ROOT"
source "$ROOT/test/parity/build_parse_report.sh"

report="$("$RPT" < "$ROOT/test/repro/catch_static_alias_branch.elisa")"
diagnostic_count="$(grep -c 'non-exhaustive catch over Fault; missing Fault.Missing' <<< "$report" || true)"
if [[ "$diagnostic_count" != 2 ]]; then
  printf 'Catch static-alias smoke failed; expected both selected-provider catches to report its missing variant:\n%s\n' "$report" >&2
  exit 1
fi
if grep -q 'WrongOnly' <<< "$report"; then
  printf 'Catch static-alias smoke selected the inactive provider:\n%s\n' "$report" >&2
  exit 1
fi

printf 'Catch static-alias smoke OK\n'
