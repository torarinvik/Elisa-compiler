#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
source "$ROOT/test/parity/run_timeout.sh"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-binding-state.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
elisa_run_timeout 180 env -u ELISACORE_BIN -u ELISA_CORE ELISA_STAGE1_BIN="$STAGE1" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit exe -O0 -permissive \
    -o "$WORK/bindings" "$ROOT/test/repro/typestate_binding_identity_probe.elisa" >"$WORK/build.log" 2>&1 || {
    cat "$WORK/build.log" >&2
    exit 1
}
if elisa_run_timeout 15 "$WORK/bindings"; then
    :
else
    status=$?
    echo "binding identity probe failed control $status" >&2
    exit "$status"
fi
echo 'Stage1 binding type identity OK: shadowing, function boundaries, module ownership, state/ref structural shapes'
