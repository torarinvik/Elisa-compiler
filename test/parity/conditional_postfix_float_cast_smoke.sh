#!/usr/bin/env bash
# Stage0/stage1 parity for a postfix numeric cast whose receiver is a value-if.
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$HOME/.elisac/elisac}"
STAGE1="$REPO_ROOT/scripts/elisac_stage1.sh"
FIXTURE="$REPO_ROOT/test/repro/conditional_postfix_float_cast.elisa"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

"$STAGE0" -emit obj -O0 -o "$TMP_DIR/stage0.o" "$FIXTURE" >"$TMP_DIR/stage0.log" 2>&1
"$STAGE1" -emit obj -O0 -o "$TMP_DIR/stage1.o" "$FIXTURE" >"$TMP_DIR/stage1.log" 2>&1

nm -gU "$TMP_DIR/stage0.o" | grep -q '_conditional_rate$'
nm -gU "$TMP_DIR/stage1.o" | grep -q '_conditional_rate$'
if nm -u "$TMP_DIR/stage1.o" | grep -q '_conditional_rate$'; then
    echo "conditional-postfix-float-cast smoke FAILED: stage1 left the local callee unresolved" >&2
    exit 1
fi
echo "conditional-postfix-float-cast smoke OK: stage0 and stage1 emit the local callee"
