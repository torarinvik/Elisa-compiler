#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac-stage0}"
FIXTURE="$ROOT/test/parity/fixtures/darray_cstr_checked_growth.elisa"

fail() { echo "darray cstr checked-growth smoke FAIL: $1" >&2; exit 1; }
[[ -x "$STAGE0" ]] || fail "missing Stage0 compiler: $STAGE0"
[[ -x "$STAGE1" ]] || fail "missing Stage1 compiler: $STAGE1"
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-cstr-growth.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

for stage in stage0 stage1; do
    compiler="$STAGE0"
    [[ "$stage" != stage1 ]] || compiler="$STAGE1"
    output="$WORK/$stage.ll"
    log="$WORK/$stage.log"
    "$compiler" -emit llvm -O0 -o "$output" "$FIXTURE" >"$log" 2>&1 \
        || fail "$stage rejected cstr construction: $(tail -n 12 "$log")"
    rg -Fq '@llvm.uadd.with.overflow' "$output" \
        || fail "$stage did not check count + terminator for overflow"
done

echo "darray cstr checked-growth smoke OK: both backends trap instead of wrapping count + 1"
