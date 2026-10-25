#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT="$ROOT"
source "$ROOT/test/parity/build_parse_report.sh"

report="$("$RPT" < "$ROOT/test/repro/catch_relative_alias_target.elisa")"
diagnostic_count="$(grep -c 'non-exhaustive catch over Fault; missing Fault.Missing' <<< "$report" || true)"
if [[ "$diagnostic_count" != 3 ]]; then
  printf 'relative Catch alias target smoke failed; expected sibling and root alias targets to preserve their ErrorSet families:\n%s\n' "$report" >&2
  exit 1
fi

echo "relative Catch alias target smoke OK"
