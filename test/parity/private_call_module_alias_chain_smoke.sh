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
    echo "private call alias-chain smoke FAIL: $1" >&2
    exit 1
}

FIXTURE="$REPO_ROOT/test/repro/private_call_module_alias_chain.elisa"
set +e
stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1)"
stage0_rc=$?
set -e
[[ "$stage0_rc" -ne 0 ]] || fail "Stage0 accepted a private call through a chained module alias"
grep -qF 'is private to module' <<< "$stage0_output" \
    || fail "Stage0 missed the private alias-chain call: $stage0_output"
grep -qF 'nested_hidden' <<< "$stage0_output" \
    || fail "Stage0 missed the qualified private alias-suffix call: $stage0_output"
grep -qF 'ProjectionChoice.loser_only' <<< "$stage0_output" \
    || fail "Stage0 did not reject a loser-only member under the winning duplicate alias: $stage0_output"

stage1_output="$("$RPT" < "$FIXTURE")"
grep -q '^P 0$' <<< "$stage1_output" || fail "Stage1 returned a nonzero process status: $stage1_output"
grep -qF 'is private to module' <<< "$stage1_output" \
    || fail "Stage1 missed the private alias-chain call: $stage1_output"
grep -qF 'nested_hidden' <<< "$stage1_output" \
    || fail "Stage1 missed the qualified private alias-suffix call: $stage1_output"
grep -qF 'ProjectionChoice.loser_only' <<< "$stage1_output" \
    || fail "Stage1 did not reject a loser-only member under the winning duplicate alias: $stage1_output"
if grep -qF 'undefined identifier "NestedSecret.nested_hidden"' <<< "$stage1_output"; then
    fail "Stage1 failed to project the canonical target's nested alias member: $stage1_output"
fi
if grep -qF 'undefined identifier "ProjectionChoice.winner_only"' <<< "$stage1_output"; then
    fail "Stage1 failed to project the winning alias member: $stage1_output"
fi

echo "private call module-alias chain smoke OK"
