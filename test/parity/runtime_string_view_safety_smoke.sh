#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
source "$ROOT/test/parity/run_timeout.sh"

[[ -x "$STAGE1" ]] || { echo "runtime string view smoke: missing stage1 compiler: $STAGE1" >&2; exit 2; }
[[ -x "$STAGE0" ]] || { echo "runtime string view smoke: missing stage0 compiler: $STAGE0" >&2; exit 2; }
command -v clang >/dev/null 2>&1 || { echo "runtime string view smoke: clang is required to link the stage0 runtime" >&2; exit 2; }
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-runtime-sview.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
ulimit -c 0 || true
SOURCE="$ROOT/test/parity/fixtures/runtime_string_view_invalid_length.elisa"

compile_case() {
    local compiler="$1" stage="$2" optimization="$3"
    local stem="$WORK/${stage}-O${optimization}"
    local log="$stem.compile.log"
    if [[ "$stage" == stage1 ]]; then
        if ! "$compiler" -emit exe "-O${optimization}" -o "$stem" "$SOURCE" >"$log" 2>&1; then
            echo "runtime string view smoke: stage1 failed to compile at O$optimization" >&2
            cat "$log" >&2
            exit 1
        fi
    else
        local archive="$stem.a"
        if ! "$compiler" -emit c-archive "-O${optimization}" -o "$archive" "$SOURCE" >"$log" 2>&1; then
            echo "runtime string view smoke: stage0 failed to compile at O$optimization" >&2
            cat "$log" >&2
            exit 1
        fi
        if ! clang -Wl,-dead_strip -o "$stem" "$archive" >"$log" 2>&1; then
            echo "runtime string view smoke: failed to link stage0 at O$optimization" >&2
            cat "$log" >&2
            exit 1
        fi
    fi
}

for optimization in 0 2; do
    compile_case "$STAGE1" stage1 "$optimization"
    compile_case "$STAGE0" stage0 "$optimization"
done

for optimization in 0 2; do
    for stage in stage1 stage0; do
        executable="$WORK/${stage}-O${optimization}"
        log="$executable.run.log"
        set +e
        elisa_run_timeout 10 "$executable" >"$log" 2>&1
        run_status=$?
        set -e
        [[ "$run_status" -eq 0 ]] || { echo "runtime string view smoke: malformed negative lengths accessed invalid pointers on $stage O$optimization (status $run_status)" >&2; cat "$log" >&2; exit 1; }
    done
done

echo "runtime string view smoke OK: malformed lengths fail closed and valid view operations agree on stage0/stage1 at O0/O2"
