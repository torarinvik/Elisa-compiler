#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac-stage0}"
SOURCE="$ROOT/test/repro/atomic_runtime_operations.elisa"
source "$ROOT/test/parity/run_timeout.sh"

fail() { echo "atomic-runtime smoke FAIL: $1" >&2; exit 1; }
[[ -x "$STAGE1" ]] || fail "missing stage1 compiler: $STAGE1"
[[ -x "$STAGE0" ]] || fail "missing stage0 compiler: $STAGE0"
command -v clang >/dev/null 2>&1 || fail "clang is required to link the stage0 archive"
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-atomic-runtime.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
ulimit -c 0 || true

for stage in stage0 stage1; do
    if [[ "$stage" == stage0 ]]; then compiler="$STAGE0"; else compiler="$STAGE1"; fi
    ir="$WORK/$stage.ll"
    log="$WORK/$stage-compile.log"
    if ! "$compiler" -emit llvm -O0 -o "$ir" "$SOURCE" >"$log" 2>&1; then
        fail "$stage failed to emit atomic IR: $(tail -n 12 "$log")"
    fi
    grep -Eq 'load atomic i64, .* acquire' "$ir" || fail "$stage omitted the acquire atomic load"
    grep -Eq 'store atomic i64 .* release' "$ir" || fail "$stage omitted the release atomic store"
    grep -Eq 'atomicrmw xchg .* acq_rel' "$ir" || fail "$stage omitted the acq_rel exchange"
    grep -Eq 'atomicrmw add .* acq_rel' "$ir" || fail "$stage omitted the acq_rel fetch_add"
    grep -Eq 'cmpxchg .* acq_rel acquire' "$ir" || fail "$stage omitted the acquire-failure compare_exchange"
done

for stage in stage0 stage1; do
    if [[ "$stage" == stage0 ]]; then compiler="$STAGE0"; else compiler="$STAGE1"; fi
    ir="$WORK/$stage-fence.ll"
    log="$WORK/$stage-fence-compile.log"
    if [[ "$stage" == stage1 ]]; then
        if ! ELISA_STAGE1_RUNTIME_STD=1 "$compiler" -emit llvm -O0 -o "$ir" "$ROOT/elisacore_std/elisacore_runtime_atomics_codegen_smoke.elisa" >"$log" 2>&1; then
            fail "stage1 failed to emit fence IR: $(tail -n 12 "$log")"
        fi
    elif ! "$compiler" -emit llvm -O0 -o "$ir" "$ROOT/elisacore_std/elisacore_runtime_atomics_codegen_smoke.elisa" >"$log" 2>&1; then
        fail "stage0 failed to emit fence IR: $(tail -n 12 "$log")"
    fi
    grep -Eq 'fence seq_cst' "$ir" || fail "$stage omitted the sequentially consistent fence"
    grep -Eq 'cmpxchg ptr .* acq_rel acquire' "$ir" || fail "$stage omitted pointer compare_exchange"
    grep -Eq 'atomicrmw xchg ptr .* acq_rel' "$ir" || fail "$stage omitted pointer exchange"
    grep -Eq 'load atomic i8, .* acquire' "$ir" || fail "$stage omitted bool atomic load"
    grep -Eq 'store atomic i8 .* release' "$ir" || fail "$stage omitted bool atomic store"
    grep -Eq 'load atomic double, .* acquire' "$ir" || fail "$stage omitted floating-point atomic load"
    grep -Eq 'store atomic double .* release' "$ir" || fail "$stage omitted floating-point atomic store"
done

for optimization in 0 2; do
    stage1_executable="$WORK/stage1-O$optimization"
    stage0_archive="$WORK/stage0-O$optimization.a"
    stage0_executable="$WORK/stage0-O$optimization"
    log="$WORK/O$optimization.log"
    if ! "$STAGE1" -emit exe "-O$optimization" -o "$stage1_executable" "$SOURCE" >"$log" 2>&1; then
        fail "stage1 failed to link at O$optimization: $(tail -n 12 "$log")"
    fi
    if ! "$STAGE0" -emit c-archive "-O$optimization" -o "$stage0_archive" "$SOURCE" >"$log" 2>&1; then
        fail "stage0 failed to emit archive at O$optimization: $(tail -n 12 "$log")"
    fi
    if ! clang -Wl,-dead_strip -o "$stage0_executable" "$stage0_archive" >"$log" 2>&1; then
        fail "could not link stage0 archive at O$optimization: $(tail -n 12 "$log")"
    fi
    for stage in stage0 stage1; do
        if [[ "$stage" == stage0 ]]; then executable="$stage0_executable"; else executable="$stage1_executable"; fi
        for repetition in 1 2 3; do
            run_log="$WORK/$stage-O$optimization-$repetition.log"
            if ! elisa_run_timeout 20 "$executable" >"$run_log" 2>&1; then
                fail "$stage failed the atomic correctness run at O$optimization ($repetition): $(tail -n 12 "$run_log")"
            fi
        done
    done
done

echo "atomic-runtime smoke OK: integer/bool/pointer/float atomics, fence IR, pointer exchange, and 4-thread CAS increments at O0/O2 on Stage0/Stage1"
