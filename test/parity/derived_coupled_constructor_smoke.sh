#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
source "$ROOT/test/parity/run_timeout.sh"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-derived-coupled.XXXXXX")"
cleanup() {
    for artifact in native native.log rejected.ll rejected.log; do
        if [[ -f "$WORK/$artifact" ]]; then rm -- "$WORK/$artifact"; fi
    done
    rmdir -- "$WORK"
}
trap cleanup EXIT
for optimization in 0 2; do
    elisa_run_timeout 30 env DEVELOPER_DIR="${DEVELOPER_DIR:-/Library/Developer/CommandLineTools}" \
        "$STAGE1" -emit exe "-O$optimization" -o "$WORK/native" \
        "$ROOT/test/repro/derived_coupled_constructor.pos.elisa" >"$WORK/native.log" 2>&1 || {
        cat "$WORK/native.log" >&2
        exit 1
    }
    elisa_run_timeout 10 "$WORK/native"
done
set +e
elisa_run_timeout 30 "$STAGE1" -emit llvm -o "$WORK/rejected.ll" \
    "$ROOT/test/repro/derived_coupled_constructor.neg.elisa" >"$WORK/rejected.log" 2>&1
status=$?
set -e
[[ "$status" -eq 1 && ! -e "$WORK/rejected.ll" ]] || { cat "$WORK/rejected.log" >&2; exit 1; }
rg -Fq 'does not satisfy derived state Within' "$WORK/rejected.log"
echo 'Coupled-field Boolean derived predicates pass at O0/O2 and reject contradictory literals'
