#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$HOME/.elisac/elisac}"
STAGE1="$ROOT/scripts/elisac_stage1.sh"
FIXTURE="$ROOT/test/repro/const_bitwise_aggregate.elisa"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

"$STAGE0" -emit llvm -o "$WORK/stage0.ll" "$FIXTURE"
"$STAGE1" -emit llvm -o "$WORK/stage1.ll" "$FIXTURE"

rg -q 'define i32 @get_mask\(i32' "$WORK/stage0.ll"
rg -q 'define i32 @get_mask\(i32' "$WORK/stage1.ll"
rg -q 'define i32 @has_bit\(i32 %0, i32 %1' "$WORK/stage0.ll"
rg -q 'define i32 @has_bit\(i32 %0, i32 %1' "$WORK/stage1.ll"
rg -q '@MASKS = internal constant \[4 x i32\] \[i32 2, i32 5, i32 512, i32 15\]' "$WORK/stage0.ll"
rg -q '@MASKS = internal constant \[4 x i32\] \[i32 2, i32 5, i32 512, i32 15\]' "$WORK/stage1.ll"
! rg -q '!elisa\.declined' "$WORK/stage1.ll"

echo "constant bitwise aggregate parity OK"
