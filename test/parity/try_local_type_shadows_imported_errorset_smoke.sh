#!/usr/bin/env bash
# A local non-error type shadows an imported error set for a bare error item.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

fail() {
    echo "Try local-type/error-set shadow smoke FAIL: $1" >&2
    exit 1
}

FIXTURE="$REPO_ROOT/test/repro/try_local_type_shadows_imported_errorset.elisa"
set +e
stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1)"
stage0_status=$?
set -e
[[ "$stage0_status" -ne 0 ]] || fail "Stage0 accepted the deliberately mismatched destination"
stage0_rows="$(printf '%s\n' "$stage0_output" \
    | sed -E -n 's#^.*:([0-9]+):[0-9]+[^:]*: (cannot propagate|return type expects).*$#L\1#p' \
    | LC_ALL=C sort)"
expected_rows="$(cat <<'EOF'
L36
L52
L74
EOF
)"
[[ "$stage0_rows" == "$expected_rows" ]] || fail "Stage0 diagnostic lines changed: $stage0_rows\n$stage0_output"

stage1_output="$("$RPT" < "$FIXTURE")"
stage1_rows="$(printf '%s\n' "$stage1_output" \
    | sed -E -n 's#^[[:space:]]*L([0-9]+) cannot propagate.*$#L\1#p' \
    | LC_ALL=C sort)"
grep -q '^D 3$' <<< "$stage1_output" || fail "Stage1 reported an unexpected diagnostic count:\n$stage1_output"
[[ "$stage1_rows" == "$expected_rows" ]] || fail "Stage1 diagnostic lines differ:\n$stage1_output"
grep -q 'cannot propagate Expected from a function returning Other' <<< "$stage1_output" \
    || fail "Stage1 lost the expected wrong-destination mismatch:\n$stage1_output"
grep -q 'cannot propagate AliasExpected from a function returning Other' <<< "$stage1_output" \
    || fail "Stage1 lost the expected local-alias mismatch:\n$stage1_output"
grep -q 'cannot propagate QualifiedExpectedAlias from a function returning Other' <<< "$stage1_output" \
    || fail "Stage1 lost the expected qualified alias-to-error-set mismatch:\n$stage1_output"

echo "Try local-type/error-set shadow smoke OK"
