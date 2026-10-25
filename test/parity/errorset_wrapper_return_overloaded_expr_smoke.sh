#!/usr/bin/env bash
# EWR must resolve nested overload calls from their argument types.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

FIXTURE="$REPO_ROOT/test/repro/errorset_wrapper_return_overloaded_expr.elisa"
set +e
stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1)"
stage0_status=$?
set -e
if [[ "$stage0_status" -eq 0 ]]; then
    echo "EWR overloaded-expression smoke expected the narrowed destination to fail" >&2
    exit 1
fi
stage0_rows="$(printf '%s\n' "$stage0_output" \
    | sed -E -n 's#^.*:([0-9]+):[0-9]+[^:]*: return type expects.*$#L\1#p' \
    | LC_ALL=C sort)"
stage1_output="$("$RPT" < "$FIXTURE")"
stage1_rows="$(printf '%s\n' "$stage1_output" \
    | sed -E -n 's#^[[:space:]]*L([0-9]+) cannot propagate.*$#L\1#p' \
    | LC_ALL=C sort)"
expected_rows='L20'
if [[ "$stage0_rows" != "$expected_rows" ]] \
    || ! grep -q 'argument 2 to "PairProvider.choose_pair" expects i64, got bool' <<< "$stage0_output" \
    || ! grep -q '^D 2$' <<< "$stage1_output" \
    || ! grep -q 'L45 argument 2 to "PairProvider.choose_pair" expects i64, got bool' <<< "$stage1_output" \
    || [[ "$stage1_rows" != "$expected_rows" ]]; then
    printf 'EWR overloaded-expression smoke expected the L20 mismatch and only the L45 argument error:\nStage0 rows: %s\nStage0 output:\n%s\nStage1 output:\n%s\n' \
        "$stage0_rows" "$stage0_output" "$stage1_output" >&2
    exit 1
fi

echo "EWR overloaded-expression smoke OK"
