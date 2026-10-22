#!/usr/bin/env bash
# Try propagation must compare the source and destination variant subsets, including
# the cases where only the source or only the destination is restricted.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

fail() {
    echo "try error subset coverage smoke FAIL: $1" >&2
    exit 1
}

FIXTURE="$REPO_ROOT/test/repro/try_error_subset_coverage.elisa"
set +e
stage0_output="$("$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1)"
stage0_status=$?
set -e
[[ "$stage0_status" -ne 0 ]] || fail "Stage0 accepted the two incompatible propagations"

stage0_rows="$(printf '%s\n' "$stage0_output" \
    | sed -E -n 's#^.*:([0-9]+):[0-9]+-[0-9]+: (cannot propagate.*)$#L\1 \2#p' \
    | LC_ALL=C sort)"
stage0_diagnostic_count="$(printf '%s\n' "$stage0_output" | grep -cF "$FIXTURE:" || true)"
stage1_output="$("$RPT" < "$FIXTURE")"
stage1_rows="$(printf '%s\n' "$stage1_output" \
    | sed -E -n 's#^[[:space:]]*L([0-9]+) (cannot propagate.*)$#L\1 \2#p' \
    | LC_ALL=C sort)"
expected_rows="$(cat <<'EOF'
L21 cannot propagate error[First.Fault.Bad] from a function returning error[Second.Fault.Other]
L24 cannot propagate First.Fault from a function returning error[Second.Fault.Bad]
EOF
)"

[[ "$stage0_rows" == "$expected_rows" ]] || fail "Stage0 subset baseline changed:\n$stage0_rows"
[[ "$stage0_diagnostic_count" == 2 ]] || fail "Stage0 reported $stage0_diagnostic_count diagnostics, expected 2"
grep -q '^D 2$' <<< "$stage1_output" || fail "Stage1 reported an unexpected diagnostic count:\n$stage1_output"
[[ "$stage1_rows" == "$expected_rows" ]] || fail "Stage1 subset coverage differs:\n$stage1_rows"

echo "try error subset coverage smoke OK: restricted-source/full-destination passes; incompatible subsets are rejected by both compilers"
