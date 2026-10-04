#!/usr/bin/env bash
# Deliberately red while a possible single state is confused with known evidence.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:?set ELISACORE_BIN to the current Stage0 compiler}"
source "$ROOT/test/parity/run_timeout.sh"
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-derived-single-state.XXXXXX")"
cleanup() {
    for artifact in rejected.ll rejected.log; do
        if [[ -f "$WORK/$artifact" ]]; then rm -- "$WORK/$artifact"; fi
    done
    rmdir -- "$WORK"
}
trap cleanup EXIT
set +e
elisa_run_timeout 30 "$STAGE0" -emit llvm -o "$WORK/rejected.ll" \
    "$ROOT/test/repro/derived_source_single_state_unknown.neg.elisa" >"$WORK/rejected.log" 2>&1
status=$?
set -e
[[ "$status" -eq 1 && ! -e "$WORK/rejected.ll" ]] || {
    cat "$WORK/rejected.log" >&2
    echo "Stage0 single-state source knowledge missing; expected semantic rejection without artifact, got $status" >&2
    exit 1
}
rg -q 'predicate evidence|current derived state' "$WORK/rejected.log"
echo 'Stage0 unknown single-state predicate evidence rejects'
