#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/scripts/sview_guard_page_runtime_inputs.sh"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-sview-runtime-inputs.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

mkdir -p "$WORK/base/bin" "$WORK/base/build/runtime" "$WORK/candidate/bin" "$WORK/candidate/build/runtime"
: > "$WORK/base/build/runtime/elisacore_runtime.o"
: > "$WORK/candidate/build/runtime/elisacore_runtime.o"
: > "$WORK/shared-runtime.o"
BASELINE="$WORK/base/bin/elisac"
CANDIDATE="$WORK/candidate/bin/elisac-stage1"
: > "$BASELINE"
: > "$CANDIDATE"

expect_reject() {
    local expected="$1"; shift
    local output status=0
    output="$(env -i PATH="$PATH" ROOT="$WORK" HELPER="$ROOT/scripts/sview_guard_page_runtime_inputs.sh" BASELINE="$BASELINE" CANDIDATE="$CANDIDATE" "$@" bash -c 'source "$HELPER"; sview_guard_page_resolve_runtimes "$ROOT" "$BASELINE" "$CANDIDATE"' 2>&1)" || status=$?
    [[ "$status" -eq 2 && "$output" == *"$expected"* ]] || {
        printf 'expected resolver rejection (%s), got status=%s output=%s\n' "$expected" "$status" "$output" >&2
        return 1
    }
}

# Separate overrides remain independent even when the legacy variable is absent.
ELISA_SVIEW_BASELINE_RUNTIME="$WORK/base/build/runtime/elisacore_runtime.o"
ELISA_SVIEW_CANDIDATE_RUNTIME="$WORK/candidate/build/runtime/elisacore_runtime.o"
unset ELISA_RUNTIME_OBJ ELISA_SVIEW_BASELINE_ABI_ID ELISA_SVIEW_CANDIDATE_ABI_ID || true
sview_guard_page_resolve_runtimes "$WORK" "$BASELINE" "$CANDIDATE"
[[ "$SVIEW_BASELINE_RUNTIME" != "$SVIEW_CANDIDATE_RUNTIME" ]]

# A legacy shared override across distinct compiler roots fails closed without identity.
expect_reject "64-character SHA-256 ELISA_SVIEW_BASELINE_ABI_ID" \
    ELISA_RUNTIME_OBJ="$WORK/shared-runtime.o"
expect_reject "64-character SHA-256 ELISA_SVIEW_BASELINE_ABI_ID" \
    ELISA_RUNTIME_OBJ="$WORK/shared-runtime.o" \
    ELISA_SVIEW_BASELINE_ROOT="$WORK/base" ELISA_SVIEW_CANDIDATE_ROOT="$WORK/base"

# A declared ABI mismatch is rejected, while equal identities retain compatibility.
expect_reject "64-character SHA-256 ELISA_SVIEW_BASELINE_ABI_ID" \
    ELISA_RUNTIME_OBJ="$WORK/shared-runtime.o" \
    ELISA_SVIEW_BASELINE_ABI_ID=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
    ELISA_SVIEW_CANDIDATE_ABI_ID=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb

# Split selection cannot silently fall back to the legacy runtime or a nonexistent file.
expect_reject "do not mix ELISA_RUNTIME_OBJ" \
    ELISA_RUNTIME_OBJ="$WORK/shared-runtime.o" \
    ELISA_SVIEW_BASELINE_RUNTIME="$WORK/base/build/runtime/elisacore_runtime.o"
expect_reject "missing candidate runtime object" \
    ELISA_SVIEW_BASELINE_RUNTIME="$WORK/base/build/runtime/elisacore_runtime.o" \
    ELISA_SVIEW_CANDIDATE_RUNTIME="$WORK/no-such-runtime.o"
env -i PATH="$PATH" ROOT="$WORK" HELPER="$ROOT/scripts/sview_guard_page_runtime_inputs.sh" BASELINE="$BASELINE" CANDIDATE="$CANDIDATE" \
    ELISA_RUNTIME_OBJ="$WORK/shared-runtime.o" \
    ELISA_SVIEW_BASELINE_ABI_ID=cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc \
    ELISA_SVIEW_CANDIDATE_ABI_ID=cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc \
    bash -c 'source "$HELPER"; sview_guard_page_resolve_runtimes "$ROOT" "$BASELINE" "$CANDIDATE"; [[ "$SVIEW_BASELINE_RUNTIME" == "$SVIEW_CANDIDATE_RUNTIME" ]]'

# One source root establishes identity for its independently derived default path.
ELISA_SVIEW_BASELINE_RUNTIME=""
ELISA_SVIEW_CANDIDATE_RUNTIME=""
unset ELISA_RUNTIME_OBJ
same_root_base="$WORK/base/bin/elisac"
same_root_candidate="$WORK/base/bin/elisac-stage1"
sview_guard_page_resolve_runtimes "$WORK/base" "$same_root_base" "$same_root_candidate"
[[ "$SVIEW_BASELINE_RUNTIME" == "$SVIEW_CANDIDATE_RUNTIME" ]]

echo "sview guard-page runtime input selection tests passed"
