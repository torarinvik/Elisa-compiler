#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT="$ROOT"
source "$ROOT/test/parity/build_parse_report.sh"

report="$("$RPT" < "$ROOT/test/repro/catch_nested_global_alias.elisa")"
diagnostic_count="$(grep -c 'non-exhaustive catch over Fault; missing Fault.Missing' <<< "$report" || true)"
if [[ "$diagnostic_count" != 1 ]]; then
  printf 'Catch nested-global-alias smoke failed; expected the root catch to resolve its nested module alias:\n%s\n' "$report" >&2
  exit 1
fi

if grep -Eq 'undefined identifier .NestedGlobal.|undefined module member .NestedGlobal.' <<< "$report"; then
  printf 'Catch nested-global-alias smoke failed; the alias was treated as unavailable from root:\n%s\n' "$report" >&2
  exit 1
fi

printf 'Catch nested-global-alias smoke OK\n'
