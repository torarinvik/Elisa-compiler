#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT
source "$REPO_ROOT/test/parity/build_parse_report.sh"

report="$("$RPT" < "$REPO_ROOT/test/repro/error_union_static_import_offset_zero.elisa")"
if ! grep -q 'error union result must be handled' <<< "$report"; then
  printf 'ErrorUnion offset-zero smoke failed; the first-byte import was hidden by the #line collision:\n%s\n' "$report" >&2
  exit 1
fi

printf 'ErrorUnion offset-zero import smoke OK\n'
