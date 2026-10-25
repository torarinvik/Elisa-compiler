#!/usr/bin/env bash
# Conflicting inherited and nested wildcard candidates are ambiguous; Try must not pick either family.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

fail() {
    echo "try wildcard import-order smoke FAIL: $1" >&2
    exit 1
}

FIXTURE="$REPO_ROOT/test/repro/try_wildcard_import_order_outer_before_nested.elisa"
set +e
stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1)"
stage0_status=$?
set -e
grep -qF 'ambiguous reference "ping"' <<< "$stage0_output" \
    || fail "Stage0 did not report the fixture's two visible wildcard candidates (status $stage0_status): $stage0_output"
if grep -qE 'cannot propagate|try requires a fallible expression' <<< "$stage0_output"; then
    fail "Stage0 let an ambiguous wildcard candidate supply a Try family: $stage0_output"
fi

stage1_output="$("$RPT" < "$FIXTURE")"
grep -qF 'ambiguous reference "ping"' <<< "$stage1_output" \
    || fail "Stage1 did not report the fixture's two visible wildcard candidates: $stage1_output"
if grep -qE 'cannot propagate|try requires a fallible expression' <<< "$stage1_output"; then
    fail "Stage1 let an ambiguous wildcard candidate supply a Try family: $stage1_output"
fi

echo "try wildcard import-order smoke OK: ambiguous outer/nested candidates fail closed"
