#!/usr/bin/env bash
# Exercise no-op and captured-loop structural behavior of the semantic checker view.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"

output="$("$ELISACORE_BIN" -emit test "$REPO_ROOT/test/parity/semantic_loop_view_test.elisa" 2>&1)"
printf '%s\n' "$output"

summary="$(printf '%s\n' "$output" | grep '\[ SUMMARY  \]' | tail -1)"
[[ -n "$summary" ]] || {
    echo "semantic loop view smoke FAILED: no test summary" >&2
    exit 1
}
grep -Eq 'failed=0$' <<< "$summary" || {
    echo "semantic loop view smoke FAILED: $summary" >&2
    exit 1
}
selected="$(printf '%s\n' "$summary" | sed -E 's/.* ([0-9]+) test\(s\) selected;.*/\1/')"
[[ "$selected" -ge 3 ]] || {
    echo "semantic loop view smoke FAILED: only $selected tests ran (expected at least 3)" >&2
    exit 1
}

echo "semantic loop view smoke OK: $selected tests passed" >&2
