#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT
source "$REPO_ROOT/test/parity/build_parse_report.sh"

report="$("$RPT" < "$REPO_ROOT/test/repro/error_union_overload_offset_zero.elisa")"
unhandled_count="$(grep -c 'error union result must be handled' <<< "$report" || true)"
if [[ "$unhandled_count" != "1" ]]; then
  printf 'ErrorUnion overload offset-zero smoke failed; expected only the fallible overload call to be diagnosed:\n%s\n' "$report" >&2
  exit 1
fi

printf 'ErrorUnion overload offset-zero smoke OK\n'
