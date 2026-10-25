#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT="$ROOT"
source "$ROOT/test/parity/build_parse_report.sh"

report="$("$RPT" < "$ROOT/test/repro/catch_relative_alias_target.elisa")"
grep -q '^D 1$' <<< "$report"
grep -q 'non-exhaustive catch over Fault; missing Fault.Missing' <<< "$report"

echo "relative Catch alias target smoke OK"
