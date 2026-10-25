#!/usr/bin/env bash
# EWR must resolve qualified callback families through nested module aliases.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

fail() {
    echo "errorset wrapper nested-alias smoke FAIL: $1" >&2
    exit 1
}

FIXTURE="$REPO_ROOT/test/repro/errorset_wrapper_nested_alias.elisa"
set +e
stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1)"
stage0_status=$?
set -e
[[ "$stage0_status" -ne 0 ]] || fail "Stage0 accepted the narrowed wrapper return"

stage0_rows="$(printf '%s\n' "$stage0_output" \
    | sed -E -n 's#^.*:([0-9]+):[0-9]+-[0-9]+:.*$#L\1#p' \
    | LC_ALL=C sort -u)"
stage0_diagnostic_count="$(printf '%s\n' "$stage0_output" | grep -cF "$FIXTURE:" || true)"
stage1_output="$("$RPT" < "$FIXTURE")"
stage1_rows="$(printf '%s\n' "$stage1_output" \
    | sed -E -n 's#^[[:space:]]*L([0-9]+) cannot propagate.*$#L\1#p' \
    | LC_ALL=C sort)"
expected_stage0_rows="$(cat <<'EOF'
L14
L20
L26
EOF
)"
expected_stage1_rows="$(cat <<'EOF'
L27
EOF
)"

[[ "$stage0_rows" == "$expected_stage0_rows" ]] \
    || fail "Stage0 nested-alias diagnostic lines changed: $stage0_rows\n$stage0_output"
[[ "$stage0_diagnostic_count" == 6 ]] \
    || fail "Stage0 reported $stage0_diagnostic_count diagnostics, expected 6:\n$stage0_output"
grep -q '^D 1$' <<< "$stage1_output" || fail "Stage1 reported an unexpected diagnostic count: $stage1_output"
[[ "$stage1_rows" == "$expected_stage1_rows" ]] \
    || fail "Stage1 nested-alias diagnostic differs: $stage1_rows\n$stage1_output"

echo "errorset wrapper nested-alias smoke OK"
