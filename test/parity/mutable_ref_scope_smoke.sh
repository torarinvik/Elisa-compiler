#!/usr/bin/env bash
# Regression for scoped local metadata: a branch-local mutable reference must not leave
# stale entries in the parallel Scope arrays. The old mismatch lowered a later `<-` as a
# write through a zero reference and crashed at runtime.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

STAGE0="${ELISACORE_BIN:-${ELISA_CORE:-$ROOT/../../Go projects/structpy-tree}/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
FIXTURE="$ROOT/test/fixtures/mutable_heap_ref_local_rebind.elisa"

[[ -x "$STAGE1" ]] || { echo "mutable-ref scope smoke SKIP: no stage1 at $STAGE1" >&2; exit 0; }

run_case() {
    local compiler="$1"
    local tag="$2"
    local expected="$3"
    local object="$WORK/$tag.o"
    local binary="$WORK/$tag"
    "$compiler" -emit obj -O0 -o "$object" "$FIXTURE"
    clang -o "$binary" "$object"
    set +e
    "$binary"
    local actual=$?
    set -e
    [[ "$actual" -eq "$expected" ]] || {
        echo "mutable-ref scope smoke FAIL: $tag returned $actual, expected $expected" >&2
        exit 1
    }
}

run_case "$STAGE1" stage1 2
if [[ -x "$STAGE0" ]]; then
    run_case "$STAGE0" stage0 2
fi

echo "mutable-ref scope smoke OK: scoped zeroed reference rebind is safe"
