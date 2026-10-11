#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$ROOT/test/parity/run_timeout.sh"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-incremental-anchor.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
for level in O0 O2; do
    if ! elisa_run_timeout 300 "$STAGE1" -emit exe "-$level" -o "$WORK/control-$level" "$ROOT/test/parity/incremental_anchor_control.elisa" >"$WORK/build-$level.log" 2>&1; then
        cat "$WORK/build-$level.log" >&2
        exit 1
    fi
    if ! elisa_run_timeout 30 "$WORK/control-$level" >"$WORK/run-$level.log" 2>&1; then
        cat "$WORK/run-$level.log" >&2
        echo "incremental anchor control FAILED at $level" >&2
        exit 1
    fi
done
echo "incremental anchor control OK at O0/O2: suffix spans, whitespace, body-relative indices, and empty ranges"
