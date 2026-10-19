#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
WORK="$ROOT/build/prereserve_push_byte_cap"
mkdir -p "$WORK"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"

# Keep the speculative pass enabled regardless of an inherited local ablation.
ELISA_DISABLE_MEMORY_SPEED=0 ELISA_DISABLE_MEMORY_RESERVE=0 \
    "$STAGE1" -emit llvm -O0 -o "$WORK/prereserve_push_byte_cap.ll" \
    "$ROOT/test/fixtures/backend/prereserve_push_byte_cap.elisa"
IR="$WORK/prereserve_push_byte_cap.ll"

# i64 has an eight-byte ABI stride: the single-push and two-push caps are 8,388,608
# and 4,194,304 trips respectively. The in-cap literal fill gets the fast cursor,
# while over-cap and dynamic fills retain the checked push-capacity path.
grep -q 'i64 8388608' "$IR"
grep -q 'i64 4194304' "$IR"
grep -q 'fill.items.base' "$IR"
grep -q 'push.cap.ok' "$IR"
echo "backend_prereserve_push_byte_cap_smoke OK"
