#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
source "$ROOT/test/parity/run_timeout.sh"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-derived-family.XXXXXX")"
cleanup() {
    for artifact in positive.ll rejected.ll positive.log rejected.log; do
        if [[ -f "$WORK/$artifact" ]]; then rm -- "$WORK/$artifact"; fi
    done
    rmdir -- "$WORK"
}
trap cleanup EXIT
elisa_run_timeout 30 "$STAGE1" -emit llvm -o "$WORK/positive.ll" \
    "$ROOT/test/repro/derived_constructor_family.pos.elisa" >"$WORK/positive.log" 2>&1 || {
    cat "$WORK/positive.log" >&2
    exit 1
}
[[ -s "$WORK/positive.ll" ]]
set +e
elisa_run_timeout 30 "$STAGE1" -emit llvm -o "$WORK/rejected.ll" \
    "$ROOT/test/repro/derived_constructor_family.neg.elisa" >"$WORK/rejected.log" 2>&1
status=$?
set -e
[[ "$status" -eq 1 && ! -e "$WORK/rejected.ll" ]] || { cat "$WORK/rejected.log" >&2; exit 1; }
rg -Fq 'does not satisfy derived state Valid' "$WORK/rejected.log"
echo 'Derived constructor canonical family checks pass'
