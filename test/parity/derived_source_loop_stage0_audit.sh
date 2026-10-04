#!/usr/bin/env bash
# Focused artifact-free rejection audit for the later-iteration source head.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:?set ELISACORE_BIN to the current Stage0 compiler}"
source "$ROOT/test/parity/run_timeout.sh"
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-derived-stage0-loop.XXXXXX")"
cleanup() {
    for artifact in rejected.ll rejected.log; do
        if [[ -f "$WORK/$artifact" ]]; then rm -- "$WORK/$artifact"; fi
    done
    rmdir -- "$WORK"
}
trap cleanup EXIT
set +e
elisa_run_timeout 30 "$STAGE0" -emit llvm -o "$WORK/rejected.ll" \
    "$ROOT/test/repro/derived_source_loop_later_iteration.neg.elisa" >"$WORK/rejected.log" 2>&1
status=$?
set -e
[[ "$status" -eq 1 && ! -e "$WORK/rejected.ll" ]] || {
    cat "$WORK/rejected.log" >&2
    echo "Stage0 later-iteration state check missing; expected semantic rejection without an artifact, got $status" >&2
    exit 1
}
rg -q 'later loop iteration expects Player\[Alive\]' "$WORK/rejected.log"
echo 'Stage0 later-iteration derived-state counterclaim rejects'
