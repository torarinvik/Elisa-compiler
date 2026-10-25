#!/usr/bin/env bash
# Polymorphic errorset wrapper returns must preserve the callback's allowed variants.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

fail() {
    echo "errorset wrapper return smoke FAIL: $1" >&2
    exit 1
}

FIXTURE="$REPO_ROOT/test/repro/errorset_wrapper_return_subsets.elisa"
set +e
stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1)"
stage0_status=$?
set -e
[[ "$stage0_status" -ne 0 ]] || fail "Stage0 accepted incompatible wrapper returns"

stage0_rows="$(printf '%s\n' "$stage0_output" \
    | sed -E -n 's#^.*:([0-9]+):[0-9]+[^:]*: (cannot propagate|return type expects).*$#L\1#p' \
    | LC_ALL=C sort)"
stage1_output="$("$RPT" < "$FIXTURE")"
stage1_rows="$(printf '%s\n' "$stage1_output" \
    | sed -E -n 's#^[[:space:]]*L([0-9]+) cannot propagate.*$#L\1#p' \
    | LC_ALL=C sort)"
expected_stage0_rows="$(cat <<'EOF'
L38
L41
L47
L53
L56
L68
L71
L87
L90
L113
L118
L135
EOF
)"
expected_stage1_rows="$(cat <<'EOF'
L38
L41
L47
L53
L56
L68
L71
L87
L90
L110
L113
L118
L135
EOF
)"

[[ "$stage0_rows" == "$expected_stage0_rows" ]] || fail "Stage0 wrapper-return baseline changed: $stage0_rows"
grep -q '^D 13$' <<< "$stage1_output" || fail "Stage1 reported an unexpected diagnostic count: $stage1_output"
[[ "$stage1_rows" == "$expected_stage1_rows" ]] || fail "Stage1 wrapper-return coverage differs: $stage1_rows"

# `error[Fault{}]` is malformed and already has a dedicated Stage1 diagnostic. EWR
# must decline a second, misleading propagation mismatch for that callback.
empty_subset_fixture="$REPO_ROOT/test/repro/errorset_wrapper_return_empty_subset.elisa"
empty_subset_output="$("$RPT" < "$empty_subset_fixture")"
grep -q '^D 2$' <<< "$empty_subset_output" || fail "Empty callback subset produced extra diagnostics: $empty_subset_output"
grep -q 'error\[\.\.\.\] requires at least one qualified error tag' <<< "$empty_subset_output" || fail "Empty callback subset lost its syntax diagnostic: $empty_subset_output"
! grep -q 'cannot propagate' <<< "$empty_subset_output" || fail "EWR diagnosed malformed empty callback subset: $empty_subset_output"

echo "errorset wrapper return smoke OK: subset inclusion is honored across family paths"
