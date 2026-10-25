#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT
source "$REPO_ROOT/test/parity/build_parse_report.sh"

report="$("$RPT" < "$REPO_ROOT/test/repro/raise_static_import_branch.elisa")"
if grep -q 'raise cannot propagate tag' <<< "$report"; then
  printf 'raise static-import smoke failed; inactive provider was selected:\n%s\n' "$report" >&2
  exit 1
fi

raise_without_set_count="$(grep -c 'raise requires the current function to return an error union' <<< "$report" || true)"
if [[ "$raise_without_set_count" != 1 ]]; then
  printf 'raise static-scope smoke failed; only the active statement arm should be checked (got %s):\n%s\n' \
    "$raise_without_set_count" "$report" >&2
  exit 1
fi

printf 'raise static-import branch smoke OK\n'
