#!/usr/bin/env bash
# Exercise the shipped Stage1 driver's semantic diagnostics for loops.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"

FIX="$ROOT/test/parity/loop_smoke.elisa"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

status=0
"$STAGE1" -emit check "$FIX" >"$WORK/output" 2>&1 || status=$?
non_iterable="$(grep -c 'for loop iterable must be an iterable type' "$WORK/output" || true)"
non_bool="$(grep -c 'while condition must be bool' "$WORK/output" || true)"
diagnostics="$(grep -c '^.*loop_smoke\.elisa:[0-9]' "$WORK/output" || true)"

if [[ "$status" != 1 || "$non_iterable" != 4 || "$non_bool" != 2 || "$diagnostics" != 6 ]]; then
    cat "$WORK/output" >&2
    echo "loop smoke FAILED with exit $status and $diagnostics diagnostics ($non_iterable non-iterable, $non_bool non-bool)" >&2
    exit 1
fi

echo "loop smoke OK: NonIterableLoop=$non_iterable NonBoolCondition=$non_bool" >&2
