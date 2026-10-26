#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
python3 "$REPO_ROOT/test/proofs/check_typestate_ref_param_owner_identity.py"

out="$(cat "$REPO_ROOT/test/repro/typestate_ref_param_owner_line_zero.elisa" | "$RPT")"
grep -q '^P 0$' <<< "$out" || {
    echo "typestate ref-param owner smoke FAIL: fixture did not parse cleanly: $out" >&2
    exit 1
}
count="$(grep -Fc 'ensures on function "second" requires "value" to resolve to a ref target for refstate effects' <<< "$out" || true)"
if [[ "$count" -ne 1 ]]; then
    echo "typestate ref-param owner smoke FAIL: non-ref sibling inherited its same-line ref marker: $out" >&2
    exit 1
fi

echo "typestate ref-param owner smoke OK"
