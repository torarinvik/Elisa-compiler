#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT
source "$REPO_ROOT/test/parity/build_parse_report.sh"

report="$("$RPT" < "$REPO_ROOT/test/repro/raise_late_import_offset_zero.elisa")"
if grep -Eq 'raise cannot propagate tag|raise requires the current function to return an error union' <<< "$report"; then
  printf 'raise import-order smoke failed; a later #line-reset import was treated as visible to a byte-zero function:\n%s\n' "$report" >&2
  exit 1
fi

printf 'raise late-import offset-zero smoke OK\n'
