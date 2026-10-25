#!/usr/bin/env bash
# A by-value aggregate candidate must not hide the selected matching Ref receiver.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

fail() {
    echo "try mixed Ref/value overload smoke FAIL: $1" >&2
    exit 1
}

FIXTURE="$REPO_ROOT/test/repro/try_overload_mixed_ref_value.elisa"
set +e
stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1)"
stage0_status=$?
set -e
[[ "$stage0_status" -ne 0 ]] || fail "Stage0 accepted the mismatched selected overload"
stage0_rows="$(printf '%s\n' "$stage0_output" \
    | sed -E -n 's#^.*:([0-9]+):[0-9]+[^:]*: (cannot propagate|return type expects).*$#L\1#p' \
    | LC_ALL=C sort)"
expected_rows="$(cat <<'EOF'
L21
EOF
)"
[[ "$stage0_rows" == "$expected_rows" ]] || fail "Stage0 diagnostic lines changed: $stage0_rows"

stage1_output="$("$RPT" < "$FIXTURE")"
stage1_rows="$(printf '%s\n' "$stage1_output" \
    | sed -E -n 's#^[[:space:]]*L([0-9]+) cannot propagate.*$#L\1#p' \
    | LC_ALL=C sort)"
grep -q '^D 1$' <<< "$stage1_output" || fail "Stage1 reported an unexpected diagnostic count: $stage1_output"
[[ "$stage1_rows" == "$expected_rows" ]] || fail "Stage1 diagnostic lines differ: $stage1_output"

echo "try mixed Ref/value overload smoke OK: matching Ref candidate wins"
