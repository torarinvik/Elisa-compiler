#!/usr/bin/env bash
# Cached Try lookup must search lexical ancestors before Core's program-level selective alias.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

fail() {
    echo "try noncall cached ancestor-precedence smoke FAIL: $1" >&2
    exit 1
}

FIXTURE="$REPO_ROOT/test/repro/try_noncall_cached_ancestor_precedes_selective_import.elisa"
if ! stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1)"; then
    fail "Stage0 rejected the lexical-ancestor source family: $stage0_output"
fi
! grep -q 'cannot propagate' <<< "$stage0_output" \
    || fail "Stage0 selected the program-level import before Consumer.origin: $stage0_output"
stage1_output="$("$RPT" < "$FIXTURE")"
grep -q '^P 0$' <<< "$stage1_output" || fail "Stage1 did not parse the precedence fixture: $stage1_output"
grep -q '^D 0$' <<< "$stage1_output" || fail "Stage1 did not preserve the lexical ancestor candidate: $stage1_output"
! grep -q 'cannot propagate' <<< "$stage1_output" \
    || fail "Stage1 selected the program-level import before Consumer.origin: $stage1_output"

echo "try noncall cached ancestor-precedence smoke OK: lexical declarations precede selective aliases"
