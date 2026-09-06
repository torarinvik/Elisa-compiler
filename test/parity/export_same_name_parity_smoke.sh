#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
if [[ -n "${ELISACORE_BIN:-}" ]]; then
    STAGE0="$ELISACORE_BIN"
else
    STAGE0=""
    for stage0_candidate in \
        "$ROOT/../../Go projects/structpy-tree/compiler/bin/elisac" \
        "$ROOT/../../../Go projects/structpy-tree/compiler/bin/elisac" \
        "$ROOT/../wasm-sdk-stage0/compiler/bin/elisac"; do
        if [[ -x "$stage0_candidate" ]]; then
            STAGE0="$stage0_candidate"
            break
        fi
    done
    STAGE0="${STAGE0:-$ROOT/../../Go projects/structpy-tree/compiler/bin/elisac}"
fi
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
FIXTURE="$ROOT/test/repro/export_same_name.elisa"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-same-name-parity.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

[[ -x "$STAGE0" ]] || { echo "same-name export parity SKIP: no stage0 at $STAGE0"; exit 0; }
[[ -x "$STAGE1" ]] || { echo "same-name export parity SKIP: no stage1 at $STAGE1"; exit 0; }

"$STAGE0" -emit llvm -o "$WORK/stage0.ll" "$FIXTURE"
"$STAGE1" -emit llvm -o "$WORK/stage1.ll" "$FIXTURE"

for ir in "$WORK/stage0.ll" "$WORK/stage1.ll"; do
    # Scalar same-name exports are the implementation itself, not a recursive wrapper.
    test "$(rg -c '^define i32 @add\(i32' "$ir")" -eq 1
    ! rg -q 'call i32 @add\(i32 %0, i32 %1\)' "$ir"

    # Small aggregate values use the C ABI integer carrier while the implementation keeps
    # Elisa's aggregate signature under a collision-free `.impl` symbol.
    rg -q '^define i32 @vec2_sum\.impl\(%Vec2' "$ir"
    rg -q '^define i32 @vec2_sum\(i64' "$ir"
    rg -q '^define %Vec2 @make_vec2\.impl\(' "$ir"
    rg -q '^define i64 @make_vec2\(' "$ir"

    # A same-name global is one definition, never a self-alias.
    test "$(rg -c '^@MAGIC = global' "$ir")" -eq 1
    ! rg -q '^@MAGIC\.[0-9]+ = alias' "$ir"
done

if command -v opt >/dev/null 2>&1; then
    opt -passes=verify "$WORK/stage0.ll" -disable-output
    opt -passes=verify "$WORK/stage1.ll" -disable-output
elif [[ -x /opt/homebrew/opt/llvm/bin/opt ]]; then
    /opt/homebrew/opt/llvm/bin/opt -passes=verify "$WORK/stage0.ll" -disable-output
    /opt/homebrew/opt/llvm/bin/opt -passes=verify "$WORK/stage1.ll" -disable-output
fi

echo "same-name export LLVM parity OK"
