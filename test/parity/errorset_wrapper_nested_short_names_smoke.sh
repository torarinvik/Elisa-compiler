#!/usr/bin/env bash
# Error-tag short names retain nested module and family components after the
# first module segment; a single matching final tag is not sufficient.
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

fixture="$REPO_ROOT/test/repro/errorset_wrapper_nested_short_names.elisa"
set +e
stage0_output="$("$ELISACORE_BIN" -emit semantic "$fixture" 2>&1)"
stage0_status=$?
set -e
stage0_rows="$(printf '%s\n' "$stage0_output" | sed -E -n 's#^.*:([0-9]+):[0-9]+[^:]*: return type expects.*$#L\1#p' | LC_ALL=C sort)"
stage1_output="$("$RPT" < "$fixture")"
stage1_rows="$(printf '%s\n' "$stage1_output" | sed -E -n 's#^[[:space:]]*L([0-9]+) (cannot propagate|return type expects error\[).*$#L\1#p' | LC_ALL=C sort)"
expected=$'L20\nL22'
[[ "$stage0_status" -ne 0 && "$stage0_rows" == "$expected" && "$stage1_rows" == "$expected" && "$stage1_output" == *$'P 0\nD 2\n'* ]] || {
    printf 'nested short-name parity failed:\nStage0: %s\nStage1: %s\n' "$stage0_output" "$stage1_output" >&2
    exit 1
}
echo 'nested error short-name parity OK'
