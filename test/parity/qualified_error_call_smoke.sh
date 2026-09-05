#!/usr/bin/env bash
# Stage0/stage1 parity: `try M::N::f() else fallback` must resolve the
# owner-qualified error function through the same ABI path as `try f()`.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/structpy-tree/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
FIXTURE="$ROOT/test/repro/module_qualified_error_call.elisa"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-qualified-error.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

[[ -x "$STAGE0" ]] || { echo "qualified error call smoke SKIP: stage0 unavailable"; exit 0; }
[[ -x "$STAGE1" ]] || { echo "qualified error call smoke SKIP: stage1 unavailable"; exit 0; }

"$STAGE0" -emit llvm -O0 -o "$WORK/stage0.ll" "$FIXTURE" >/dev/null 2>&1
"$STAGE1" -emit llvm -O0 -o "$WORK/stage1.ll" "$FIXTURE" >/dev/null 2>&1

for output in "$WORK/stage0.ll" "$WORK/stage1.ll"; do
    ! rg -q '!elisa\.declined' "$output"
    rg -q 'call i32 .*Service.*load.*ptr' "$output"
done

echo "qualified error call parity OK: nested module try lowering matches stage0"
