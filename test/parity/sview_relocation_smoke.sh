#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac-stage0}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
BAD="$ROOT/test/parity/fixtures/sview_chained_growth_stale.elisa"
OPTIONAL_BAD="$ROOT/test/parity/fixtures/sview_optional_chained_growth_stale.elisa"
GOOD="$ROOT/test/parity/fixtures/sview_unrelated_growth_live.elisa"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-sview-relocation.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

fail() { echo "sview relocation smoke FAIL: $1" >&2; exit 1; }
[[ -x "$STAGE0" ]] || fail "missing Stage0 compiler: $STAGE0"
[[ -x "$STAGE1" ]] || fail "missing Stage1 compiler: $STAGE1"
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"

for stage in stage0 stage1; do
    if [[ "$stage" == stage0 ]]; then compiler="$STAGE0"; else compiler="$STAGE1"; fi

    bad_output="$WORK/$stage-stale-view.ll"
    bad_log="$bad_output.log"
    if "$compiler" -emit llvm -O0 -o "$bad_output" "$BAD" >"$bad_log" 2>&1; then
        fail "$stage accepted an sview after its chained darray backing was grown"
    fi
    rg -Fq 'storage dependency facts were invalidated by darray push of bytes' "$bad_log" \
        || fail "$stage rejected the stale view for an unrelated reason: $(tail -n 8 "$bad_log")"
    [[ ! -e "$bad_output" ]] || fail "$stage emitted LLVM for a stale sview"

    optional_output="$WORK/$stage-stale-optional-view.ll"
    optional_log="$optional_output.log"
    if "$compiler" -emit llvm -O0 -o "$optional_output" "$OPTIONAL_BAD" >"$optional_log" 2>&1; then
        fail "$stage accepted a present optional sview after its chained backing was grown"
    fi
    rg -Fq 'storage dependency facts were invalidated by darray push of bytes' "$optional_log" \
        || fail "$stage rejected the optional stale view for an unrelated reason: $(tail -n 8 "$optional_log")"
    [[ ! -e "$optional_output" ]] || fail "$stage emitted LLVM for a stale optional sview"

    good_output="$WORK/$stage-stable-view.ll"
    good_log="$good_output.log"
    "$compiler" -emit llvm -O0 -o "$good_output" "$GOOD" >"$good_log" 2>&1 \
        || fail "$stage rejected a view whose backing was not mutated when an unrelated darray grew: $(tail -n 8 "$good_log")"
done

echo "sview relocation smoke OK: chained backing growth invalidates present views and unrelated container growth preserves them under both stages"
