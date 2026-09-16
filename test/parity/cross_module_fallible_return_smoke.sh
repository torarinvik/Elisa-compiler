#!/usr/bin/env bash
# Stage0/Stage1 parity: a qualified fallible call returned directly from an
# error function must propagate through the callee's hidden out/status ABI.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0" || exit $?
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1" || exit $?
FIXTURE="$ROOT/test/repro/cross_module_fallible_scalar.elisa"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-cross-module-fallible.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

[[ -x "$STAGE0" ]] || { echo "cross-module fallible return smoke FAIL: stage0 unavailable" >&2; exit 1; }
[[ -x "$STAGE1" ]] || { echo "cross-module fallible return smoke FAIL: stage1 unavailable" >&2; exit 1; }

"$STAGE0" -emit llvm -O0 -o "$WORK/stage0.ll" "$FIXTURE" >/dev/null 2>&1
"$STAGE1" -emit llvm -O0 -o "$WORK/stage1.ll" "$FIXTURE" >/dev/null 2>&1

for output in "$WORK/stage0.ll" "$WORK/stage1.ll"; do
    ! rg -q '!elisa\.declined' "$output"
    rg -q 'define .*RenderHost.*checked' "$output"
    rg -q 'define .*WasmBrowser.*append' "$output"
    rg -q 'call i32 .*RenderHost.*checked' "$output"
done

echo "cross-module fallible return parity OK"
