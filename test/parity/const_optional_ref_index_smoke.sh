#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../Elisa-core/compiler/bin/elisacore}"
STAGE1="$ROOT/scripts/elisac_stage1.sh"
FIXTURE="$ROOT/test/repro/const_optional_ref_index.elisa"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

"$STAGE0" -emit llvm "$FIXTURE" >"$WORK/stage0.ll"
"$STAGE1" -emit llvm -o "$WORK/stage1.ll" "$FIXTURE"

rg -q 'define ptr @get_string\(' "$WORK/stage0.ll"
rg -q 'define ptr @get_string\(' "$WORK/stage1.ll"
! rg -q '!elisa\.declined' "$WORK/stage1.ll"
rg -q '@STRINGS = internal constant \[2 x ptr\]' "$WORK/stage1.ll"
rg -q 'getelementptr \[2 x ptr\], ptr @STRINGS' "$WORK/stage1.ll"

echo "const optional-ref index parity OK"
