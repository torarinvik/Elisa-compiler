#!/usr/bin/env bash
# Core checks all lexical namespaces before wildcard using candidates.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

fail() {
    echo "try wildcard ancestor-precedence smoke FAIL: $1" >&2
    exit 1
}

FIXTURE="$REPO_ROOT/test/repro/try_wildcard_import_does_not_shadow_ancestor.elisa"
grep -q 'return try ping()' "$FIXTURE" || fail "fixture is missing the direct-call path"
grep -q 'payload = ping()' "$FIXTURE" || fail "fixture is missing the cached assignment path"
grep -q 'return try payload' "$FIXTURE" || fail "fixture is missing the cached try path"
if ! stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1)"; then
    fail "Stage0 rejected the lexical-ancestor call: $stage0_output"
fi
! grep -q 'cannot propagate' <<< "$stage0_output" \
    || fail "Stage0 selected Api.ping before Consumer.ping: $stage0_output"
stage1_output="$("$RPT" < "$FIXTURE")"
grep -q '^P 0$' <<< "$stage1_output" || fail "Stage1 did not parse the wildcard precedence fixture: $stage1_output"
grep -q '^D 0$' <<< "$stage1_output" || fail "Stage1 did not preserve the ancestor function candidate: $stage1_output"
! grep -q 'cannot propagate' <<< "$stage1_output" \
    || fail "Stage1 selected Api.ping before Consumer.ping: $stage1_output"

echo "try wildcard ancestor-precedence smoke OK: Consumer.ping precedes the nested using for direct and cached tries"
