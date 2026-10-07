#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"  # host flags/paths: scripts/platform.sh
# Stage0 executable/state counterclaims; range/alias classification is not proved.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:?set ELISACORE_BIN to the current Stage0 compiler}"
source "$ROOT/test/parity/run_timeout.sh"
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-derived-stage0-loop-native.XXXXXX")"
cleanup() {
    for artifact in native native.a native.h native.elisa-abi.json native.unsafe.txt native.log link.log rejected.ll rejected.log; do
        if [[ -f "$WORK/$artifact" ]]; then rm -- "$WORK/$artifact"; fi
    done
    rmdir -- "$WORK"
}
trap cleanup EXIT
for optimization in 0 2; do
    elisa_run_timeout 30 env DEVELOPER_DIR="${DEVELOPER_DIR:-/Library/Developer/CommandLineTools}" \
        "$STAGE0" -emit c-archive "-O$optimization" -o "$WORK/native.a" \
        "$ROOT/test/repro/derived_source_loops.pos.elisa" >"$WORK/native.log" 2>&1 || {
        cat "$WORK/native.log" >&2
        exit 1
    }
    elisa_run_timeout 30 env DEVELOPER_DIR="${DEVELOPER_DIR:-/Library/Developer/CommandLineTools}" \
        "${ELISA_CLANG:-clang}" $ELISA_LD_DEAD_STRIP $ELISA_LINK_EXE_FLAGS -o "$WORK/native" "$WORK/native.a" >"$WORK/link.log" 2>&1 || {
        cat "$WORK/link.log" >&2
        exit 1
    }
    elisa_run_timeout 10 "$WORK/native"
done
for fixture in derived_source_loop_zero.neg derived_source_loop_later_iteration.neg derived_source_loop_break.neg; do
    set +e
    elisa_run_timeout 30 "$STAGE0" -emit llvm -o "$WORK/rejected.ll" \
        "$ROOT/test/repro/$fixture.elisa" >"$WORK/rejected.log" 2>&1
    status=$?
    set -e
    [[ "$status" -eq 1 && ! -e "$WORK/rejected.ll" ]] || {
        cat "$WORK/rejected.log" >&2
        echo "Stage0 loop counterclaim must reject without an artifact ($fixture); got $status" >&2
        exit 1
    }
    if [[ "$fixture" == derived_source_loop_later_iteration.neg ]]; then
        rg -q 'later loop iteration expects Player\[Alive\]' "$WORK/rejected.log"
    else
        rg -q 'return type expects Player\[Dead\]' "$WORK/rejected.log"
    fi
done
echo 'Stage0 derived loop fixed points execute at O0/O2; zero-entry/later-iteration/break counterclaims reject'
