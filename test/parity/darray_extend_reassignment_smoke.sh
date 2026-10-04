#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
source "$ROOT/test/parity/run_timeout.sh"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-extend-reassign.XXXXXX")"
cleanup() {
    rm -f "$WORK/probe" "$WORK/build.log" "$WORK/reject.ll" "$WORK/reject.log"
    rmdir "$WORK"
}
trap cleanup EXIT
for optimization in O0 O2; do
  for fixture in darray_extend_reassignment_probe darray_extend_local_probe darray_nested_constructor_probe; do
    elisa_run_timeout 60 env -u ELISACORE_BIN -u ELISA_CORE ELISA_STAGE1_BIN="$STAGE1" \
        bash "$ROOT/scripts/elisac_stage1.sh" -emit exe "-$optimization" -permissive \
        -o "$WORK/probe" "$ROOT/test/repro/$fixture.elisa" >"$WORK/build.log" 2>&1 || {
        tail -80 "$WORK/build.log" >&2
        exit 1
    }
    elisa_run_timeout 15 "$WORK/probe"
  done
done
set +e
elisa_run_timeout 30 "$STAGE1" -emit llvm -permissive -o "$WORK/reject.ll" \
    "$ROOT/test/repro/darray_extend_different_target.neg.elisa" >"$WORK/reject.log" 2>&1
status=$?
set -e
[[ "$status" == 2 ]] && [[ ! -e "$WORK/reject.ll" ]] && rg -q 'backend could not produce a linkable unit; declined 1: main@' "$WORK/reject.log" || {
    tail -60 "$WORK/reject.log" >&2
    exit 1
}
echo 'Darray extend reassignment passes O0/O2: lmut field, empty input, self-extension/growth; different target declines'
