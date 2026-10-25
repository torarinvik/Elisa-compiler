#!/usr/bin/env bash
# Unknown-type and protocol classification must use the owning declaration offset.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
python3 "$REPO_ROOT/test/proofs/check_unknown_type_generic_owner.py"

FIXTURE="$REPO_ROOT/test/repro/unknown_type_generic_owner.elisa"
report="$("$RPT" < "$FIXTURE")"
grep -qE '^P 0$' <<< "$report" || {
    echo "unknown type generic owner smoke: fixture did not parse cleanly" >&2
    printf '%s\n' "$report" >&2
    exit 1
}
unknown_count="$(grep -Fc 'unknown type "' <<< "$report" || true)"
protocol_count="$(grep -Fc 'is a constraint, not a concrete value type' <<< "$report" || true)"
if [[ "$unknown_count" != 5 || "$protocol_count" != 2 ]] || grep -qF 'unknown type "Z"' <<< "$report"; then
    echo "unknown type generic owner smoke: expected 5 exact-owner unknowns, 2 concrete protocol errors, and no one-letter error" >&2
    printf '%s\n' "$report" >&2
    exit 1
fi

echo "unknown type generic owner smoke OK"
