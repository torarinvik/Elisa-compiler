#!/usr/bin/env bash
# A conflicting later selective import must not enter Try's visible receiver set.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

fail() {
    echo "try duplicate selective-import receiver smoke FAIL: $1" >&2
    exit 1
}

FIXTURE="$REPO_ROOT/test/repro/try_overload_duplicate_selective_import_first_target.elisa"
set +e
stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1)"
stage0_status=$?
set -e
[[ "$stage0_status" -ne 0 ]] || fail "Stage0 accepted the conflicting selective imports"
grep -q 'conflicting import.*"choose"' <<< "$stage0_output" || fail "Stage0 did not report the duplicate alias conflict: $stage0_output"
stage0_rows="$(printf '%s\n' "$stage0_output" \
    | sed -E -n 's#^.*:([0-9]+):[0-9]+[^:]*: cannot propagate.*$#L\1#p' \
    | LC_ALL=C sort)"
stage1_output="$("$RPT" < "$FIXTURE")"
stage1_rows="$(printf '%s\n' "$stage1_output" \
    | sed -E -n 's#^[[:space:]]*L([0-9]+) cannot propagate.*$#L\1#p' \
    | LC_ALL=C sort)"
expected_rows="$(cat <<'EOF'
L28
EOF
)"

[[ "$stage0_rows" == "$expected_rows" ]] || fail "Stage0 propagation diagnostics changed: $stage0_rows"
[[ $(grep -cF 'cannot propagate' <<< "$stage0_output") == 1 ]] || fail "Stage0 reported an unexpected propagation diagnostic: $stage0_output"
[[ $(grep -cF 'cannot propagate' <<< "$stage1_output") == 1 ]] || fail "Stage1 did not report exactly one propagation mismatch: $stage1_output"
[[ "$stage1_rows" == "$expected_rows" ]] || fail "Stage1 chose a later conflicting import target: $stage1_output"

echo "try duplicate selective-import receiver smoke OK: the first alias remains authoritative"
