#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"  # host flags/paths: scripts/platform.sh
# Stage0 enforcement gate; this does not imply Stage1 parity.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:?set ELISACORE_BIN to the dedicated Stage0 compiler}"
source "$ROOT/test/parity/run_timeout.sh"
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-derived-update.XXXXXX")"
cleanup() {
    for artifact in positive.a positive.ll positive positive.h positive.elisa-abi.json positive.unsafe.txt rejected.ll reject.log; do
        if [[ -f "$WORK/$artifact" ]]; then
            rm -- "$WORK/$artifact"
        fi
    done
    rmdir -- "$WORK"
}
trap cleanup EXIT
elisa_run_timeout 30 "$STAGE0" -emit llvm -o "$WORK/positive.ll" "$ROOT/test/repro/derived_record_update_codegen_probe.elisa" || { status=$?; echo "positive LLVM build failed: $status" >&2; exit "$status"; }
rg -q '^%Player__Alive = type \{ i64, i64 \}$' "$WORK/positive.ll"
rg -q '^%Player__Dead = type \{ i64, i64 \}$' "$WORK/positive.ll"
for optimization in 0 2; do
    elisa_run_timeout 30 "$STAGE0" -emit c-archive "-O$optimization" -o "$WORK/positive.a" "$ROOT/test/repro/derived_record_update_codegen_probe.elisa" || { status=$?; echo "O$optimization build failed: $status" >&2; exit "$status"; }
    elisa_run_timeout 30 "${ELISA_CLANG:-clang}" $ELISA_LD_DEAD_STRIP $ELISA_LINK_EXE_FLAGS -o "$WORK/positive" "$WORK/positive.a"
    elisa_run_timeout 10 "$WORK/positive"
done
for fixture in derived_record_update_forged derived_record_update_single_unknown; do
    set +e
    elisa_run_timeout 30 "$STAGE0" -emit llvm -o "$WORK/rejected.ll" "$ROOT/test/repro/$fixture.neg.elisa" >"$WORK/reject.log" 2>&1
    status=$?
    set -e
    [[ "$status" -eq 1 ]] || { cat "$WORK/reject.log" >&2; echo "$fixture: expected rejection, got $status" >&2; exit 1; }
    [[ ! -e "$WORK/rejected.ll" ]] || { echo "$fixture: emitted an artifact despite rejection" >&2; exit 1; }
    if [[ "$fixture" == derived_record_update_forged ]]; then
        rg -Fq 'return type expects Player[Alive], got Player[Dead]' "$WORK/reject.log"
    else
        rg -Fq 'cannot establish its only derived state from an unknown predicate' "$WORK/reject.log"
    fi
done
echo 'Stage0 derived record updates pass O0/O2; invalid preserved-state and unknown singleton claims reject'
