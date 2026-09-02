#!/usr/bin/env bash
# Stage1 regression: a void error call with the explicit no-op recovery.
#
# `try f() else void` is a valid statement when f returns void error[E]. It still
# uses the split error ABI (out-slot plus status), but it intentionally swallows
# the status instead of propagating it. Previously stage1 crashed while emitting
# the refinement-shaped expression, whereas stage0 accepted it.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/structpy-tree/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
SOURCE="$ROOT/test/repro/try_void_else_void.elisa"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-try-void.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

[[ -x "$STAGE0" ]] || { echo "void try smoke SKIP: stage0 unavailable"; exit 0; }
[[ -x "$STAGE1" ]] || { echo "void try smoke SKIP: stage1 unavailable"; exit 0; }

"$STAGE0" -emit llvm -O0 -o "$WORK/stage0.ll" "$SOURCE" >/dev/null 2>&1
"$STAGE1" -emit llvm -O0 -o "$WORK/stage1.ll" "$SOURCE" >/dev/null 2>&1

for output in "$WORK/stage0.ll" "$WORK/stage1.ll"; do
    ! rg -q '!elisa\.declined' "$output"
done

echo "void try else smoke OK: stage1 matches stage0 for void no-op recovery"
