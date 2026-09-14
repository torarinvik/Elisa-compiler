#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/structpy-tree/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
clang -c "$ROOT/test/parity/profile_hooks.c" -o "$WORK/hooks.o"
for fixture in loop_scratch_inferred loop_region_reuse_exits loop_scratch_borrow_fallback loop_scratch_outer_growth region_container_metadata_copy loop_scratch_summary_chain loop_scratch_summary_unknown loop_scratch_summary_overload region_parameter_in_scope loop_scratch_summary_reduction loop_scratch_surviving_output loop_scratch_summary_nonlocal loop_scratch_summary_module loop_scratch_summary_multi_mutation trace_function_prologue_location; do
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

# Mutation, overload ambiguity, and nonlocal stores remain outside the proof.
for fixture in loop_scratch_summary_unknown loop_scratch_summary_overload loop_scratch_summary_nonlocal loop_scratch_summary_multi_mutation; do
    "$STAGE1" -emit llvm -O0 -o "$WORK/fallback.ll" "$ROOT/test/differential/cases/$fixture.elisa"
    if grep -q '__loop_scratch' "$WORK/fallback.ll"; then
        echo "unsafe scratch inference in $fixture" >&2
        exit 1
    fi
done
for fixture in loop_scratch_borrow_fallback loop_scratch_summary_chain loop_scratch_outer_growth loop_scratch_summary_reduction loop_scratch_surviving_output loop_scratch_summary_module; do
    "$STAGE1" -emit llvm -O0 -o "$WORK/summary.ll" "$ROOT/test/differential/cases/$fixture.elisa"
    grep -q '__loop_scratch' "$WORK/summary.ll"
done
# Opt-in explanations describe both a proof and its first blocking operation.
ELISA_EXPLAIN_MEMORY=1 "$STAGE1" -emit obj -o "$WORK/explain.o" "$ROOT/test/differential/cases/loop_scratch_summary_reduction.elisa" > "$WORK/explain.txt"
grep -q 'helper positive_sum .*read-only borrow' "$WORK/explain.txt"
grep -q 'loop xs .*reuse scratch' "$WORK/explain.txt"
ELISA_EXPLAIN_MEMORY=1 "$STAGE1" -emit obj -o "$WORK/reject.o" "$ROOT/test/differential/cases/loop_scratch_summary_nonlocal.elisa" > "$WORK/reject.txt"
grep -q 'write to borrowed parameter or nonlocal target' "$WORK/reject.txt"
grep -q 'keep original region' "$WORK/reject.txt"
# Every overload receives its own debug subprogram, selected by declaration line.
"$STAGE1" -emit llvm -g -O0 -o "$WORK/overload-debug.ll" "$ROOT/test/differential/cases/loop_scratch_summary_overload.elisa"
python3 - "$WORK/overload-debug.ll" <<'PY_DEBUG'
import pathlib, sys
lines = [s for s in pathlib.Path(sys.argv[1]).read_text().splitlines()
         if s.startswith('define ') and '@first' in s]
assert len(lines) == 2 and all('!dbg !' in s for s in lines), lines
PY_DEBUG
# Each function prologue starts without the previous function's debug location.
"$STAGE1" -emit obj -g -ftrace -O2 -o "$WORK/prologue.o" "$ROOT/test/differential/cases/trace_function_prologue_location.elisa"
clang -Wl,-dead_strip -o "$WORK/prologue" "$WORK/prologue.o" "$WORK/hooks.o" "$ROOT/build/runtime/elisacore_runtime.o"
"$WORK/prologue"
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
