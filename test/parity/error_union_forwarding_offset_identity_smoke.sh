#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT
source "$REPO_ROOT/test/parity/build_parse_report.sh"

report="$("$RPT" < "$REPO_ROOT/test/repro/error_union_forwarding_offset_identity.elisa")"
unhandled_count="$(grep -c 'error union result must be handled' <<< "$report" || true)"
if [[ "$unhandled_count" != "1" ]] || ! grep -q 'expects 1 arguments, got 0\|wrong number of arguments' <<< "$report"; then
  printf 'ErrorUnion forwarding offset smoke failed; expected one fallible forwarded call and an arity diagnostic for the same-line non-forwarded call:\n%s\n' "$report" >&2
  exit 1
fi

printf 'ErrorUnion forwarding offset smoke OK\n'
