#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac-stage0}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
BAD="$ROOT/test/parity/fixtures/sview_chained_growth_stale.elisa"
OPTIONAL_BAD="$ROOT/test/parity/fixtures/sview_optional_chained_growth_stale.elisa"
GOOD="$ROOT/test/parity/fixtures/sview_unrelated_growth_live.elisa"
CROSS_FIELD_BAD="$ROOT/test/parity/fixtures/sview_cross_field_alias_stale.elisa"
DARRAY_ALIAS_BAD="$ROOT/test/parity/fixtures/sview_darray_copy_alias_stale.elisa"
AGGREGATE_BAD="$ROOT/test/repro/sview_aggregate_field_after_growth.elisa"
AGGREGATE_COPY_BAD="$ROOT/test/repro/sview_aggregate_copy_after_growth.elisa"
AGGREGATE_GOOD="$ROOT/test/parity/fixtures/sview_aggregate_field_unrelated_growth.elisa"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-sview-relocation.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

fail() { echo "sview relocation smoke FAIL: $1" >&2; exit 1; }

check_stage1_alias_stale() {
    local fixture="$1" expected="$2" label="$3"
    for optimization in 0 2; do
        output="$WORK/$label-stage1-O$optimization.ll"
        log="$output.log"
        if "$STAGE1" -emit llvm "-O$optimization" -o "$output" "$fixture" >"$log" 2>&1; then
            fail "Stage1 accepted $label after its shared darray backing was grown at O$optimization"
        fi
        rg -Fq "$expected" "$log" || fail "Stage1 rejected $label for an unrelated reason at O$optimization: $(tail -n 8 "$log")"
        [[ ! -e "$output" ]] || fail "Stage1 emitted LLVM for stale $label at O$optimization"
    done
}

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

check_stage1_alias_stale "$CROSS_FIELD_BAD" 'storage dependency facts were invalidated by darray push of parser' cross-field-alias
check_stage1_alias_stale "$DARRAY_ALIAS_BAD" 'storage dependency facts were invalidated by darray push of alias' darray-copy-alias
check_stage1_alias_stale "$AGGREGATE_BAD" 'storage dependency facts were invalidated by darray push of values' aggregate-field-alias
check_stage1_alias_stale "$AGGREGATE_COPY_BAD" 'storage dependency facts were invalidated by darray push of values' nested-aggregate-copy-alias

for optimization in 0 2; do
    aggregate_good_output="$WORK/aggregate-unrelated-growth-O$optimization.ll"
    aggregate_good_log="$aggregate_good_output.log"
    "$STAGE1" -emit llvm "-O$optimization" -o "$aggregate_good_output" "$AGGREGATE_GOOD" >"$aggregate_good_log" 2>&1 \
        || fail "Stage1 rejected an aggregate-held view when only an unrelated darray grew at O$optimization: $(tail -n 8 "$aggregate_good_log")"
done

echo "sview relocation smoke OK: chained/optional, cross-field, copied-container, aggregate-field, and nested aggregate-copy aliases invalidate after backing growth; unrelated growth stays live"
