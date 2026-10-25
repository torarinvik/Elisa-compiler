#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT
source "$REPO_ROOT/test/parity/build_parse_report.sh"

report="$("$RPT" < "$REPO_ROOT/test/repro/raise_declaration_offset_identity.elisa")"
requires_error_union_count="$(grep -c 'raise requires the current function to return an error union' <<< "$report" || true)"
if [[ "$requires_error_union_count" != "1" ]]; then
  printf 'raise declaration-offset smoke failed; expected the same-line non-error overload to keep its own return metadata:\n%s\n' "$report" >&2
  exit 1
fi

printf 'raise declaration-offset identity smoke OK\n'
