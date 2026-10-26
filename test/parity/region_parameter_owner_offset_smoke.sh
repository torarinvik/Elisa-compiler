#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
python3 "$ROOT/test/proofs/check_region_parameter_owner_offset.py"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$ROOT/test/parity/run_timeout.sh"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-region-owner-offset.XXXXXX")"
cleanup() {
    for artifact in native native.log; do
        if [[ -f "$WORK/$artifact" ]]; then rm -- "$WORK/$artifact"; fi
    done
    rmdir -- "$WORK"
}
trap cleanup EXIT
for optimization in 0 2; do
    for fixture in region_parameter_owner_offset region_fact_owner_offset region_fact_cross_module_owner region_generic_owner_offset; do
        elisa_run_timeout 30 env DEVELOPER_DIR="${DEVELOPER_DIR:-/Library/Developer/CommandLineTools}" \
            "$STAGE1" -emit exe "-O$optimization" -o "$WORK/native" \
            "$ROOT/test/repro/$fixture.elisa" >"$WORK/native.log" 2>&1 || {
            cat "$WORK/native.log" >&2
            exit 1
        }
        elisa_run_timeout 10 "$WORK/native"
    done
done
echo 'Region-parameter and inferred arena ABI facts stay paired with their declaring functions'
