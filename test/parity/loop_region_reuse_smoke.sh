#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/structpy-tree/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
clang -c "$ROOT/test/parity/profile_hooks.c" -o "$WORK/hooks.o"
for fixture in loop_scratch_inferred loop_region_reuse_exits loop_scratch_borrow_fallback loop_scratch_outer_growth region_container_metadata_copy loop_scratch_summary_chain loop_scratch_summary_unknown loop_scratch_summary_overload region_parameter_in_scope; do
    for stage in 0 1; do
        compiler="$STAGE0"
        [[ "$stage" == 0 ]] || compiler="$STAGE1"
        "$compiler" -emit obj -O2 -o "$WORK/result.o" "$ROOT/test/differential/cases/$fixture.elisa"
        clang -Wl,-dead_strip -o "$WORK/result" "$WORK/result.o" "$WORK/hooks.o" "$ROOT/build/runtime/elisacore_runtime.o"
        "$WORK/result" > "$WORK/output$stage"
    done
    cmp "$WORK/output0" "$WORK/output1"
    printf '%s: stage0/stage1 runtime PASS\n' "$fixture"
done

# Mutation and outer growth remain outside the summary proof.
for fixture in loop_scratch_summary_unknown loop_scratch_summary_overload loop_scratch_outer_growth; do
    "$STAGE1" -emit llvm -O0 -o "$WORK/fallback.ll" "$ROOT/test/differential/cases/$fixture.elisa"
    if grep -q '__loop_scratch' "$WORK/fallback.ll"; then
        echo "unsafe scratch inference in $fixture" >&2
        exit 1
    fi
done
for fixture in loop_scratch_borrow_fallback loop_scratch_summary_chain; do
    "$STAGE1" -emit llvm -O0 -o "$WORK/summary.ll" "$ROOT/test/differential/cases/$fixture.elisa"
    grep -q '__loop_scratch' "$WORK/summary.ll"
done
# Trace-value argument order must remain compatible with the collector ABI.
"$STAGE1" -emit obj -ftrace -O2 -o "$WORK/traced.o" "$ROOT/test/differential/cases/loop_scratch_inferred.elisa"

cat > "$WORK/escape.elisa" <<'ELISA'
struct Box:
    count: darray[i64]
def main() -> i64:
    out: mutable darray[i64] = []
    region scratch(4096):
        xs: mutable darray[i64] = []
        xs.push(42)
        box: Box = Box{count: xs}
        out <- box.count
    return out[0]
ELISA
# Preserve stage1's existing rejection. Stage0 currently accepts this separate
# user-field escape; it is not used as a negative oracle for this regression.
for compiler in "$STAGE1"; do
    if "$compiler" -emit obj -o "$WORK/escape.o" "$WORK/escape.elisa" > "$WORK/rejection" 2>&1; then
        echo "a user-defined count field incorrectly lost its region lifetime" >&2
        exit 1
    fi
    grep -q 'region' "$WORK/rejection"
done
