#!/usr/bin/env bash
# Build the complete runtime object used by native and self-hosting links.
#
# The runtime must be compiled without whole-module dead-code elimination: the stage1
# product references helpers that a small probe program does not reach. The final linker
# performs dead stripping, so retaining the definitions here is both complete and small
# in the resulting executable.
set -euo pipefail

ROOT="$(cd -- "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_SCRIPT="$ROOT/scripts/build_runtime_object.sh"
ELISA_CORE="${ELISA_CORE:-$ROOT/../../Go projects/structpy-tree}"
STAGE0_BIN="${ELISACORE_BIN:-$ELISA_CORE/compiler/bin/elisac}"
OUT="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
ELISA_CLANG_TOOL="${ELISA_CLANG:-$(command -v clang || true)}"

[[ -x "$STAGE0_BIN" ]] || {
  echo "missing stage0 compiler: $STAGE0_BIN" >&2
  exit 2
}
[[ -x "$ELISA_CLANG_TOOL" ]] || {
  echo "missing clang for profiler hook fallback: $ELISA_CLANG_TOOL" >&2
  exit 2
}
mkdir -p "$(dirname "$OUT")"
# ATOMIC, and only when stale. This used to emit straight onto $OUT; six gate checks call this
# script, so a rebuild mid-gate truncated the object under a sibling's link and backend_native
# reported "Undefined symbols for architecture arm64" for cases that link fine alone
# (2026-09-07, four consecutive gates). Same shape as build_emit_native.sh.
SRC="$ROOT/elisacore_std/native_runtime_support.elisa"
# Freshness against the REAL stage0: in the gate STAGE0_BIN is the tools/s0cache wrapper,
# whose own mtime says nothing about the compiler.
REAL_STAGE0="${ELISA_S0_REAL:-$STAGE0_BIN}"
if [[ -s "$OUT" && ! "$SRC" -nt "$OUT" && ! "$BUILD_SCRIPT" -nt "$OUT" && ! "$REAL_STAGE0" -nt "$OUT" && "${ELISA_RUNTIME_FORCE:-0}" != 1 ]]; then
  exit 0
fi
TMP="$OUT.$$.tmp"
RUNTIME_TMP="$OUT.runtime.$$.tmp"
HOOK_SOURCE="$OUT.hooks.$$.c"
HOOK_OBJECT="$OUT.hooks.$$.o"
cleanup_runtime_build() {
  rm -f "$TMP" "$RUNTIME_TMP" "$HOOK_SOURCE" "$HOOK_OBJECT"
}
trap cleanup_runtime_build EXIT
"$STAGE0_BIN" -emit obj -O0 -o "$RUNTIME_TMP" "$SRC"
printf '%s\n' \
  '#include <stddef.h>' \
  '#include <stdint.h>' \
  '#if defined(__GNUC__) || defined(__clang__)' \
  '#define ELISA_WEAK __attribute__((weak))' \
  '#else' \
  '#define ELISA_WEAK' \
  '#endif' \
  'ELISA_WEAK void elisa_profile_allocation_event(uint32_t kind, uintptr_t address, size_t size, uintptr_t old_address, size_t old_size, uintptr_t arena, size_t region) {' \
  '  (void)kind; (void)address; (void)size; (void)old_address; (void)old_size; (void)arena; (void)region;' \
  '}' >"$HOOK_SOURCE"
"$ELISA_CLANG_TOOL" -c -o "$HOOK_OBJECT" "$HOOK_SOURCE"
"$ELISA_CLANG_TOOL" -r -o "$TMP" "$RUNTIME_TMP" "$HOOK_OBJECT"
mv -f "$TMP" "$OUT"
echo "wrote $OUT"
