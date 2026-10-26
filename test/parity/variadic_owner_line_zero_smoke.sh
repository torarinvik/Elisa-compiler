#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
python3 "$REPO_ROOT/test/proofs/check_variadic_owner_identity.py"

out="$(cat "$REPO_ROOT/test/repro/variadic_owner_line_zero.elisa" | "$RPT")"
grep -q '^P 0$' <<< "$out" || {
    echo "variadic owner smoke FAIL: fixture did not parse cleanly: $out" >&2
    exit 1
}
count="$(grep -Fc 'function "fixed" expects 1 arguments, got 2' <<< "$out" || true)"
if [[ "$count" -ne 1 ]]; then
    echo "variadic owner smoke FAIL: fixed sibling inherited its same-line variadic marker: $out" >&2
    exit 1
fi

echo "variadic owner smoke OK"
