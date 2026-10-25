#!/usr/bin/env bash
# Same-line functions must not share generic bound ownership in the associated-index checker.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
python3 "$REPO_ROOT/test/proofs/check_assoc_index_generic_owner_identity.py"

FIXTURE="$REPO_ROOT/test/repro/assoc_index_generic_owner_line0.elisa"
report="$("$RPT" < "$FIXTURE")"
count="$(grep -Fc 'unchecked index requires can[Unsafe]' <<< "$report" || true)"
[[ "$count" == 1 ]] || {
    echo "associated-index generic owner smoke: expected one warning from actual_bound, got $count" >&2
    printf '%s\n' "$report" >&2
    exit 1
}

echo "associated-index generic owner line-zero smoke OK"
