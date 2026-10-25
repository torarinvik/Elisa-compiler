#!/usr/bin/env bash
# A same-line generic parameter must not classify a sibling concrete field access.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
python3 "$REPO_ROOT/test/proofs/check_field_access_generic_owner.py"

FIXTURE="$REPO_ROOT/test/repro/field_access_generic_owner.elisa"
report="$("$RPT" < "$FIXTURE")"
grep -qE '^P 0$' <<< "$report" || {
    echo "field access generic owner smoke: fixture did not parse cleanly" >&2
    printf '%s\n' "$report" >&2
    exit 1
}
warnings="$(grep -Fc 'field access requires struct type, got T' <<< "$report" || true)"
[[ "$warnings" == 1 ]] || {
    echo "field access generic owner smoke: expected only the generic owner's field diagnostic" >&2
    printf '%s\n' "$report" >&2
    exit 1
}

echo "field access generic owner smoke OK"
