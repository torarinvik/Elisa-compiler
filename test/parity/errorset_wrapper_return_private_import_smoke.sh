#!/usr/bin/env bash
# EWR must decline a wrapper candidate that is inaccessible at the call site.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

fail() {
    echo "errorset wrapper private-import smoke FAIL: $1" >&2
    exit 1
}

FIXTURE="$REPO_ROOT/test/repro/errorset_wrapper_return_private_import.elisa"
set +e
stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1)"
stage0_status=$?
set -e
[[ "$stage0_status" -ne 0 ]] || fail "Stage0 accepted an imported private wrapper"
stage1_output="$("$RPT" < "$FIXTURE")"
grep -qF '"AliasInstaller.Provider.wrap" is private to module "AliasInstaller.Provider"' <<< "$stage0_output" \
    || fail "Stage0 missed the private-access diagnostic: $stage0_output"
grep -qF '"AliasInstaller.Provider.wrap" is private to module "AliasInstaller.Provider"' <<< "$stage1_output" \
    || fail "Stage1 missed the private-access diagnostic: $stage1_output"
grep -Eq '^D [1-9][0-9]*$' <<< "$stage1_output" \
    || fail "Stage1 missed the private-access error: $stage1_output"
! grep -q 'cannot propagate' <<< "$stage0_output" \
    || fail "Stage0 diagnosed the inaccessible wrapper as an EWR mismatch: $stage0_output"
! grep -q 'cannot propagate' <<< "$stage1_output" \
    || fail "EWR diagnosed an inaccessible wrapper candidate: $stage1_output"

echo "errorset wrapper private-import smoke OK: inaccessible candidates do not produce EWR diagnostics"
