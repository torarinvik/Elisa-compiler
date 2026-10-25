#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

FIXTURE="$REPO_ROOT/test/repro/ambiguous_error_variant_inaccessible_set.elisa"
report="$("$RPT" < "$FIXTURE")"
if ! grep -qF 'error variant "Shared" is ambiguous across sets' <<< "$report"; then
  printf 'ambiguous error variant visibility smoke failed; an inaccessible sibling set suppressed the ambiguity diagnostic:\n%s\n' "$report" >&2
  exit 1
fi

printf 'ambiguous error variant visibility smoke OK\n'
