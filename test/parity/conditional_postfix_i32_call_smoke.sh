#!/usr/bin/env bash
# Stage0/stage1 runtime parity for a value-if call whose argument narrows from i64 to i32.
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$REPO_ROOT/../../Go projects/structpy-tree/compiler/bin/elisac}"
STAGE1="$REPO_ROOT/scripts/elisac_stage1.sh"
FIXTURE="$REPO_ROOT/test/repro/conditional_postfix_i32_call.elisa"
RUNTIME="$REPO_ROOT/build/runtime/elisacore_runtime.o"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

cat >"$TMP_DIR/driver.c" <<'EOF'
#include <stdint.h>

extern int64_t conditional_postfix_i32_call_api(int32_t value);

int main(void)
{
    return conditional_postfix_i32_call_api(0) == 62 &&
                   conditional_postfix_i32_call_api(2) == 64 &&
                   conditional_postfix_i32_call_api(1) == 1
               ? 0
               : 1;
}
EOF

"$STAGE0" -emit obj -O2 -o "$TMP_DIR/stage0.o" "$FIXTURE" >"$TMP_DIR/stage0.log" 2>&1
"$STAGE1" -emit obj -O2 -o "$TMP_DIR/stage1.o" "$FIXTURE" >"$TMP_DIR/stage1.log" 2>&1

cc -std=c17 "$TMP_DIR/driver.c" "$TMP_DIR/stage0.o" "$RUNTIME" -o "$TMP_DIR/stage0"
cc -std=c17 "$TMP_DIR/driver.c" "$TMP_DIR/stage1.o" "$RUNTIME" -o "$TMP_DIR/stage1"
"$TMP_DIR/stage0"
"$TMP_DIR/stage1"
echo "conditional-postfix-i32-call smoke OK: stage0 and stage1 runtime results match at -O2"
