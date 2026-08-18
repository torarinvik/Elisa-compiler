#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../Elisa-core/compiler/bin/elisacore}"
STAGE1="$ROOT/scripts/elisac_stage1.sh"
FIXTURE="$ROOT/test/repro/export_void_wrapper.elisa"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

"$STAGE0" -emit llvm "$FIXTURE" >"$WORK/stage0.ll"
"$STAGE1" -emit llvm -o "$WORK/stage1.ll" "$FIXTURE"

rg -q 'define void @export_void_target\(' "$WORK/stage0.ll"
rg -q 'define void @export_void_target\(' "$WORK/stage1.ll"
rg -q 'define void @export_void_public\(' "$WORK/stage0.ll"
rg -q 'define void @export_void_public\(' "$WORK/stage1.ll"
! rg -q '%export\.call = call void' "$WORK/stage0.ll"
! rg -q '%export\.call = call void' "$WORK/stage1.ll"

if command -v opt >/dev/null 2>&1; then
    opt -passes=verify "$WORK/stage0.ll" -disable-output
    opt -passes=verify "$WORK/stage1.ll" -disable-output
elif [ -x /opt/homebrew/opt/llvm/bin/opt ]; then
    /opt/homebrew/opt/llvm/bin/opt -passes=verify "$WORK/stage0.ll" -disable-output
    /opt/homebrew/opt/llvm/bin/opt -passes=verify "$WORK/stage1.ll" -disable-output
fi

echo "void export wrapper parity OK"
