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
PATHS_SOURCE="$ROOT/test/repro/try_void_recovery_paths.elisa"
CLANG="${ELISA_CLANG:-/opt/homebrew/opt/llvm/bin/clang}"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-try-void.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

[[ -x "$STAGE0" ]] || { echo "void try smoke SKIP: stage0 unavailable"; exit 0; }
[[ -x "$STAGE1" ]] || { echo "void try smoke SKIP: stage1 unavailable"; exit 0; }

[[ -x "$CLANG" ]] || { echo "void try smoke FAIL: clang unavailable" >&2; exit 1; }
for optimization in 0 1 2 3; do
    for generation in stage0 stage1; do
        compiler="$STAGE0"
        [[ "$generation" != stage1 ]] || compiler="$STAGE1"
        output="$WORK/$generation-O$optimization.ll"
        "$compiler" -emit llvm "-O$optimization" -o "$output" "$SOURCE"
        ! rg -q '!elisa\.declined|alloca void|load void|store void' "$output"
        paths_output="$WORK/$generation-paths-O$optimization.ll"
        "$compiler" -emit llvm "-O$optimization" -o "$paths_output" "$PATHS_SOURCE"
        ! rg -q '!elisa\.declined|alloca void|load void|store void' "$paths_output"
        executable="$WORK/$generation-paths-O$optimization"
        "$CLANG" -Wno-override-module "$paths_output" -o "$executable"
        "$executable"
    done
done

echo "void try else smoke OK: O0-O3 no-op and conditional side-effect recovery match stage0"
