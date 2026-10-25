#!/usr/bin/env bash
# A cyclic type alias in a Try destination must diagnose without recursive failure.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/run_timeout.sh"
STAGE1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
bash "$REPO_ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN"
bash "$REPO_ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"

fail() {
    echo "try bare-variant alias-cycle shadow smoke FAIL: $1" >&2
    exit 1
}

FIXTURE="$REPO_ROOT/test/repro/try_bare_variant_alias_cycle_shadow.elisa"
ELISA_TIMEOUT_ESCALATE=1
set +e
stage0_output="$(elisa_run_timeout 30 "$ELISACORE_BIN" -emit semantic "$FIXTURE" 2>&1)"
stage0_status=$?
stage1_output="$(elisa_run_timeout 30 "$STAGE1" -emit semantic "$FIXTURE" 2>&1)"
stage1_status=$?
set -e

[[ "$stage0_status" -eq 1 ]] || fail "Stage0 did not return semantic diagnostics (status $stage0_status): $stage0_output"
[[ "$stage1_status" -eq 1 ]] || fail "Stage1 did not return semantic diagnostics (status $stage1_status): $stage1_output"
grep -q 'unknown type' <<< "$stage0_output" || fail "Stage0 did not report the alias cycle: $stage0_output"
grep -q 'unknown type' <<< "$stage1_output" || fail "Stage1 did not report the alias cycle: $stage1_output"
grep -q 'cannot propagate' <<< "$stage0_output" || fail "Stage0 did not reach the Try diagnostic: $stage0_output"
grep -q 'cannot propagate' <<< "$stage1_output" || fail "Stage1 did not reach the Try diagnostic: $stage1_output"

stage0_try_rows="$(printf '%s\n' "$stage0_output" \
    | sed -E -n 's#^.*:([0-9]+):[0-9]+-[0-9]+: cannot propagate.*$#L\1#p' \
    | LC_ALL=C sort)"
stage1_try_rows="$(printf '%s\n' "$stage1_output" \
    | sed -E -n 's#^[[:space:]]*L([0-9]+) cannot propagate.*$#L\1#p' \
    | LC_ALL=C sort)"
expected_try_rows="$(cat <<'EOF'
L16
EOF
)"
[[ "$stage0_try_rows" == "$expected_try_rows" ]] || fail "Stage0 Try diagnostics differ from the single expected destination mismatch: $stage0_output"
[[ "$stage1_try_rows" == "$expected_try_rows" ]] || fail "Stage1 Try diagnostics differ from the single expected destination mismatch: $stage1_output"
if grep -Eiq 'stack overflow|stack trace|panic:|runtime error:' <<< "$stage1_output"; then
    fail "Stage1 recursed while resolving the alias cycle: $stage1_output"
fi

echo "try bare-variant alias-cycle shadow smoke OK: Try analysis terminates with ordinary diagnostics"
