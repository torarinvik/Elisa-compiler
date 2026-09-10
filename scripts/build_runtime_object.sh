#!/usr/bin/env bash
# Build the complete runtime object used by native and self-hosting links.
#
# SELF-HOSTED: the object is compiled by the stage1 product, not by stage0. The product
# is the compiler every downstream project uses, so the runtime it links must be the
# runtime that compiler produces -- one compiler for the program and its runtime, one
# codegen to trust. stage0's part in the bootstrap ends at the seed, which links the
# product against the weak profiler-hook fallbacks alone and needs no runtime object;
# that is what lets the product build the runtime rather than the other way round.
#
# The runtime must be compiled without whole-module dead-code elimination: the stage1
# product references helpers that a small probe program does not reach. The final linker
# performs dead stripping, so retaining the definitions here is both complete and small
# in the resulting executable.
set -euo pipefail

ROOT="$(cd -- "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_SCRIPT="$ROOT/scripts/build_runtime_object.sh"
PRODUCT="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
OUT="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
ELISA_CLANG_TOOL="${ELISA_CLANG:-$(command -v clang || true)}"

[[ -x "$PRODUCT" ]] || {
  echo "missing stage1 product: $PRODUCT (run: $ROOT/scripts/elisac_stage1.sh --seed, which builds the runtime after the product)" >&2
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
    # The PRODUCT is an input: a reseed changes the compiler that builds the object.
    "${HASH_COMMAND[@]}" "$BUILD_SCRIPT" "$ROOT/scripts/write_profiler_hook_fallbacks.sh" "$PRODUCT" "$ELISA_CLANG_TOOL" || return
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
# The raw product, not the elisac_stage1.sh wrapper: the wrapper refuses a product older
# than its sources, and this script is the wrapper's own last step of a seed -- the
# freshness the wrapper would check is the freshness the caller is establishing.
"$PRODUCT" -emit obj -O0 -o "$RUNTIME_TMP" "$SRC"
bash "$ROOT/scripts/write_profiler_hook_fallbacks.sh" >"$HOOK_SOURCE"
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
