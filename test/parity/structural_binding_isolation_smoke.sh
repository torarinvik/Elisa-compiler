#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
source "$ROOT/test/parity/run_timeout.sh"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-structural-isolation.XXXXXX")"
cleanup() {
    rm -f "$WORK/probe" "$WORK/build.log"
    rmdir "$WORK"
}
trap cleanup EXIT
for optimization in O0 O2; do
  for fixture in structural_binding_function_isolation_probe darray_rows_binding_collision_open; do
    elisa_run_timeout 180 env -u ELISACORE_BIN -u ELISA_CORE ELISA_STAGE1_BIN="$STAGE1" \
      bash "$ROOT/scripts/elisac_stage1.sh" -emit exe "-$optimization" -permissive \
      -o "$WORK/probe" "$ROOT/test/repro/$fixture.elisa" >"$WORK/build.log" 2>&1 || {
        echo "Structural binding isolation failed: $fixture at $optimization" >&2
        tail -80 "$WORK/build.log" >&2
        exit 1
    }
    elisa_run_timeout 15 "$WORK/probe"
  done
done
echo 'Structural binding isolation passes O0/O2 across functions and runtime imports'
