#!/usr/bin/env bash
# Exercise nested and conflicting selective imports plus aliased overloaded callees
# through both semantic implementations.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

fail() {
    echo "ErrorUnion resolution smoke FAIL: $1" >&2
    exit 1
}

check_rows() {
    fixture="$1"
    expected_rows="$2"
    label="$3"
    set +e
    stage0_output="$("$ELISACORE_BIN" -emit semantic "$fixture" 2>&1)"
    stage0_status=$?
    set -e
    [[ "$stage0_status" -ne 0 ]] || fail "$label: Stage0 accepted discarded fallible calls"
    if [[ "$label" == 'first selective-import target' ]] \
        && ! grep -Fq 'conflicting import: "load" is already imported as "First.load", cannot also import it as "Second.load"' <<< "$stage0_output"; then
        fail "$label: Stage0 did not report the expected duplicate-import conflict: $stage0_output"
    fi
    stage0_rows="$(printf '%s\n' "$stage0_output" \
        | sed -E -n 's#^.*:([0-9]+):[0-9]+[^:]*: error union result must be handled.*#L\1#p' \
        | LC_ALL=C sort)"
    stage1_output="$("$RPT" < "$fixture")"
    stage1_rows="$(printf '%s\n' "$stage1_output" \
        | sed -E -n 's#^[[:space:]]*L([0-9]+) error union result must be handled.*#L\1#p' \
        | LC_ALL=C sort)"
    [[ "$stage0_rows" == "$expected_rows" ]] || fail "$label: Stage0 rows were $stage0_rows; expected $expected_rows. Output: $stage0_output"
    [[ "$stage1_rows" == "$expected_rows" ]] || fail "$label: Stage1 rows were $stage1_rows; expected $expected_rows. Output: $stage1_output"
    [[ $(grep -cF 'error union result must be handled' <<< "$stage0_output") == $(grep -c '^L' <<< "$expected_rows") ]] \
        || fail "$label: Stage0 emitted an unexpected ErrorUnion count: $stage0_output"
    [[ $(grep -cF 'error union result must be handled' <<< "$stage1_output") == $(grep -c '^L' <<< "$expected_rows") ]] \
        || fail "$label: Stage1 emitted an unexpected ErrorUnion count: $stage1_output"
}

check_rows "$REPO_ROOT/test/repro/error_union_nested_selective_import.elisa" 'L16' 'nested relative selective import'
check_rows "$REPO_ROOT/test/repro/error_union_duplicate_selective_import_first_target.elisa" 'L20' 'first selective-import target'
check_rows "$REPO_ROOT/test/repro/error_union_aliased_fallible_overloads.elisa" $'L20\nL23' 'aliased fallible overloads'

echo "ErrorUnion resolution smoke OK"
