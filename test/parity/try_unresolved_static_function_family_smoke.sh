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
    echo "try unresolved static-function family smoke FAIL: $1" >&2
    exit 1
}

FIXTURE="$REPO_ROOT/test/repro/try_unresolved_static_function_family.elisa"
set +e
stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1)"
set -e
if grep -qF 'cannot propagate' <<< "$stage0_output"; then
    fail "Stage0 treated the unresolved function's ErrorSet as definite: $stage0_output"
fi

stage1_output="$("$RPT" < "$FIXTURE")"
if grep -qF 'cannot propagate' <<< "$stage1_output"; then
    fail "Stage1 treated the unresolved function's ErrorSet as definite: $stage1_output"
fi

echo "try unresolved static-function family smoke OK"
