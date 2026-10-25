#!/usr/bin/env bash
# Protocol-precondition receiver classification must use the owning function offset.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
python3 "$REPO_ROOT/test/proofs/check_protocol_precondition_generic_owner.py"

FIXTURE="$REPO_ROOT/test/repro/protocol_precondition_generic_owner.elisa"
report="$("$RPT" < "$FIXTURE")"
grep -qE '^P 0$' <<< "$report" || {
    echo "protocol precondition generic owner smoke: fixture did not parse cleanly" >&2
    printf '%s\n' "$report" >&2
    exit 1
}
warnings="$(grep -Fc 'could not be proven statically at this call' <<< "$report" || true)"
[[ "$warnings" == 2 ]] && grep -qF '  L38 precondition of "check"' <<< "$report" && grep -qF '  L71 precondition of "check"' <<< "$report" || {
    echo "protocol precondition generic owner smoke: expected exact generic receiver warnings at lines 38 and 71" >&2
    printf '%s\n' "$report" >&2
    exit 1
}

echo "protocol precondition generic owner smoke OK"
