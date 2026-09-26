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
grep -Eq 'failed=0$' <<< "$summary" || {
    echo "lexer machine-state smoke FAILED: $summary" >&2
    exit 1
}
echo "lexer machine-state smoke OK" >&2

stage1_bin="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
[[ -x "$stage1_bin" ]] || {
    echo "lexer machine-state smoke FAILED: stage1 compiler unavailable: $stage1_bin" >&2
    exit 1
}
stage1_output="$(ELISA_STAGE1_BIN="$stage1_bin" ELISACORE_BIN="$ELISACORE_BIN" \
    bash "$REPO_ROOT/scripts/elisac_stage1.sh" -emit test \
    "$REPO_ROOT/test/parity/lexer_machine_state_test.elisa" 2>&1)"
printf '%s\n' "$stage1_output"

stage1_summary="$(printf '%s\n' "$stage1_output" | grep '\[ SUMMARY  \]' | tail -1)"
[[ -n "$stage1_summary" ]] || {
    echo "lexer machine-state smoke FAILED: stage1 test summary was not emitted" >&2
    exit 1
}
grep -Eq 'failed=0$' <<< "$stage1_summary" || {
    echo "lexer machine-state smoke FAILED under stage1: $stage1_summary" >&2
    exit 1
}
echo "lexer machine-state smoke OK under stage1" >&2
