#!/usr/bin/env bash
# Lambda raise checking must use the overload selected from the call arguments.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

FIXTURE="$REPO_ROOT/test/repro/lambda_raise_overloaded_callee.elisa"
set +e
stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1)"
stage0_status=$?
set -e
if [[ "$stage0_status" -eq 0 ]]; then
    echo "overloaded Lambda raise smoke expected Stage0 to reject the mismatched callback" >&2
    exit 1
fi
stage0_rows="$(printf '%s\n' "$stage0_output" \
    | sed -E -n 's#^.*:([0-9]+):[0-9]+-[0-9]+: raise cannot propagate tag.*$#L\1#p' \
    | LC_ALL=C sort)"
output="$("$RPT" < "$FIXTURE")"
expected_rows='L16'
if [[ "$stage0_rows" != "$expected_rows" ]] \
    || ! grep -q '^D 1$' <<< "$output" \
    || ! grep -q '^L16 raise cannot propagate tag' <<< "$output"; then
    printf 'overloaded Lambda raise smoke expected one mismatch at L16:\nStage0 rows: %s\nStage0 output:\n%s\nStage1 output:\n%s\n' \
        "$stage0_rows" "$stage0_output" "$output" >&2
    exit 1
fi

echo "overloaded Lambda raise smoke OK"
