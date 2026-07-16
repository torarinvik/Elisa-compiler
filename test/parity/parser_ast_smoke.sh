#!/usr/bin/env bash
# Run the self-hosted parser's structural AST regression suite.  This is kept
# separate from parser_smoke.sh because `-emit test` builds and executes Elisa
# tests directly, while parser_smoke links the parser behind a small C driver.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"

output="$($ELISACORE_BIN -emit test "$REPO_ROOT/test/parity/parser_ast_test.elisa" 2>&1)"
printf '%s\n' "$output"

summary="$(printf '%s\n' "$output" | grep '\[ SUMMARY  \]' | tail -1)"
[[ -n "$summary" ]] || {
    echo "parser AST smoke FAILED: test summary was not emitted" >&2
    exit 1
}
printf '%s\n' "$summary" | grep -Eq 'failed=0$' || {
    echo "parser AST smoke FAILED: $summary" >&2
    exit 1
}

selected="$(printf '%s\n' "$summary" | sed -E 's/.* ([0-9]+) test\(s\) selected;.*/\1/')"
[[ "$selected" -ge 84 ]] || {
    echo "parser AST smoke FAILED: only $selected tests ran (expected at least 84)" >&2
    exit 1
}
echo "parser AST smoke OK: $selected structural tests passed" >&2
