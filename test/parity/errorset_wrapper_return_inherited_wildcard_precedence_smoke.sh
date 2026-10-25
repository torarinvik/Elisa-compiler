#!/usr/bin/env bash
# Inherited outer `using` candidates precede a nested module's local `using` entries.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

fail() {
    echo "errorset wrapper inherited-wildcard precedence smoke FAIL: $1" >&2
    exit 1
}

FIXTURE="$REPO_ROOT/test/repro/errorset_wrapper_return_inherited_wildcard_precedence.elisa"
set +e
stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1)"
stage0_status=$?
set -e
[[ "$stage0_status" -eq 0 ]] || fail "Core rejected the inherited wildcard winner: $stage0_output"

stage1_output="$("$RPT" < "$FIXTURE")"
grep -q '^P 0$' <<< "$stage1_output" || fail "Stage1 did not parse the inherited-wildcard fixture: $stage1_output"
grep -q '^D 0$' <<< "$stage1_output" || fail "EWR did not preserve the outer wildcard winner: $stage1_output"
if grep -qF 'cannot propagate' <<< "$stage1_output"; then
    fail "EWR selected the nested wildcard's ErrorSet instead of the inherited outer candidate: $stage1_output"
fi

echo "errorset wrapper inherited-wildcard precedence smoke OK"
