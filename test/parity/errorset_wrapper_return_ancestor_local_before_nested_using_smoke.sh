#!/usr/bin/env bash
# Core checks all lexical declarations before wildcard using candidates.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

fail() {
    echo "EWR ancestor-local precedence smoke FAIL: $1" >&2
    exit 1
}

FIXTURE="$REPO_ROOT/test/repro/errorset_wrapper_return_ancestor_local_before_nested_using.elisa"
stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1)" \
    || fail "Stage0 rejected the ancestor-local wrapper: $stage0_output"
stage1_output="$("$RPT" < "$FIXTURE")"

grep -q '^P 0$' <<< "$stage1_output" || fail "Stage1 did not parse the precedence fixture: $stage1_output"
grep -q '^D 0$' <<< "$stage1_output" || fail "Stage1 reported a semantic error for the ancestor-local wrapper: $stage1_output"
! grep -q 'cannot propagate\|return type expects' <<< "$stage1_output" \
    || fail "Stage1 selected the nested wildcard wrapper: $stage1_output"

echo "EWR ancestor-local precedence smoke OK: Consumer.wrap precedes Consumer::Inner using Api"
