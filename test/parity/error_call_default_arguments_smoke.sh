#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-error-defaults.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
for level in 0 2; do
    bash "$ROOT/scripts/elisac_stage1.sh" -O"$level" -emit exe -o "$WORK/control-$level" "$ROOT/test/repro/error_call_default_arguments.elisa"
    "$WORK/control-$level"
done
if bash "$ROOT/scripts/elisac_stage1.sh" -O0 -emit obj -o "$WORK/rejected.o" "$ROOT/test/repro/error_call_missing_argument_rejected.elisa" >"$WORK/rejected.log" 2>&1; then
    echo "error defaults smoke FAIL: missing required argument accepted" >&2
    exit 1
fi
rg -q 'error_call_missing_argument_rejected.elisa:' "$WORK/rejected.log"
echo "error call default arguments smoke OK"
