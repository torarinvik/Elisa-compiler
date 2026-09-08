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
if command -v sha256sum >/dev/null 2>&1; then
  HASH_COMMAND=(sha256sum)
elif command -v shasum >/dev/null 2>&1; then
  HASH_COMMAND=(shasum -a 256)
else
  echo "missing SHA-256 tool (sha256sum or shasum)" >&2
  exit 2
fi
runtime_input_digest() {
  # Conservatively cover the entire runtime source tree, including interfaces.
  # Content and path hashing detects edited, added, deleted, and backdated
  # includes; the tiny entrypoint's mtime cannot establish runtime freshness.
  {
    find "$ROOT/elisacore_std" -type f \( -name '*.elisa' -o -name '*.elisai' \) \
      -exec "${HASH_COMMAND[@]}" {} + || return
    "${HASH_COMMAND[@]}" "$BUILD_SCRIPT" "$STAGE0_BIN" "$REAL_STAGE0" "$ELISA_CLANG_TOOL" || return
  } | LC_ALL=C sort | "${HASH_COMMAND[@]}" | awk '{print $1}'
}
runtime_object_digest() {
  "${HASH_COMMAND[@]}" < "$1" | awk '{print $1}'
}
INPUT_DIGEST="$(runtime_input_digest)"
STAMP="$OUT.inputs.sha256"
if [[ -s "$OUT" && -f "$STAMP" && "${ELISA_RUNTIME_FORCE:-0}" != 1 ]]; then
  if [[ "$(< "$STAMP")" == "$INPUT_DIGEST $(runtime_object_digest "$OUT")" ]]; then
    exit 0
  fi
fi
TMP="$OUT.$$.tmp"
RUNTIME_TMP="$OUT.runtime.$$.tmp"
HOOK_SOURCE="$OUT.hooks.$$.c"
HOOK_OBJECT="$OUT.hooks.$$.o"
STAMP_TMP="$STAMP.$$.tmp"
cleanup_runtime_build() {
  rm -f "$TMP" "$RUNTIME_TMP" "$HOOK_SOURCE" "$HOOK_OBJECT" "$STAMP_TMP"
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
  'ELISA_WEAK uint32_t elisa_profile_allocation_negotiate(uint32_t version) { (void)version; return 0; }' \
  'ELISA_WEAK uint32_t elisa_profile_region_layout_negotiate(uint32_t version) { (void)version; return 0; }' \
  'ELISA_WEAK void elisa_profile_region_layout_v1(uintptr_t arena, size_t region, uintptr_t header, uintptr_t data, size_t capacity) { (void)arena; (void)region; (void)header; (void)data; (void)capacity; }' \
  'ELISA_WEAK void elisa_profile_allocation_event_v1(uint32_t kind, uintptr_t address, size_t size, uintptr_t old_address, size_t old_size, uintptr_t arena, size_t region) {' \
  '  (void)kind; (void)address; (void)size; (void)old_address; (void)old_size; (void)arena; (void)region;' \
  '}' >"$HOOK_SOURCE"
"$ELISA_CLANG_TOOL" -c -o "$HOOK_OBJECT" "$HOOK_SOURCE"
"$ELISA_CLANG_TOOL" -r -o "$TMP" "$RUNTIME_TMP" "$HOOK_OBJECT"
if [[ "$INPUT_DIGEST" != "$(runtime_input_digest)" ]]; then
  echo "runtime inputs changed during build; keeping the previous runtime object" >&2
  exit 2
fi
printf '%s %s\n' "$INPUT_DIGEST" "$(runtime_object_digest "$TMP")" > "$STAMP_TMP"
mv -f "$TMP" "$OUT"
mv -f "$STAMP_TMP" "$STAMP"
echo "wrote $OUT"
