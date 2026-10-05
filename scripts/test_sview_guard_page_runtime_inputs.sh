#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/scripts/sview_guard_page_runtime_inputs.sh"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-sview-runtime-inputs.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

: > "$WORK/baseline-runtime.o"
: > "$WORK/candidate-runtime.o"

expect_reject() {
    local expected="$1"; shift
    local output status=0
    output="$(env -i PATH="$PATH" HELPER="$ROOT/scripts/sview_guard_page_runtime_inputs.sh" "$@" \
        bash -c 'source "$HELPER"; sview_guard_page_resolve_runtimes /unused /unused /unused' 2>&1)" || status=$?
    [[ "$status" -eq 2 && "$output" == *"$expected"* ]] || {
        printf 'expected resolver rejection (%s), got status=%s output=%s\n' "$expected" "$status" "$output" >&2
        return 1
    }
}

# Separate runtime paths are selected independently and may both be the same
# explicit path when the caller has independently established compatibility.
ELISA_SVIEW_BASELINE_RUNTIME="$WORK/baseline-runtime.o"
ELISA_SVIEW_CANDIDATE_RUNTIME="$WORK/candidate-runtime.o"
unset ELISA_RUNTIME_OBJ || true
sview_guard_page_resolve_runtimes /unused /unused /unused
[[ "$SVIEW_BASELINE_RUNTIME" == "$WORK/baseline-runtime.o" ]]
[[ "$SVIEW_CANDIDATE_RUNTIME" == "$WORK/candidate-runtime.o" ]]

ELISA_SVIEW_CANDIDATE_RUNTIME="$WORK/baseline-runtime.o"
sview_guard_page_resolve_runtimes /unused /unused /unused
[[ "$SVIEW_BASELINE_RUNTIME" == "$SVIEW_CANDIDATE_RUNTIME" ]]

# The legacy shared variable is deliberately refused, even if split variables
# are also present; callers must make both runtime choices visible.
expect_reject "ELISA_RUNTIME_OBJ is ambiguous" ELISA_RUNTIME_OBJ="$WORK/baseline-runtime.o"
expect_reject "ELISA_RUNTIME_OBJ is ambiguous" \
    ELISA_RUNTIME_OBJ="$WORK/baseline-runtime.o" \
    ELISA_SVIEW_BASELINE_RUNTIME="$WORK/baseline-runtime.o" \
    ELISA_SVIEW_CANDIDATE_RUNTIME="$WORK/candidate-runtime.o"
expect_reject "set ELISA_SVIEW_BASELINE_RUNTIME explicitly" \
    ELISA_SVIEW_CANDIDATE_RUNTIME="$WORK/candidate-runtime.o"
expect_reject "set ELISA_SVIEW_CANDIDATE_RUNTIME explicitly" \
    ELISA_SVIEW_BASELINE_RUNTIME="$WORK/baseline-runtime.o"
expect_reject "missing candidate runtime object" \
    ELISA_SVIEW_BASELINE_RUNTIME="$WORK/baseline-runtime.o" \
    ELISA_SVIEW_CANDIDATE_RUNTIME="$WORK/missing-runtime.o"

echo "sview guard-page runtime input selection tests passed"
