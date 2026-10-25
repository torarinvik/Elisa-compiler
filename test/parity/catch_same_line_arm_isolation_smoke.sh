#!/usr/bin/env bash
# Same-callee catches at the same logical #line must not share handled-arm metadata.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

fail() {
    echo "Catch same-line arm isolation smoke FAIL: $1" >&2
    exit 1
}

FIXTURE="$REPO_ROOT/test/repro/catch_same_line_arm_isolation.elisa"
set +e
stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1)"
stage0_status=$?
set -e
[[ "$stage0_status" -ne 0 ]] || fail "Stage0 accepted two incomplete catches"
[[ $(grep -c 'non-exhaustive catch over Fault; missing Fault\.' <<< "$stage0_output") -eq 2 ]] || fail "Stage0 reported an unexpected diagnostic count:\n$stage0_output"
grep -q 'non-exhaustive catch over Fault; missing Fault.Other' <<< "$stage0_output" || fail "Stage0 lost the first catch's missing variant:\n$stage0_output"
grep -q 'non-exhaustive catch over Fault; missing Fault.Bad' <<< "$stage0_output" || fail "Stage0 lost the second catch's missing variant:\n$stage0_output"

stage1_output="$("$RPT" < "$FIXTURE")"
grep -q '^D 2$' <<< "$stage1_output" || fail "Stage1 reported an unexpected diagnostic count:\n$stage1_output"
grep -q 'non-exhaustive catch over Fault; missing Fault.Other' <<< "$stage1_output" || fail "Stage1 merged the first catch's arm rows:\n$stage1_output"
grep -q 'non-exhaustive catch over Fault; missing Fault.Bad' <<< "$stage1_output" || fail "Stage1 merged the second catch's arm rows:\n$stage1_output"

echo "Catch same-line arm isolation smoke OK" >&2
