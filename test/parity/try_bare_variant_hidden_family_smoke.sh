#!/usr/bin/env bash
# An inaccessible sibling family name must not suppress unique bare variant lookup.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

fail() {
    echo "try bare-variant hidden-family smoke FAIL: $1" >&2
    exit 1
}

FIXTURE="$REPO_ROOT/test/repro/try_bare_variant_hidden_family.elisa"
set +e
stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1)"
stage0_status=$?
set -e
[[ "$stage0_status" -ne 0 ]] || fail "Stage0 accepted the two incompatible propagations"

stage0_rows="$(printf '%s\n' "$stage0_output" \
    | sed -E -n 's#^.*:([0-9]+):[0-9]+-[0-9]+: cannot propagate.*$#L\1#p' \
    | LC_ALL=C sort)"
stage1_output="$("$RPT" < "$FIXTURE")"
stage1_rows="$(printf '%s\n' "$stage1_output" \
    | sed -E -n 's#^[[:space:]]*L([0-9]+) cannot propagate.*$#L\1#p' \
    | LC_ALL=C sort)"
expected_rows="$(cat <<'EOF'
L24
L32
EOF
)"

[[ "$stage0_rows" == "$expected_rows" ]] || fail "Stage0 diagnostic lines changed: $stage0_rows"
[[ $(grep -cF "$FIXTURE:" <<< "$stage0_output") == 2 ]] || fail "Stage0 reported an unexpected diagnostic count: $stage0_output"
grep -q '^D 2$' <<< "$stage1_output" || fail "Stage1 reported an unexpected diagnostic count: $stage1_output"
[[ "$stage1_rows" == "$expected_rows" ]] || fail "Stage1 diagnostic lines differ: $stage1_output"

echo "try bare-variant hidden-family smoke OK: visible family shadowing and hidden sibling fallback match"
