#!/usr/bin/env bash
# Run the self-hosted parser's structural AST regression suite.  This is kept
# separate from parser_smoke.sh because `-emit test` builds and executes Elisa
# tests directly, while parser_smoke links the parser behind a small C driver.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"

run_parser_test_file() {
    local fixture="$1" label="$2" minimum="$3" output summary selected

    if ! output="$("$ELISACORE_BIN" -emit test "$REPO_ROOT/test/parity/$fixture" 2>&1)"; then
        printf '%s\n' "$output"
        echo "parser AST smoke FAILED: $label did not run" >&2
        exit 1
    fi
    printf '%s\n' "$output"

    summary="$(printf '%s\n' "$output" | grep '\[ SUMMARY  \]' | tail -1)"
    [[ -n "$summary" ]] || {
        echo "parser AST smoke FAILED: $label did not emit a test summary" >&2
        exit 1
    }
    grep -Eq 'failed=0$' <<< "$summary" || {
        echo "parser AST smoke FAILED: $label: $summary" >&2
        exit 1
    }

    selected="$(printf '%s\n' "$summary" | sed -E 's/.* ([0-9]+) test\(s\) selected;.*/\1/')"
    [[ "$selected" -ge "$minimum" ]] || {
        echo "parser AST smoke FAILED: $label ran only $selected tests (expected at least $minimum)" >&2
        exit 1
    }
    echo "parser AST smoke OK: $selected $label tests passed" >&2
}

run_parser_test_file parser_ast_test.elisa "structural" 124
run_parser_test_file parser_guard_condition_list_unit.elisa "guard parser/formatter unit" 4
run_parser_test_file parser_guard_condition_list.elisa "guard full-parser integration" 3
