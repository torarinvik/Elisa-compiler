#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$ROOT/test/parity/run_timeout.sh"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-submit-store.XXXXXX")"
source "$ROOT/test/parity/control_artifacts.sh"
elisa_control_artifacts "$WORK"
if ! elisa_run_timeout 300 env -u ELISA_STAGE1_RUNTIME_STD "$STAGE1" -emit llvm -O0 -o "$WORK/control.ll" "$ROOT/test/parity/submit_store_capture_control.elisa" >"$WORK/build-llvm.log" 2>&1; then
    cat "$WORK/build-llvm.log" >&2
    exit 1
fi
awk '/^define .*@main\(/,/^}/' "$WORK/control.ll" >"$WORK/main.ll"
secondary_pool_submits=$(grep -Ec 'call .*@pool_submit1[^;]*ptr %[^, )]*secondary_workers' "$WORK/main.ll" || true)
if [[ "$secondary_pool_submits" -ne 2 ]]; then
    echo "same-line selector lowering used secondary_workers $secondary_pool_submits times; expected 2" >&2
    grep -n 'call .*@pool_submit1' "$WORK/main.ll" >&2 || true
    exit 1
fi
generated_thunks=$(grep -Ec '^define .*@__submit_store_thunk_[1-9][0-9]*\(' "$WORK/control.ll" || true)
if [[ "$generated_thunks" -ne 7 ]] || ! grep -Eq '^define .*@__submit_store_thunk_0\(' "$WORK/control.ll"; then
    echo "capture thunk naming emitted $generated_thunks unique thunks or collided with the source symbol" >&2
    grep -n '@__submit_store_thunk_' "$WORK/control.ll" >&2 || true
    exit 1
fi
for level in O0 O2; do
    if ! elisa_run_timeout 300 env -u ELISA_STAGE1_RUNTIME_STD "$STAGE1" -emit exe "-$level" -o "$WORK/control-$level" "$ROOT/test/parity/submit_store_capture_control.elisa" >"$WORK/build-$level.log" 2>&1; then
        cat "$WORK/build-$level.log" >&2
        exit 1
    fi
    for run in 1 2 3; do
        if ! elisa_run_timeout 30 "$WORK/control-$level" >"$WORK/run-$level-$run.log" 2>&1; then
            cat "$WORK/run-$level-$run.log" >&2
            echo "submit store capture failed at $level, run $run" >&2
            exit 1
        fi
    done
    nested_output="$WORK/nested-$level"
    nested_log="$WORK/nested-$level.log"
    if ! elisa_run_timeout 300 env -u ELISA_STAGE1_RUNTIME_STD "$STAGE1" -emit exe "-$level" -o "$nested_output" "$ROOT/test/parity/submit_store_nested_group_control.elisa" >"$nested_log" 2>&1; then
        cat "$nested_log" >&2
        exit 1
    fi
    for run in 1 2 3; do
        if ! elisa_run_timeout 30 "$nested_output" >"$WORK/nested-run-$level-$run.log" 2>&1; then
            cat "$WORK/nested-run-$level-$run.log" >&2
            echo "nested submit group failed at $level, run $run" >&2
            exit 1
        fi
    done
    fake_output="$WORK/fake-group-O$level.o"
    fake_log="$WORK/fake-group-O$level.log"
    if elisa_run_timeout 300 env -u ELISA_STAGE1_RUNTIME_STD "$STAGE1" -emit obj "-$level" -o "$fake_output" "$ROOT/test/parity/submit_store_fake_group_control.elisa" >"$fake_log" 2>&1; then
        echo "submit store capture: accepted a store-capturing submit guarded only by user-defined fake TaskGroup APIs at $level" >&2
        exit 1
    fi
    [[ ! -e "$fake_output" ]] || { echo "submit store capture: wrote an object for fake TaskGroup APIs at $level" >&2; exit 1; }
    grep -qi 'declin\|unsupported\|unmodeled' "$fake_log" || {
        cat "$fake_log" >&2
        echo "submit store capture: fake TaskGroup refusal had no useful diagnostic at $level" >&2
        exit 1
    }
    fake_override_log="$WORK/fake-group-override-O$level.log"
    if elisa_run_timeout 300 env ELISA_STAGE1_RUNTIME_STD=1 "$STAGE1" -emit obj "-$level" -o "$WORK/fake-group-override-O$level.o" "$ROOT/test/parity/submit_store_fake_group_control.elisa" >"$fake_override_log" 2>&1; then
        echo "submit store capture: accepted user-defined fake TaskGroup APIs under the runtime provenance override at $level" >&2
        exit 1
    fi
    [[ ! -e "$WORK/fake-group-override-O$level.o" ]] || { echo "submit store capture: wrote an object for fake TaskGroup APIs under the runtime provenance override at $level" >&2; exit 1; }
done
echo "submit store capture OK: packed-store results, manual and nested group joins, and fake-TaskGroup refusal with and without the runtime provenance override at O0/O2"
