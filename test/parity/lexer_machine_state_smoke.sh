#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"

output="$("$ELISACORE_BIN" -emit test "$REPO_ROOT/test/parity/lexer_machine_state_test.elisa" 2>&1)"
printf '%s\n' "$output"

summary="$(printf '%s\n' "$output" | grep '\[ SUMMARY  \]' | tail -1)"
[[ -n "$summary" ]] || {
    echo "lexer machine-state smoke FAILED: test summary was not emitted" >&2
    exit 1
}
printf '%s\n' "$summary" | grep -Eq 'failed=0$' || {
    echo "lexer machine-state smoke FAILED: $summary" >&2
    exit 1
}
echo "lexer machine-state smoke OK" >&2
