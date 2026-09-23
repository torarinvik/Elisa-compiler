#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
source "$ROOT/test/parity/run_timeout.sh"

[[ -x "$STAGE1" ]] || { echo "fixed-buffer safety smoke: missing stage1 compiler: $STAGE1" >&2; exit 2; }
[[ -x "$STAGE0" ]] || { echo "fixed-buffer safety smoke: missing stage0 compiler: $STAGE0" >&2; exit 2; }
command -v clang >/dev/null 2>&1 || { echo "fixed-buffer safety smoke: clang is required to link the stage0 runtime" >&2; exit 2; }
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-fixed-buffer.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
ulimit -c 0 || true

compile_case() {
    local compiler="$1" stage="$2" case_name="$3" optimization="$4"
    local source_file="$ROOT/test/parity/fixtures/fixed_buffer_${case_name}.elisa"
    local stem="$WORK/${stage}-${case_name}-O${optimization}"
    local log="$stem.compile.log"
    if [[ "$stage" == stage1 ]]; then
        if ! "$compiler" -emit exe "-O${optimization}" -o "$stem" "$source_file" >"$log" 2>&1; then
            echo "fixed-buffer safety smoke: stage1 failed to compile $case_name at O$optimization" >&2
            cat "$log" >&2
            exit 1
        fi
    else
        local archive="$stem.a"
        if ! "$compiler" -emit c-archive "-O${optimization}" -o "$archive" "$source_file" >"$log" 2>&1; then
            echo "fixed-buffer safety smoke: stage0 failed to compile $case_name at O$optimization" >&2
            cat "$log" >&2
            exit 1
        fi
        if ! clang -Wl,-dead_strip -o "$stem" "$archive" >"$log" 2>&1; then
            echo "fixed-buffer safety smoke: failed to link stage0 $case_name at O$optimization" >&2
            cat "$log" >&2
            exit 1
        fi
    fi
}

for optimization in 0 2; do
    for case_name in valid alignment_overflow invalid_mark forward_rewind alloc_failure; do
        compile_case "$STAGE1" stage1 "$case_name" "$optimization"
        compile_case "$STAGE0" stage0 "$case_name" "$optimization"
    done
done

for optimization in 0 2; do
    for stage in stage1 stage0; do
        valid="$WORK/${stage}-valid-O${optimization}"
        if ! elisa_run_timeout 10 "$valid" >"$valid.run.log" 2>&1; then
            echo "fixed-buffer safety smoke: valid allocation/resize behavior failed on $stage O$optimization" >&2
            cat "$valid.run.log" >&2
            exit 1
        fi
        for case_name in alignment_overflow invalid_mark forward_rewind alloc_failure; do
            executable="$WORK/${stage}-${case_name}-O${optimization}"
            log="$executable.run.log"
            set +e
            elisa_run_timeout 10 "$executable" >"$log" 2>&1
            run_status=$?
            set -e
            [[ "$run_status" -ne 0 ]] || { echo "fixed-buffer safety smoke: $case_name returned normally on $stage O$optimization" >&2; exit 1; }
            expected="fixed-buffer size arithmetic overflow"
            if [[ "$case_name" == invalid_mark ]]; then
                expected="fixed-buffer rewind mark exceeds allocator capacity"
            elif [[ "$case_name" == forward_rewind ]]; then
                expected="fixed-buffer rewind mark advances the allocator"
            elif [[ "$case_name" == alloc_failure ]]; then
                expected="fixed-buffer allocation failed"
            fi
            rg -Fq "$expected" "$log" || { echo "fixed-buffer safety smoke: $case_name failed without expected panic on $stage O$optimization" >&2; cat "$log" >&2; exit 1; }
        done
    done
done

echo "fixed-buffer safety smoke OK: resize, alignment, cursor, and rewind checks hold on stage0/stage1 at O0/O2"
