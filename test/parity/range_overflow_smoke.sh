#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$ROOT/test/parity/run_timeout.sh"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-range-overflow.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

if ! elisa_run_timeout 300 env -u ELISA_STAGE1_RUNTIME_STD "$STAGE1" -emit exe -O0 -o "$WORK/range-overflow" "$ROOT/test/parity/range_overflow_control.elisa" >"$WORK/build.log" 2>&1; then
    cat "$WORK/build.log" >&2
    exit 1
fi
if ! elisa_run_timeout 30 "$WORK/range-overflow" >"$WORK/run.log" 2>&1; then
    cat "$WORK/run.log" >&2
    echo "range overflow smoke failed or did not terminate" >&2
    exit 1
fi
echo "range overflow smoke OK: signed minimum strides and finite-width step overflow terminate correctly"
