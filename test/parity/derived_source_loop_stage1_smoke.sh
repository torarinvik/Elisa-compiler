#!/usr/bin/env bash
# Stage1 loop-frontier behavior; Stage0 parity is separately audited, not implied.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
source "$ROOT/test/parity/run_timeout.sh"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-derived-loop.XXXXXX")"
cleanup() {
    for artifact in native native.log rejected.ll rejected.log; do
        if [[ -f "$WORK/$artifact" ]]; then rm -- "$WORK/$artifact"; fi
    done
    rmdir -- "$WORK"
}
trap cleanup EXIT
for optimization in 0 2; do
    elisa_run_timeout 30 env DEVELOPER_DIR="${DEVELOPER_DIR:-/Library/Developer/CommandLineTools}" \
        "$STAGE1" -emit exe "-O$optimization" -o "$WORK/native" \
        "$ROOT/test/repro/derived_source_loops.pos.elisa" >"$WORK/native.log" 2>&1 || {
        cat "$WORK/native.log" >&2
        exit 1
    }
    elisa_run_timeout 10 "$WORK/native"
done
for fixture in derived_source_loop_zero.neg derived_source_loop_later_iteration.neg derived_source_loop_break.neg derived_source_loop_scalar_alias.neg; do
    set +e
    elisa_run_timeout 30 "$STAGE1" -emit llvm -o "$WORK/rejected.ll" \
        "$ROOT/test/repro/$fixture.elisa" >"$WORK/rejected.log" 2>&1
    status=$?
    set -e
    [[ "$status" -eq 1 && ! -e "$WORK/rejected.ll" ]] || {
        cat "$WORK/rejected.log" >&2
        echo "Loop state counterclaim must reject without an artifact ($fixture); got $status" >&2
        exit 1
    }
    rg -q 'unknown predicate evidence' "$WORK/rejected.log" || {
        cat "$WORK/rejected.log" >&2
        echo "Expected current-source evidence diagnostic ($fixture)" >&2
        exit 1
    }
done
echo 'Stage1 derived loop fixed points preserve states at O0/O2; zero-entry/later-iteration/break/scalar-alias counterclaims reject'
