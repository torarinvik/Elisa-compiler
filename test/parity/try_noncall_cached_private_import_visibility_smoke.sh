#!/usr/bin/env bash
# A private imported call must not supply ErrorSet facts to direct or cached `try` inference.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

fail() {
    echo "try noncall cached private-import smoke FAIL: $1" >&2
    exit 1
}

FIXTURE="$REPO_ROOT/test/repro/try_noncall_cached_private_import_visibility.elisa"
set +e
stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1)"
stage0_status=$?
set -e
[[ "$stage0_status" -ne 0 ]] || fail "Stage0 accepted the inaccessible private call"
grep -q 'is private to module' <<< "$stage0_output" \
    || fail "Stage0 did not report private access: $stage0_output"
grep -q 'try requires a fallible expression' <<< "$stage0_output" \
    || fail "Stage0 did not reject propagation from the invalid call result: $stage0_output"
if grep -qF 'cannot propagate' <<< "$stage0_output"; then
    fail "Stage0 unexpectedly propagated the hidden callable's ErrorSet: $stage0_output"
fi

stage1_output="$("$RPT" < "$FIXTURE")"
grep -q 'is private to module' <<< "$stage1_output" \
    || fail "Stage1 did not report private access: $stage1_output"
grep -q 'try requires a fallible expression' <<< "$stage1_output" \
    || fail "Stage1 did not reject propagation from the invalid call result: $stage1_output"
if grep -qF 'cannot propagate' <<< "$stage1_output"; then
    fail "Stage1 inferred the hidden callable's ErrorSet for the cached value: $stage1_output"
fi

echo "try noncall cached private-import smoke OK: inaccessible call facts do not leak"
