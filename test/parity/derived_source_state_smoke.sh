#!/usr/bin/env bash
# Deliberately red until Stage1 checks the current source state on preservation.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:?set ELISACORE_BIN to the current Stage0 compiler}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
source "$ROOT/test/parity/run_timeout.sh"
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-derived-source.XXXXXX")"
cleanup() {
    for artifact in native native.log positive.ll positive.log rejected.ll rejected.log; do
        if [[ -f "$WORK/$artifact" ]]; then rm -- "$WORK/$artifact"; fi
    done
    rmdir -- "$WORK"
}
trap cleanup EXIT
for optimization in 0 2; do
    elisa_run_timeout 30 env DEVELOPER_DIR="${DEVELOPER_DIR:-/Library/Developer/CommandLineTools}" \
        "$STAGE1" -emit exe "-O$optimization" -o "$WORK/native" \
        "$ROOT/test/repro/derived_update_changed_before_copy.pos.elisa" >"$WORK/native.log" 2>&1 || {
        cat "$WORK/native.log" >&2
        exit 1
    }
    elisa_run_timeout 10 "$WORK/native"
done
for compiler in "$STAGE0" "$STAGE1"; do
    elisa_run_timeout 30 "$compiler" -emit llvm -o "$WORK/positive.ll" \
        "$ROOT/test/repro/derived_update_changed_before_copy.pos.elisa" >"$WORK/positive.log" 2>&1
    set +e
    elisa_run_timeout 30 "$compiler" -emit llvm -o "$WORK/rejected.ll" \
        "$ROOT/test/repro/derived_update_unchanged_wrong_state.neg.elisa" >"$WORK/rejected.log" 2>&1
    status=$?
    set -e
    [[ "$status" -eq 1 && ! -e "$WORK/rejected.ll" ]] || {
        cat "$WORK/rejected.log" >&2
        echo "Unchanged-field relabelling must reject semantically without an artifact; got $status" >&2
        exit 1
    }
done
echo 'Derived source-state preservation checks pass'
