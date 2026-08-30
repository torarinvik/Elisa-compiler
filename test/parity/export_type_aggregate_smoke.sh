#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/structpy-tree/compiler/bin/elisac}"
STAGE1="$ROOT/scripts/elisac_stage1.sh"
FIXTURE="$ROOT/test/repro/export_type_aggregate.elisa"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

"$STAGE0" -emit llvm "$FIXTURE" >"$WORK/stage0.ll"
"$STAGE1" -emit llvm -o "$WORK/stage1.ll" "$FIXTURE"

rg -q 'define i32 @fill_export_record\(ptr' "$WORK/stage0.ll"
rg -q 'define i32 @fill_export_record\(ptr' "$WORK/stage1.ll"
rg -q 'define i32 @fill_export_record_public\(ptr' "$WORK/stage0.ll"
rg -q 'define i32 @fill_export_record_public\(ptr' "$WORK/stage1.ll"
! rg -q '!elisa\.declined' "$WORK/stage1.ll"

echo "export type aggregate parity OK"
