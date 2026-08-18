#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../Elisa-core/compiler/bin/elisacore}"
STAGE1="$ROOT/scripts/elisac_stage1.sh"
FIXTURE="$ROOT/test/repro/export_optional_ref_return.elisa"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

"$STAGE0" -emit llvm "$FIXTURE" >"$WORK/stage0.ll"
"$STAGE1" -emit llvm -o "$WORK/stage1.ll" "$FIXTURE"
"$STAGE0" -emit header -o "$WORK/stage0.h" "$FIXTURE"
"$STAGE1" -emit header -o "$WORK/stage1.h" "$FIXTURE"

rg -q 'define ptr @optional_label\(' "$WORK/stage0.ll"
rg -q 'define ptr @optional_label\(' "$WORK/stage1.ll"
rg -q 'uint8_t \*export_optional_label\(' "$WORK/stage0.h"
rg -q 'uint8_t \*export_optional_label\(' "$WORK/stage1.h"
cmp "$WORK/stage0.h" "$WORK/stage1.h"

if command -v opt >/dev/null 2>&1; then
    opt -passes=verify "$WORK/stage0.ll" -disable-output
    opt -passes=verify "$WORK/stage1.ll" -disable-output
elif [ -x /opt/homebrew/opt/llvm/bin/opt ]; then
    /opt/homebrew/opt/llvm/bin/opt -passes=verify "$WORK/stage0.ll" -disable-output
    /opt/homebrew/opt/llvm/bin/opt -passes=verify "$WORK/stage1.ll" -disable-output
fi

echo "optional reference return parity OK"
