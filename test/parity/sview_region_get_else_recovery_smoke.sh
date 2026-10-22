#!/usr/bin/env bash
# The GetElse recovery is a separate path; region stores in it still need checking.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
SOURCES=(
    "$ROOT/test/repro/sview_region_get_else_recovery.neg.elisa"
    "$ROOT/test/repro/sview_region_get_else_block_initializer.neg.elisa"
    "$ROOT/test/repro/sview_region_get_else_taint_join.neg.elisa"
    "$ROOT/test/repro/sview_region_get_else_match_annotated_scrutinee.neg.elisa"
)
STAGE1_ONLY_SOURCES=(
    "$ROOT/test/repro/sview_region_get_else_nested_call_return.neg.elisa"
    "$ROOT/test/repro/sview_region_get_else_nested_array_return.neg.elisa"
)
STAGE1_ONLY_STORE_SOURCES=(
    "$ROOT/test/repro/sview_region_block_live_tail.neg.elisa"
    "$ROOT/test/repro/sview_region_get_else_match_arm_scope.neg.elisa"
    "$ROOT/test/repro/sview_region_get_else_match_continuing_arm.neg.elisa"
    "$ROOT/test/repro/sview_region_get_else_match_payload_binder.neg.elisa"
    "$ROOT/test/repro/sview_region_get_else_while_join.neg.elisa"
    "$ROOT/test/repro/sview_region_if_taint_join.neg.elisa"
    "$ROOT/test/repro/sview_region_match_taint_join.neg.elisa"
    "$ROOT/test/repro/sview_region_statement_match_taint_join.neg.elisa"
    "$ROOT/test/repro/sview_region_for_taint_join.neg.elisa"
    "$ROOT/test/repro/sview_region_for_named_taint_join.neg.elisa"
    "$ROOT/test/repro/sview_region_for_named_push_taint.neg.elisa"
    "$ROOT/test/repro/sview_region_comprehension_store.neg.elisa"
)
STAGE1_ONLY_POSITIVE_SOURCES=(
    "$ROOT/test/repro/sview_region_block_dead_tail.pos.elisa"
    "$ROOT/test/repro/sview_region_get_else_match_terminating_arm.pos.elisa"
    "$ROOT/test/repro/sview_region_get_else_match_terminating_call_arg.pos.elisa"
    "$ROOT/test/repro/sview_region_get_else_match_terminating_binary_operand.pos.elisa"
    "$ROOT/test/repro/sview_region_get_else_match_terminating_short_circuit.pos.elisa"
    "$ROOT/test/repro/sview_region_if_terminating_branch.pos.elisa"
    "$ROOT/test/repro/sview_region_match_terminating_branch.pos.elisa"
    "$ROOT/test/repro/sview_region_statement_match_literal_reachability.pos.elisa"
    "$ROOT/test/repro/sview_region_get_else_while_false.pos.elisa"
    "$ROOT/test/repro/sview_region_for_named_push_static.pos.elisa"
)

fail() { echo "sview GetElse recovery region smoke FAIL: $1" >&2; exit 1; }
[[ -x "$STAGE1" ]] || fail "missing Stage1 compiler: $STAGE1"
[[ -x "$STAGE0" ]] || fail "missing Stage0 compiler: $STAGE0"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-sview-get-else-recovery.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

for stage in stage0 stage1; do
    if [[ "$stage" == stage0 ]]; then compiler="$STAGE0"; else compiler="$STAGE1"; fi
    for source in "${SOURCES[@]}"; do
        name="$(basename "$source" .neg.elisa)"
        if "$compiler" -emit llvm -O0 -o "$WORK/$stage-$name.ll" "$source" >"$WORK/$stage-$name.log" 2>&1; then
            fail "$stage accepted a short-lived view stored into the outer region in GetElse recovery ($name)"
        fi
        grep -Fq 'value in region "inner" is stored into longer-lived region "outer"' "$WORK/$stage-$name.log" \
            || fail "$stage rejection did not identify the inner-to-outer lifetime escape ($name): $(tail -n 8 "$WORK/$stage-$name.log")"
    done
done

# Stage0 currently accepts this nested-return shape, so keep its gap visible as a
# Stage1-specific regression instead of asserting parity with the known Stage0 miss.
for source in "${STAGE1_ONLY_SOURCES[@]}"; do
    name="$(basename "$source" .neg.elisa)"
    if "$STAGE1" -emit llvm -O0 -o "$WORK/stage1-$name.ll" "$source" >"$WORK/stage1-$name.log" 2>&1; then
        fail "stage1 accepted a region-local view returned from a nested GetElse call argument ($name)"
    fi
    grep -Fq 'value allocated in region "inner" escapes via return' "$WORK/stage1-$name.log" \
        || fail "stage1 rejection did not identify the nested region return escape ($name): $(tail -n 8 "$WORK/stage1-$name.log")"
done

for source in "${STAGE1_ONLY_STORE_SOURCES[@]}"; do
    name="$(basename "$source" .neg.elisa)"
    if "$STAGE1" -emit llvm -O0 -o "$WORK/stage1-$name.ll" "$source" >"$WORK/stage1-$name.log" 2>&1; then
        fail "stage1 accepted an inner-to-outer store in a GetElse recovery branch ($name)"
    fi
    grep -Fq 'value in region "inner" is stored into longer-lived region "outer"' "$WORK/stage1-$name.log" \
        || fail "stage1 rejection did not identify the inner-to-outer lifetime escape ($name): $(tail -n 8 "$WORK/stage1-$name.log")"
done

for source in "${STAGE1_ONLY_POSITIVE_SOURCES[@]}"; do
    name="$(basename "$source" .pos.elisa)"
    if ! "$STAGE1" -emit llvm -O0 -o "$WORK/stage1-$name.ll" "$source" >"$WORK/stage1-$name.log" 2>&1; then
        fail "stage1 propagated a region taint from unreachable recovery control flow ($name): $(tail -n 8 "$WORK/stage1-$name.log")"
    fi
done

echo "sview GetElse recovery region smoke OK: both stages inspect recovery stores; Stage1 inspects nested returns and expression-arm flow"
