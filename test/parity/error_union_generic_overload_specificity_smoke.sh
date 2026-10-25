#!/usr/bin/env bash
# The discarded-error checker must follow concrete-over-generic overload ranking,
# resolve an aliased overloaded target, and retain Core's arg0-only tie behavior.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

FIXTURE="$REPO_ROOT/test/repro/error_union_generic_overload_specificity.elisa"
set +e
stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1)"
stage0_status=$?
set -e
if [[ "$stage0_status" -eq 0 ]]; then
    echo "ErrorUnion overload smoke expected discarded fallible calls to fail" >&2
    exit 1
fi
stage0_rows="$(printf '%s\n' "$stage0_output" \
    | sed -E -n 's#^.*:([0-9]+):[0-9]+[^:]*: error union result must be handled.*#L\1#p' \
    | LC_ALL=C sort)"
stage1_output="$("$RPT" < "$FIXTURE")"
stage1_rows="$(printf '%s\n' "$stage1_output" \
    | sed -E -n 's#^[[:space:]]*L([0-9]+) error union result must be handled.*#L\1#p' \
    | LC_ALL=C sort)"
expected_rows=$'L17\nL20'
if [[ "$stage0_rows" != "$expected_rows" ]] \
    || ! grep -q '^D 2$' <<< "$stage1_output" \
    || [[ "$stage1_rows" != "$expected_rows" ]]; then
    printf 'ErrorUnion overload smoke expected diagnostics at L17 and L20:\nStage0 rows: %s\nStage0 output:\n%s\nStage1 output:\n%s\n' \
        "$stage0_rows" "$stage0_output" "$stage1_output" >&2
    exit 1
fi

echo "ErrorUnion generic-overload specificity smoke OK"
