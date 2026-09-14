#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/structpy-tree/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
clang -c "$ROOT/test/parity/profile_hooks.c" -o "$WORK/hooks.o"
for compiler in "$STAGE0" "$STAGE1"; do
    "$compiler" -emit obj -O2 -o "$WORK/test.o" "$ROOT/test/parity/lexer_buffer_return.elisa" > "$WORK/compile.log" 2>&1 || { cat "$WORK/compile.log"; exit 1; }
    clang -Wl,-dead_strip -o "$WORK/test" "$WORK/test.o" "$WORK/hooks.o" "$ROOT/build/runtime/elisacore_runtime.o"
    "$WORK/test"
done
printf 'lexer returned-buffer lifetime: stage0/stage1 runtime PASS\n'
