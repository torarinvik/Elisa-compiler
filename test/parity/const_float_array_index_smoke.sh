#!/usr/bin/env bash
# Stage0/stage1 regression for f64 literals in fixed-array constants.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/structpy-tree/compiler/bin/elisac}"
STAGE1="$ROOT/scripts/elisac_stage1.sh"
FIXTURE="$ROOT/test/repro/const_float_array_index.elisa"
RUNTIME="$ROOT/build/runtime/elisacore_runtime.o"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

"$STAGE0" -emit llvm -o "$TMP_DIR/stage0.ll" "$FIXTURE"
"$STAGE1" -emit llvm -o "$TMP_DIR/stage1.ll" "$FIXTURE"

rg -q 'define (internal )?double @weight\(i64' "$TMP_DIR/stage0.ll"
rg -q 'define (internal )?double @weight\(i64' "$TMP_DIR/stage1.ll"
! rg -q '!elisa\.declined' "$TMP_DIR/stage1.ll"
rg -q '@WEIGHTS = internal constant \[4 x double\]' "$TMP_DIR/stage0.ll"
rg -q '@WEIGHTS = internal constant \[4 x double\]' "$TMP_DIR/stage1.ll"

"$STAGE0" -emit obj -O0 -o "$TMP_DIR/stage0.o" "$FIXTURE" >/dev/null 2>&1
"$STAGE1" -emit obj -O0 -o "$TMP_DIR/stage1.o" "$FIXTURE" >/dev/null 2>&1

cc "$TMP_DIR/stage0.o" "$RUNTIME" -o "$TMP_DIR/stage0"
cc "$TMP_DIR/stage1.o" "$RUNTIME" -o "$TMP_DIR/stage1"
set +e
"$TMP_DIR/stage0"
stage0_status=$?
"$TMP_DIR/stage1"
stage1_status=$?
set -e
test "$stage0_status" -eq 43
test "$stage1_status" -eq 43

echo "constant float-array index parity OK: stage0 and stage1 return 43"
