#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
python3 "$REPO_ROOT/test/proofs/check_checked_get_owner_identity.py"

out=$(cat "$REPO_ROOT/test/repro/checked_get_owner_line_zero.elisa" | "$RPT")
grep -q '^P 0$' <<< "$out" || {
    echo "checked-get owner smoke FAIL: fixture did not parse cleanly: $out" >&2
    exit 1
}
count=$(grep -Fc 'implicit `else` index fallback has been removed' <<< "$out" || true)
if [[ "$count" -ne 1 ]]; then
    echo "checked-get owner smoke FAIL: a same-line checked get suppressed or duplicated its sibling's fallback diagnostic: $out" >&2
    exit 1
fi

consumer_out=$(cat "$REPO_ROOT/test/repro/checked_get_owner_consumers_line_zero.elisa" | "$RPT")
grep -q '^P 0$' <<< "$consumer_out" || {
    echo "checked-get owner smoke FAIL: consumer fixture did not parse cleanly: $consumer_out" >&2
    exit 1
}
oob_count=$(grep -Fc 'constant index 9 out of bounds for i64[4]' <<< "$consumer_out" || true)
optional_count=$(grep -Fc 'variable "plain" expects i64, got i64?' <<< "$consumer_out" || true)
unsafe_count=$(grep -Fc 'unchecked index requires' <<< "$consumer_out" || true)
if [[ "$oob_count" -ne 1 || "$optional_count" -ne 1 || "$unsafe_count" -ne 2 ]]; then
    echo "checked-get owner smoke FAIL: expected one sibling OOB, one sibling optional mismatch, and two sibling unchecked-index diagnostics: $consumer_out" >&2
    exit 1
fi

echo "checked-get owner smoke OK"
