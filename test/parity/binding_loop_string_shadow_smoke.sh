#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:?set ELISACORE_BIN to the Stage0 compiler}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
source "$ROOT/test/parity/run_timeout.sh"
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-binding-shadow.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
for compiler in "$STAGE0" "$STAGE1"; do
    elisa_run_timeout 30 "$compiler" -emit llvm -o "$WORK/positive.ll" \
        "$ROOT/test/repro/binding_loop_string_shadow.pos.elisa" >"$WORK/positive.log" 2>&1 || { cat "$WORK/positive.log" >&2; exit 1; }
    ! rg -q '!elisa\.declined' "$WORK/positive.ll"
    set +e
    elisa_run_timeout 30 "$compiler" -emit llvm -o "$WORK/negative.ll" \
        "$ROOT/test/repro/binding_loop_string_shadow.neg.elisa" >"$WORK/negative.log" 2>&1
    status=$?
    set -e
    [[ "$status" -eq 1 ]] || { cat "$WORK/negative.log" >&2; exit 1; }
    rg -q 'expects sview' "$WORK/negative.log" || { cat "$WORK/negative.log" >&2; exit 1; }
done
echo 'Loop binder reference classification OK: inner sview accepted, restored outer pointer rejected'
