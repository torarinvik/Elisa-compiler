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
    echo "private call target visibility smoke FAIL: $1" >&2
    exit 1
}

FIXTURE="$REPO_ROOT/test/repro/private_call_overload_visibility_shapes.elisa"
set +e
stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1)"
stage0_rc=$?
set -e
[[ "$stage0_rc" -ne 0 ]] || fail "Stage0 accepted the private-only incompatible call"
[[ $(grep -cF 'is private to module' <<< "$stage0_output") == 2 ]] \
    || fail "Stage0 reported private access for a public winner or missed a private-winner control: $stage0_output"
grep -qF 'QualifiedNamedProvider.inspect' <<< "$stage0_output" \
    || fail "Stage0 missed the same-spelling cross-module named-type private winner: $stage0_output"

stage1_output="$("$RPT" < "$FIXTURE")"
grep -q '^P 0$' <<< "$stage1_output" || fail "Stage1 returned a nonzero process status: $stage1_output"
[[ $(grep -cF 'is private to module' <<< "$stage1_output") == 2 ]] \
    || fail "Stage1 reported private access for a public winner or missed a private-winner control: $stage1_output"
grep -qF 'Provider.sealed' <<< "$stage1_output" \
    || fail "Stage1's private diagnostic did not identify the private-only callee: $stage1_output"
grep -qF 'QualifiedNamedProvider.inspect' <<< "$stage1_output" \
    || fail "Stage1 missed the same-spelling cross-module named-type private winner: $stage1_output"

echo "private call target visibility smoke OK"
