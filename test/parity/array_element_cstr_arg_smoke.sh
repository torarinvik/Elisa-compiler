#!/usr/bin/env bash
# Stage0/stage1 regression: passing a fixed-array byte value to a cstr parameter
# must be diagnosed; the buffer address is a separate, explicit expression.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$HOME/.elisac/elisac}"
STAGE1="$ROOT/scripts/elisac_stage1.sh"
FIXTURE="$ROOT/test/repro/array_element_cstr_arg.elisa"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

set +e
"$STAGE0" -emit llvm -o "$TMP_DIR/stage0.ll" "$FIXTURE" >"$TMP_DIR/stage0.err" 2>&1
stage0_status=$?
"$STAGE1" -emit llvm -o "$TMP_DIR/stage1.ll" "$FIXTURE" >"$TMP_DIR/stage1.err" 2>&1
stage1_status=$?
set -e

test "$stage0_status" -ne 0
test "$stage1_status" -ne 0
rg -q 'expects cstr, got u8' "$TMP_DIR/stage0.err"
rg -q 'expects cstr, got u8' "$TMP_DIR/stage1.err"

echo "fixed-array byte to cstr argument parity OK"
