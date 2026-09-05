#!/usr/bin/env bash
# Stage0/stage1 parity: qualified error calls in module-local value initializers
# must preserve the callee owner for every module in the compilation unit.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/structpy-tree/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
FIXTURE="$ROOT/test/repro/multi_module_qualified_error_call.elisa"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-multi-qualified-error.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

[[ -x "$STAGE0" ]] || { echo "multi-module qualified error smoke SKIP: stage0 unavailable"; exit 0; }
[[ -x "$STAGE1" ]] || { echo "multi-module qualified error smoke SKIP: stage1 unavailable"; exit 0; }

"$STAGE0" -emit llvm -O0 -o "$WORK/stage0.ll" "$FIXTURE" >/dev/null 2>&1
"$STAGE1" -emit llvm -O0 -o "$WORK/stage1.ll" "$FIXTURE" >/dev/null 2>&1

for output in "$WORK/stage0.ll" "$WORK/stage1.ll"; do
    ! rg -q '!elisa\.declined' "$output"
    rg -q 'call i32 .*First.*advance' "$output"
    rg -q 'call i32 .*Second.*advance' "$output"
done

echo "multi-module qualified error parity OK: module-local try lowering preserves owners"
