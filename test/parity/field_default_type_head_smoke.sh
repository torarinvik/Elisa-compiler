#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
python3 "$REPO_ROOT/test/proofs/check_field_default_type_owner_identity.py"

out="$(cat "$REPO_ROOT/test/repro/field_default_type_mutable_parens.elisa" | "$RPT")"
grep -q '^P 0$' <<< "$out" || {
    echo "field default type-head smoke FAIL: fixture did not parse cleanly: $out" >&2
    exit 1
}
paren_count="$(grep -Fc 'default value for struct field "paren_bad" expects bool, got int' <<< "$out" || true)"
mutable_paren_count="$(grep -Fc 'default value for struct field "mutable_paren_bad" expects bool, got int' <<< "$out" || true)"
if [[ "$paren_count" -ne 1 || "$mutable_paren_count" -ne 1 ]]; then
    echo "field default type-head smoke FAIL: parenthesized primitive mismatches were not both reported: $out" >&2
    exit 1
fi

echo "field default type-head smoke OK"
