#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:?set ELISACORE_BIN to the protocol-graph Stage0 compiler}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
source "$ROOT/test/parity/run_timeout.sh"
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-protocol-validation.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
fixtures=(unknown_state duplicate_edge mixed_derived without_family)
messages=('names an undeclared state' 'duplicate protocol transition' 'cannot combine a protocol transition graph with derive state:' 'transitions: requires a named struct state parameter')
for compiler in "$STAGE0" "$STAGE1"; do
    for index in "${!fixtures[@]}"; do
        set +e
        elisa_run_timeout 30 "$compiler" -emit llvm -o "$WORK/rejected.ll" \
            "$ROOT/test/repro/protocol_graph_${fixtures[index]}.neg.elisa" >"$WORK/reject.log" 2>&1
        status=$?
        set -e
        [[ "$status" -eq 1 ]] || { cat "$WORK/reject.log" >&2; echo "expected semantic rejection, got $status" >&2; exit 1; }
        rg -Fq "${messages[index]}" "$WORK/reject.log" || { cat "$WORK/reject.log" >&2; exit 1; }
    done
done
# Stage0 already rejects malformed state headers; verify Stage1's newly retained
# family metadata also receives the specific declaration-level diagnostics.
fixtures=(duplicate_state empty_family)
messages=('duplicate protocol state Closed' 'must declare at least one state')
for index in "${!fixtures[@]}"; do
    set +e
    elisa_run_timeout 30 "$STAGE1" -emit llvm -o "$WORK/rejected.ll" \
        "$ROOT/test/repro/protocol_graph_${fixtures[index]}.neg.elisa" >"$WORK/reject.log" 2>&1
    status=$?
    set -e
    [[ "$status" -eq 1 ]] || { cat "$WORK/reject.log" >&2; exit 1; }
    rg -Fq "${messages[index]}" "$WORK/reject.log" || { cat "$WORK/reject.log" >&2; exit 1; }
done
echo 'Protocol graph validation OK: paired edge/mode/family rejection; Stage1 duplicate/empty state families'
