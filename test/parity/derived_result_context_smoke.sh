#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
source "$ROOT/test/parity/run_timeout.sh"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-derived-result.XXXXXX")"
cleanup() {
    for artifact in native native.log rejected.ll rejected.log; do
        if [[ -f "$WORK/$artifact" ]]; then rm -- "$WORK/$artifact"; fi
    done
    rmdir -- "$WORK"
}
trap cleanup EXIT
for positive in derived_record_update_codegen_probe derived_result_snapshot_codegen_probe; do
for optimization in 0 2; do
    elisa_run_timeout 30 env DEVELOPER_DIR="${DEVELOPER_DIR:-/Library/Developer/CommandLineTools}" \
        "$STAGE1" -emit exe "-O$optimization" -o "$WORK/native" \
        "$ROOT/test/repro/$positive.elisa" >"$WORK/native.log" 2>&1 || {
        cat "$WORK/native.log" >&2
        exit 1
    }
    elisa_run_timeout 10 "$WORK/native"
done
done
for fixture in derived_record_update_forged derived_update_local derived_update_alias_return derived_constructor_return_context derived_update_conditional_return derived_update_match_return derived_update_coupled_return; do
    set +e
    elisa_run_timeout 30 "$STAGE1" -emit llvm -o "$WORK/rejected.ll" \
        "$ROOT/test/repro/$fixture.neg.elisa" >"$WORK/rejected.log" 2>&1
    status=$?
    set -e
    [[ "$status" -eq 1 && ! -e "$WORK/rejected.ll" ]] || { cat "$WORK/rejected.log" >&2; exit 1; }
    rg -q 'does not satisfy derived state (Alive|Within)' "$WORK/rejected.log" || { cat "$WORK/rejected.log" >&2; exit 1; }
done
echo 'Derived result contexts reject proven contradictions; valid state-changing updates run at O0/O2'
