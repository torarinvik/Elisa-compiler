#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-fieldless-rethrow.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
for level in 0 2; do
    bash "$ROOT/scripts/elisac_stage1.sh" -O"$level" -emit exe -o "$WORK/control-$level" "$ROOT/test/repro/composite_fieldless_rethrow.elisa"
    "$WORK/control-$level"
done
if bash "$ROOT/scripts/elisac_stage1.sh" -O0 -emit obj -o "$WORK/rejected.o" "$ROOT/test/repro/composite_fieldless_rethrow_rejected.elisa" >"$WORK/rejected.log" 2>&1; then
    echo "fieldless rethrow smoke FAIL: incompatible family accepted" >&2
    exit 1
fi
rg -q 'cannot propagate|cannot raise|not.*error|incompatible' "$WORK/rejected.log"
echo "composite fieldless rethrow smoke OK"
