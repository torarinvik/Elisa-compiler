#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$ROOT/test/parity/run_timeout.sh"
python3 "$ROOT/test/proofs/check_backend_error_union_subset_capture.py"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-error-union-subset.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
FIXTURE="$ROOT/test/fixtures/effects/error_union_subset_capture_cleanup.elisa"

for optimization in 0 2; do
    executable="$WORK/subset-O$optimization"
    if ! elisa_run_timeout 29 "$ROOT/scripts/elisac_stage1.sh" \
        -emit exe "-O$optimization" -o "$executable" "$FIXTURE" \
        >"$WORK/build-O$optimization.log" 2>&1; then
        echo "subset capture compile failed at O$optimization" >&2
        sed -n '1,100p' "$WORK/build-O$optimization.log" >&2
        exit 1
    fi
    actual=0
    if elisa_run_timeout 10 "$executable"; then
        actual=0
    else
        actual=$?
    fi
    [[ "$actual" == 35 ]] || {
        echo "subset capture at O$optimization returned $actual, expected 35" >&2
        exit 1
    }
done

echo "error union subset capture smoke OK (O0/O2, remapped tag/payload, cleanup, argument evaluated once)"
