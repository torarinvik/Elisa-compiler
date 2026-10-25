#!/usr/bin/env bash
# Core rejects the private concrete overload before `try` can propagate its family.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

fail() {
    echo "try private-overload visibility smoke FAIL: $1" >&2
    exit 1
}

FIXTURE="$REPO_ROOT/test/repro/try_overload_private_winner_visibility.elisa"
set +e
stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1)"
stage0_rc=$?
set -e
[[ "$stage0_rc" -ne 0 ]] || fail "Stage0 accepted the inaccessible private overload"
grep -qF 'is private to module' <<< "$stage0_output" \
    || fail "Stage0 did not reject the private receiver winner: $stage0_output"
[[ $(grep -cF 'is private to module' <<< "$stage0_output") == 9 ]] \
    || fail "Stage0 reported private access for a public overload control: $stage0_output"
grep -qF 'CharProvider.narrow' <<< "$stage0_output" \
    || fail "Stage0 did not identify the private char winner for a typed int receiver: $stage0_output"
grep -qF 'CharProvider.address' <<< "$stage0_output" \
    || fail "Stage0 did not identify the private uintptr winner for a typed int receiver: $stage0_output"
if grep -qF 'try requires a fallible expression' <<< "$stage0_output"; then
    fail "Stage0 cascaded `try` diagnostics after the invalid private call: $stage0_output"
fi
[[ $(grep -cF 'cannot propagate' <<< "$stage0_output") == 8 ]] \
    || fail "Stage0 failed to preserve bare, qualified, numeric-width, and char public-generic mismatch controls: $stage0_output"

stage1_output="$("$RPT" < "$FIXTURE")"
grep -qF 'is private to module' <<< "$stage1_output" \
    || fail "Stage1 did not report the inaccessible private overload: $stage1_output"
[[ $(grep -cF 'is private to module' <<< "$stage1_output") == 9 ]] \
    || fail "Stage1 reported private access for a public overload control: $stage1_output"
grep -qF 'CharProvider.narrow' <<< "$stage1_output" \
    || fail "Stage1 did not identify the private char winner for a typed int receiver: $stage1_output"
grep -qF 'CharProvider.address' <<< "$stage1_output" \
    || fail "Stage1 did not identify the private uintptr winner for a typed int receiver: $stage1_output"
if grep -qF 'try requires a fallible expression' <<< "$stage1_output"; then
    fail "Stage1 cascaded `try` diagnostics after the invalid private call: $stage1_output"
fi
grep -qF '  L25 "Provider.origin" is private to module "Provider"' <<< "$stage1_output" \
    || fail "Stage1 did not retain the direct private-winner diagnostic: $stage1_output"
grep -qF '  L28 "Provider.origin" is private to module "Provider"' <<< "$stage1_output" \
    || fail "Stage1 did not retain the cached private-winner diagnostic: $stage1_output"
grep -qF '  L32 "Provider.origin" is private to module "Provider"' <<< "$stage1_output" \
    || fail "Stage1 did not retain the qualified direct private-winner diagnostic: $stage1_output"
grep -qF '  L35 "Provider.origin" is private to module "Provider"' <<< "$stage1_output" \
    || fail "Stage1 did not retain the qualified cached private-winner diagnostic: $stage1_output"
grep -qF '  L67 "Provider.origin" is private to module "Provider"' <<< "$stage1_output" \
    || fail "Stage1 let the same-named root callable suppress root_callable_private_winner_direct: $stage1_output"
grep -qF '  L70 "Provider.origin" is private to module "Provider"' <<< "$stage1_output" \
    || fail "Stage1 let the same-named root callable suppress root_callable_private_winner_cached: $stage1_output"
if grep -qE '^  L(39|42|46|49|53|56|60|63) .*is private to module ' <<< "$stage1_output"; then
    fail "Stage1 reported private access for a public bool overload winner: $stage1_output"
fi
[[ $(grep -cF 'cannot propagate' <<< "$stage1_output") == 8 ]] \
    || fail "Stage1 failed to preserve bare, qualified, numeric-width, and char public-generic mismatch controls: $stage1_output"

echo "try private-overload visibility smoke OK: private winner does not leak"
