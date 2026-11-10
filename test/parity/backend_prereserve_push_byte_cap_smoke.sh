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
function_ir() {
    sed -n "/^define .*@$1(/,/^}/p" "$IR"
}

one_literal=$(function_ir fill_one_i64_under_cap)
two_literal=$(function_ir fill_two_i64_over_cap)
one_dynamic=$(function_ir fill_one_i64_dynamic)
two_dynamic=$(function_ir fill_two_i64_dynamic)

grep -q 'fill.items.base' <<< "$one_literal"
grep -q 'i64 4194304, i64 2' <<< "$two_literal"
grep -q 'icmp ult i64 .*8388608$' <<< "$one_dynamic"
grep -q 'icmp ult i64 .*4194304$' <<< "$two_dynamic"
for fallback in "$two_literal" "$one_dynamic" "$two_dynamic"; do
    grep -q 'push.cap.ok' <<< "$fallback"
    if grep -q 'darray.fill.cursor' <<< "$fallback"; then
        echo "byte-cap smoke: an over-cap or dynamic loop uses the unchecked fill cursor" >&2
        exit 1
    fi
done
echo "backend_prereserve_push_byte_cap_smoke OK"
