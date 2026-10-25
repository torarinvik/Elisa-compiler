#!/usr/bin/env bash
# A unique bare variant in error[...] is a one-tag subset of its owning family.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

fail() {
    echo "try bare-variant subset smoke FAIL: $1" >&2
    exit 1
}

FIXTURE="$REPO_ROOT/test/repro/try_error_bare_variant_subset.elisa"
set +e
stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1)"
stage0_status=$?
set -e
[[ "$stage0_status" -ne 0 ]] || fail "Stage0 accepted incompatible bare-variant propagations"

stage0_rows="$(printf '%s\n' "$stage0_output" \
    | sed -E -n 's#^.*:([0-9]+):[0-9]+-[0-9]+: cannot propagate.*$#L\1#p' \
    | LC_ALL=C sort)"
stage1_output="$("$RPT" < "$FIXTURE")"
stage1_rows="$(printf '%s\n' "$stage1_output" \
    | sed -E -n 's#^[[:space:]]*L([0-9]+) cannot propagate.*$#L\1#p' \
    | LC_ALL=C sort)"
expected_rows="$(cat <<'EOF'
L12
L24
EOF
)"

[[ "$stage0_rows" == "$expected_rows" ]] || fail "Stage0 bare-variant diagnostic lines changed: $stage0_rows"
[[ $(grep -cF "$FIXTURE:" <<< "$stage0_output") == 2 ]] || fail "Stage0 reported an unexpected diagnostic count: $stage0_output"
grep -q '^D 2$' <<< "$stage1_output" || fail "Stage1 reported an unexpected diagnostic count: $stage1_output"
[[ "$stage1_rows" == "$expected_rows" ]] || fail "Stage1 bare-variant diagnostic lines differ: $stage1_output"

echo "try bare-variant subset smoke OK: owner-family and one-tag coverage match"
