#!/usr/bin/env bash
# Stage0/Stage1 parity: a qualified fallible call recovered with `else return`
# must lower through the hidden error out-slot instead of declining its caller.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/structpy-tree/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
FIXTURE="$ROOT/test/repro/qualified_error_else_return.elisa"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-qualified-error-else-return.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

[[ -x "$STAGE0" ]] || { echo "qualified error else-return smoke SKIP: stage0 unavailable"; exit 0; }
[[ -x "$STAGE1" ]] || { echo "qualified error else-return smoke SKIP: stage1 unavailable"; exit 0; }

"$STAGE0" -emit llvm -O0 -o "$WORK/stage0.ll" "$FIXTURE" >/dev/null 2>&1
"$STAGE1" -emit llvm -O0 -o "$WORK/stage1.ll" "$FIXTURE" >/dev/null 2>&1

for output in "$WORK/stage0.ll" "$WORK/stage1.ll"; do
    ! rg -q '!elisa\.declined' "$output"
    rg -q 'define .*render_frame' "$output"
    rg -q 'call i32 .*Graphics.*append' "$output"
done

echo "qualified error else-return parity OK"
