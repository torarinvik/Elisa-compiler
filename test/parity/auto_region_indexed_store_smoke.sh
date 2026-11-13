#!/usr/bin/env bash
# A local backing array cannot be stored into a caller-owned slot; local and
# explicitly same-region storage remain valid.
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
out="$("$RPT" < "$REPO_ROOT/test/repro/auto_region_indexed_store.elisa")"
if ! grep -q '^P 0$' <<< "$out" || ! grep -q '^D 1$' <<< "$out" ||
   ! grep -q '^  L4 value escapes its `in auto:` scope via store into longer-lived storage' <<< "$out" ||
   ! grep -q '^  note: value backed by a short-lived region escapes via store' <<< "$out"; then
    printf 'auto region indexed store smoke FAILED:\n%s\n' "$out" >&2
    exit 1
fi
echo 'auto region indexed store smoke OK'
