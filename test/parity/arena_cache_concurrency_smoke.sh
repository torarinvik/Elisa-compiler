#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
SOURCE="$ROOT/test/repro/arena_cache_concurrent_access.elisa"
source "$ROOT/test/parity/run_timeout.sh"

[[ -x "$STAGE1" ]] || { echo "arena cache concurrency smoke: missing stage1 compiler: $STAGE1" >&2; exit 2; }
[[ -x "$STAGE0" ]] || { echo "arena cache concurrency smoke: missing stage0 compiler: $STAGE0" >&2; exit 2; }
command -v clang >/dev/null 2>&1 || { echo "arena cache concurrency smoke: clang is required to link stage0 output" >&2; exit 2; }
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-arena-cache-concurrency.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
ulimit -c 0 || true

for optimization in 0 2; do
    stage1_executable="$WORK/stage1-O$optimization"
    stage0_archive="$WORK/stage0-O$optimization.a"
    stage0_executable="$WORK/stage0-O$optimization"
    log="$WORK/O$optimization.log"

    if ! "$STAGE1" -emit exe "-O$optimization" -o "$stage1_executable" "$SOURCE" >"$log" 2>&1; then
        echo "arena cache concurrency smoke: stage1 failed to compile at O$optimization" >&2
        cat "$log" >&2
        exit 1
    fi
    if ! "$STAGE0" -emit c-archive "-O$optimization" -o "$stage0_archive" "$SOURCE" >"$log" 2>&1; then
        echo "arena cache concurrency smoke: stage0 failed to compile at O$optimization" >&2
        cat "$log" >&2
        exit 1
    fi
    if ! clang -Wl,-dead_strip -o "$stage0_executable" "$stage0_archive" >"$log" 2>&1; then
        echo "arena cache concurrency smoke: failed to link stage0 output at O$optimization" >&2
        cat "$log" >&2
        exit 1
    fi

    for stage in stage0 stage1; do
        if [[ "$stage" == stage0 ]]; then executable="$stage0_executable"; else executable="$stage1_executable"; fi
        for repetition in 1 2 3; do
            run_log="$WORK/$stage-O$optimization-$repetition.log"
            if ! elisa_run_timeout 20 "$executable" >"$run_log" 2>&1; then
                echo "arena cache concurrency smoke: $stage failed at O$optimization, run $repetition" >&2
                cat "$run_log" >&2
                exit 1
            fi
        done
    done
done

echo "arena cache concurrency smoke OK: four workers repeatedly allocate and release independent arenas at O0/O2 on stage0/stage1"
