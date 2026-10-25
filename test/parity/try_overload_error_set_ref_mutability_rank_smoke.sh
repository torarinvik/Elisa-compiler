#!/usr/bin/env bash
# Core gives a ranking point to the reference overload whose mutability matches
# the actual reference; Try must use the same selected error family.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

fail() {
    echo "try overload reference-mutability smoke FAIL: $1" >&2
    exit 1
}

FIXTURE="$REPO_ROOT/test/repro/try_overload_error_set_ref_mutability_rank.elisa"
set +e
stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1)"
stage0_status=$?
set -e
[[ "$stage0_status" -ne 0 ]] || fail "Stage0 accepted the mismatched selected overloads"
stage0_rows="$(printf '%s\n' "$stage0_output" \
    | sed -E -n 's#^.*:([0-9]+):[0-9]+[^:]*: (cannot propagate|return type expects).*$#L\1#p' \
    | LC_ALL=C sort)"
expected_rows="$(cat <<'EOF'
L21
L27
EOF
)"
[[ "$stage0_rows" == "$expected_rows" ]] || fail "Stage0 reference-rank diagnostic rows changed: $stage0_rows"
grep -q 'cannot propagate MutableFault from a function returning ImmutableFault' <<< "$stage0_output" \
    || fail "Stage0 did not rank the matching mutable reference first"
grep -q 'cannot propagate ImmutableFault from a function returning MutableFault' <<< "$stage0_output" \
    || fail "Stage0 did not select the immutable-reference overload"

stage1_output="$("$RPT" < "$FIXTURE")"
stage1_rows="$(printf '%s\n' "$stage1_output" \
    | sed -E -n 's#^[[:space:]]*L([0-9]+) cannot propagate.*$#L\1#p' \
    | LC_ALL=C sort)"
grep -q '^D 2$' <<< "$stage1_output" || fail "Stage1 reported an unexpected diagnostic count: $stage1_output"
[[ "$stage1_rows" == "$expected_rows" ]] || fail "Stage1 reference-rank diagnostic rows differ: $stage1_output"
grep -q 'cannot propagate MutableFault from a function returning ImmutableFault' <<< "$stage1_output" \
    || fail "Stage1 did not rank the matching mutable reference first"
grep -q 'cannot propagate ImmutableFault from a function returning MutableFault' <<< "$stage1_output" \
    || fail "Stage1 did not select the immutable-reference overload"

echo "try overload reference-mutability ranking smoke OK"
