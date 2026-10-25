#!/usr/bin/env bash
# A hidden overload reached through a selective alias can win across modules.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

fail() {
    echo "cross-module Try private-winner smoke FAIL: $1" >&2
    exit 1
}

FIXTURE="$REPO_ROOT/test/repro/try_overload_cross_module_private_cached_winner.elisa"
set +e
stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1)"
stage0_rc=$?
set -e
[[ "$stage0_rc" -ne 0 ]] || fail "Stage0 accepted the inaccessible cross-module winner"
[[ $(grep -cF 'is private to module' <<< "$stage0_output") == 2 ]] \
    || fail "Stage0 did not reject both direct and cached private winners: $stage0_output"
[[ $(grep -cF 'try requires a fallible expression' <<< "$stage0_output") == 2 ]] \
    || fail "Stage0 did not reject both invalid Try expressions: $stage0_output"
[[ $(grep -cF 'cannot propagate' <<< "$stage0_output") == 2 ]] \
    || fail "Stage0 failed to preserve direct and cached public generic controls: $stage0_output"

stage1_output="$("$RPT" < "$FIXTURE")"
[[ $(grep -cF 'is private to module' <<< "$stage1_output") == 2 ]] \
    || fail "Stage1 did not reject both direct and cached private winners: $stage1_output"
[[ $(grep -cF 'try requires a fallible expression' <<< "$stage1_output") == 2 ]] \
    || fail "Stage1 did not reject both invalid Try expressions: $stage1_output"
[[ $(grep -cF 'cannot propagate' <<< "$stage1_output") == 2 ]] \
    || fail "Stage1 failed to preserve direct and cached public generic controls: $stage1_output"

echo "cross-module Try private-winner smoke OK"
