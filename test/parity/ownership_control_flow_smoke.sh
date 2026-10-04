#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
source "$ROOT/test/parity/run_timeout.sh"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-owner-cfg.XXXXXX")"
cleanup() {
    rm -f "$WORK/probe" "$WORK/build.log"
    rmdir "$WORK"
}
trap cleanup EXIT
if [[ $# -eq 0 ]]; then
    set -- ownership_control_flow_probe ownership_dead_paths_probe ownership_while_paths_probe ownership_for_paths_probe protocol_transition_eligibility_probe protocol_module_authority_probe
fi
for fixture in "$@"; do
elisa_run_timeout 180 env -u ELISACORE_BIN -u ELISA_CORE ELISA_STAGE1_BIN="$STAGE1" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit exe -O0 -permissive \
    -o "$WORK/probe" "$ROOT/test/repro/$fixture.elisa" >"$WORK/build.log" 2>&1 || {
    tail -100 "$WORK/build.log" >&2
    exit 1
}
elisa_run_timeout 15 "$WORK/probe" || {
    status=$?
    echo "$fixture failed with status $status" >&2
    exit "$status"
}
done
echo "Ownership CFG observations pass: $*"
