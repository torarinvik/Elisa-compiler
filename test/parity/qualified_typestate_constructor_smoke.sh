#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
source "$ROOT/test/parity/run_timeout.sh"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-qualified-state.XXXXXX")"
cleanup() {
    for artifact in positive.ll rejected.ll positive.log rejected.log native native.log; do
        if [[ -f "$WORK/$artifact" ]]; then rm -- "$WORK/$artifact"; fi
    done
    rmdir -- "$WORK"
}
trap cleanup EXIT
elisa_run_timeout 30 "$STAGE1" -emit llvm -o "$WORK/positive.ll" \
    "$ROOT/test/repro/derived_constructor_qualified.repro.elisa" >"$WORK/positive.log" 2>&1 || {
    cat "$WORK/positive.log" >&2
    exit 1
}
[[ -s "$WORK/positive.ll" ]]
! rg -q '!elisa\.declined' "$WORK/positive.ll"
for optimization in 0 2; do
    elisa_run_timeout 30 env DEVELOPER_DIR="${DEVELOPER_DIR:-/Library/Developer/CommandLineTools}" \
        "$STAGE1" -emit exe "-O$optimization" -o "$WORK/native" \
        "$ROOT/test/repro/derived_constructor_qualified.repro.elisa" >"$WORK/native.log" 2>&1 || {
        cat "$WORK/native.log" >&2
        exit 1
    }
    elisa_run_timeout 10 "$WORK/native"
done
fixtures=(derived_constructor_qualified qualified_application_value_index qualified_application_missing_path qualified_application_shadowed_path qualified_application_unknown_state)
messages=('does not satisfy derived state Valid' 'undefined identifier "missing_index"' 'undefined identifier "missing_index"' 'undefined identifier "missing_index"' 'has no named state Missing')
for index in "${!fixtures[@]}"; do
    set +e
    elisa_run_timeout 30 "$STAGE1" -emit llvm -o "$WORK/rejected.ll" \
        "$ROOT/test/repro/${fixtures[index]}.neg.elisa" >"$WORK/rejected.log" 2>&1
    status=$?
    set -e
    [[ "$status" -eq 1 && ! -e "$WORK/rejected.ll" ]] || { cat "$WORK/rejected.log" >&2; exit 1; }
    rg -Fq "${messages[index]}" "$WORK/rejected.log" || { cat "$WORK/rejected.log" >&2; exit 1; }
done
echo 'Qualified typestate construction and value-index resolution controls pass'
