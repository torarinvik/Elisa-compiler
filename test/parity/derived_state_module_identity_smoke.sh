#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
python3 "$ROOT/test/proofs/check_backend_derived_state_module_identity.py"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
source "$ROOT/test/parity/run_timeout.sh"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-derived-state-owner.XXXXXX")"
cleanup() {
    for artifact in native native.log shadow.log; do
        if [[ -f "$WORK/$artifact" ]]; then rm -- "$WORK/$artifact"; fi
    done
    rmdir -- "$WORK"
}
trap cleanup EXIT
for optimization in 0 2; do
    elisa_run_timeout 30 env DEVELOPER_DIR="${DEVELOPER_DIR:-/Library/Developer/CommandLineTools}" \
        "$STAGE1" -emit exe "-O$optimization" -o "$WORK/native" \
        "$ROOT/test/repro/derived_state_module_identity.elisa" >"$WORK/native.log" 2>&1 || {
        cat "$WORK/native.log" >&2
        exit 1
    }
    elisa_run_timeout 10 "$WORK/native"
done
for optimization in 0 2; do
    shadow_status=0
    elisa_run_timeout 30 env DEVELOPER_DIR="${DEVELOPER_DIR:-/Library/Developer/CommandLineTools}" \
        "$STAGE1" -emit obj "-O$optimization" -o /dev/null \
        "$ROOT/test/repro/derived_state_wrong_owner.neg.elisa" >"$WORK/shadow.log" 2>&1 || shadow_status=$?
    if [[ "$shadow_status" -eq 0 || "$shadow_status" -eq 124 || "$shadow_status" -ge 128 || ! -s "$WORK/shadow.log" ]]; then
        echo "Derived-state owner regression: root Gauge borrowed Left::Gauge[Ready] at O$optimization" >&2
        sed -n '1,80p' "$WORK/shadow.log" >&2
        exit 1
    fi
    grep -Eiq 'declin|unsupported|unmodeled|invalid|error|state' "$WORK/shadow.log" || {
        echo "Derived-state owner regression: rejection had no codegen diagnostic at O$optimization" >&2
        sed -n '1,80p' "$WORK/shadow.log" >&2
        exit 1
    }
done
echo 'Derived-state tests select predicates from the owning module'
