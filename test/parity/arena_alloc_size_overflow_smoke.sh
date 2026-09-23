#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
source "$ROOT/test/parity/run_timeout.sh"

[[ -x "$STAGE1" ]] || { echo "arena allocation overflow smoke: missing stage1 compiler: $STAGE1" >&2; exit 2; }
[[ -x "$STAGE0" ]] || { echo "arena allocation overflow smoke: missing stage0 compiler: $STAGE0" >&2; exit 2; }
command -v clang >/dev/null 2>&1 || { echo "arena allocation overflow smoke: clang is required to link the stage0 runtime" >&2; exit 2; }
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-arena-size-overflow.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
ulimit -c 0 || true

compile_case() {
    local compiler="$1" stage="$2" case_name="$3" optimization="$4"
    local source_file="$ROOT/test/parity/fixtures/arena_alloc_size_${case_name}.elisa"
    local stem="$WORK/${stage}-${case_name}-O${optimization}"
    local log="$stem.compile.log"
    if [[ "$stage" == stage1 ]]; then
        if ! "$compiler" -emit exe "-O${optimization}" -o "$stem" "$source_file" >"$log" 2>&1; then
            echo "arena allocation overflow smoke: stage1 failed to compile $case_name at O$optimization" >&2
            cat "$log" >&2
            exit 1
        fi
    else
        local archive="$stem.a"
        if ! "$compiler" -emit c-archive "-O${optimization}" -o "$archive" "$source_file" >"$log" 2>&1; then
            echo "arena allocation overflow smoke: stage0 failed to compile $case_name at O$optimization" >&2
            cat "$log" >&2
            exit 1
        fi
        # The O0 c-archive also contains unused runtime entry points such as va_copy
        # that are supplied only when those features are used. Dead-strip unreachable
        # sections so this isolated allocator fixture need not stub unrelated varargs.
        if ! clang -Wl,-dead_strip -o "$stem" "$archive" >"$log" 2>&1; then
            echo "arena allocation overflow smoke: failed to link stage0 $case_name at O$optimization" >&2
            cat "$log" >&2
            exit 1
        fi
    fi
}

for optimization in 0 2; do
    for case_name in valid overflow; do
        compile_case "$STAGE1" stage1 "$case_name" "$optimization"
        compile_case "$STAGE0" stage0 "$case_name" "$optimization"
    done
done

for optimization in 0 2; do
    for stage in stage1 stage0; do
        valid="$WORK/${stage}-valid-O${optimization}"
        overflow="$WORK/${stage}-overflow-O${optimization}"
        valid_log="$valid.run.log"
        overflow_log="$overflow.run.log"
        set +e
        elisa_run_timeout 10 "$valid" >"$valid_log" 2>&1
        valid_status=$?
        elisa_run_timeout 10 "$overflow" >"$overflow_log" 2>&1
        overflow_status=$?
        set -e
        [[ "$valid_status" -eq 0 ]] || { echo "arena allocation overflow smoke: valid zero/small allocations failed on $stage O$optimization (status $valid_status)" >&2; cat "$valid_log" >&2; exit 1; }
        [[ "$overflow_status" -ne 0 ]] || { echo "arena allocation overflow smoke: usize-max byte request returned normally on $stage O$optimization" >&2; exit 1; }
        rg -Fq "arena allocation size overflow" "$overflow_log" || { echo "arena allocation overflow smoke: overflow failed without the checked-size panic on $stage O$optimization" >&2; cat "$overflow_log" >&2; exit 1; }
    done
done

echo "arena allocation overflow smoke OK: zero/small requests succeed; usize-max byte requests trap on stage0/stage1 at O0/O2"
