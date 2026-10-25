#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT
source "$REPO_ROOT/test/parity/build_parse_report.sh"

report="$("$RPT" < "$REPO_ROOT/test/repro/error_union_static_import_branches.elisa")"
unhandled_count="$(grep -c 'error union result must be handled' <<< "$report" || true)"
if [[ "$unhandled_count" != 1 ]]; then
  printf 'error-union static-branch smoke failed; expected only the active fallible overload to require handling:\n%s\n' "$report" >&2
  exit 1
fi

printf 'error-union static-import smoke OK\n'
