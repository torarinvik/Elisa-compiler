#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

fail() {
    echo "Catch match identity smoke FAIL: $1" >&2
    exit 1
}

FIXTURE="$REPO_ROOT/test/repro/catch_match_line_identity.elisa"
set +e
stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1)"
stage0_status=$?
set -e
[[ "$stage0_status" -ne 0 ]] || fail "Stage0 accepted an ordinary wildcard-dominated match"
grep -q 'unreachable because an earlier arm' <<< "$stage0_output" || fail "Stage0 lost the ordinary unreachable-arm diagnostic: $stage0_output"

stage1_output="$("$RPT" < "$FIXTURE")"
grep -q '^D 1$' <<< "$stage1_output" || fail "Stage1 did not preserve the ordinary match diagnostic: $stage1_output"
grep -q 'unreachable because an earlier arm' <<< "$stage1_output" || fail "Stage1 lost the ordinary unreachable-arm diagnostic: $stage1_output"

echo "Catch match identity smoke OK" >&2
