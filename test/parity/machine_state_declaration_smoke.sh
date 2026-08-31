#!/usr/bin/env bash
# State payload names are scalarized into shared locals. Reject duplicate states, duplicate
# fields, and conflicting types before that lowering can silently overwrite one declaration.
set -uo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/structpy-tree}"
export ELISA_CORE
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

fail() { echo "machine state declaration smoke FAIL: $1" >&2; exit 1; }

expect_diagnostics() {
    local label="$1"
    local source="$2"
    local out
    out="$(printf '%b' "$source" | "$RPT")"
    echo "$out" | grep -q '^D 0$' && fail "$label was accepted: $out"
}

expect_diagnostics "duplicate state" 'def run() -> i64:
    machine over 0:
        state Run
        state Run
        start Run
        Run, _:
            break
    return 0
'

expect_diagnostics "duplicate field" 'def run() -> i64:
    machine over 0:
        state Run(value: i64, value: i64)
        start Run(0, 0)
        Run(_, _), _:
            break
    return 0
'

expect_diagnostics "conflicting shared field type" 'def run() -> i64:
    machine over 0:
        state First(value: i64)
        state Second(value: bool)
        start First(0)
        First(value), _:
            -> Second(false)
        Second(value), _:
            break
    return 0
'

echo "machine state declaration smoke OK: duplicate states/fields and conflicting shared types refused"
