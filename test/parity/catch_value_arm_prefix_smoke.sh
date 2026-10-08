#!/usr/bin/env bash
# Stage1 value catches share statement-arm prefix and exit lowering.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-catch-prefix.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
for fixture in catch_value_arm_prefix catch_value_arm_prefix_effects; do
    bash "$ROOT/scripts/elisac_stage1.sh" -O0 -emit exe -o "$WORK/$fixture" "$ROOT/test/repro/$fixture.elisa"
    "$WORK/$fixture"
done
if bash "$ROOT/scripts/elisac_stage1.sh" -O0 -emit obj -o "$WORK/rejected.o" "$ROOT/test/repro/catch_value_arm_prefix_leak_rejected.elisa" >"$WORK/rejected.log" 2>&1; then
    echo "catch prefix smoke FAIL: arm-local binding escaped" >&2
    exit 1
fi
rg -q 'undefined identifier "temporary"' "$WORK/rejected.log"
echo "catch value-arm prefix smoke OK"
