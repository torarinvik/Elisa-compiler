#!/usr/bin/env bash
# A forward top-level selective import participates in type resolution before analysis.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

fail() {
    echo "Try forward-import visibility smoke FAIL: $1" >&2
    exit 1
}

FIXTURE="$REPO_ROOT/test/repro/try_forward_import_error_set_visibility.elisa"
set +e
stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1)"
stage0_status=$?
set -e
[[ "$stage0_status" -ne 0 ]] || fail "Stage0 accepted propagation into the unrelated Fault variant family"
stage0_rows="$(printf '%s\n' "$stage0_output" \
    | sed -E -n 's#^.*:([0-9]+):[0-9]+-[0-9]+: cannot propagate.*$#L\1#p' \
    | LC_ALL=C sort)"
expected_rows='L23'
[[ "$stage0_rows" == "$expected_rows" ]] || fail "Stage0 diagnostic lines changed: $stage0_rows\n$stage0_output"

stage1_output="$("$RPT" < "$FIXTURE")"
stage1_rows="$(printf '%s\n' "$stage1_output" \
    | sed -E -n 's#^[[:space:]]*L([0-9]+) cannot propagate.*$#L\1#p' \
    | LC_ALL=C sort)"
grep -q '^D 1$' <<< "$stage1_output" || fail "Stage1 reported an unexpected diagnostic count:\n$stage1_output"
[[ "$stage1_rows" == "$expected_rows" ]] || fail "Stage1 diagnostic lines differ:\n$stage1_output"
grep -q 'cannot propagate Expected from a function returning Fault' <<< "$stage1_output" \
    || fail "Stage1 did not preserve the imported family identity:\n$stage1_output"

echo "Try forward-import visibility smoke OK"
