#!/usr/bin/env bash
# A damaged header must not consume the next function's return arrow.
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
out="$("$RPT" < "$REPO_ROOT/test/repro/parser_arrow_recovery.elisa")"
if ! grep -q '^P 1$' <<< "$out" || ! grep -q '^  0 L1 -$' <<< "$out"; then
    printf 'parser arrow recovery smoke FAILED:\n%s\n' "$out" >&2
    exit 1
fi
echo 'parser arrow recovery smoke OK'
