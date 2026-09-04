#!/usr/bin/env bash
# Stage1 regression: a no-recovery `try` used directly as an argument to another call.
#
# `emit_expression` has no control-flow context, so this used to leave the outer function
# declined instead of propagating the inner error. The backend now materializes the inner
# value through the existing typed propagation path before emitting the outer call.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/structpy-tree/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
SOURCE="$ROOT/test/repro/nested_try_direct_argument.elisa"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-nested-try-argument.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

[[ -x "$STAGE0" ]] || { echo "nested try argument smoke SKIP: stage0 unavailable"; exit 0; }
[[ -x "$STAGE1" ]] || { echo "nested try argument smoke SKIP: stage1 unavailable"; exit 0; }

"$STAGE0" -emit llvm -O0 -o "$WORK/stage0.ll" "$SOURCE" >/dev/null 2>&1
"$STAGE1" -emit llvm -O0 -o "$WORK/stage1.ll" "$SOURCE" >/dev/null 2>&1

for output in "$WORK/stage0.ll" "$WORK/stage1.ll"; do
    ! rg -q '!elisa\.declined' "$output"
    rg -q 'forwarded_text' "$output"
done

"$STAGE1" -emit obj -O2 -o "$WORK/stage1.o" "$SOURCE" >/dev/null 2>&1
[[ -s "$WORK/stage1.o" ]]

echo "nested try argument smoke OK: stage0 and stage1 propagate a fallible direct call argument"
