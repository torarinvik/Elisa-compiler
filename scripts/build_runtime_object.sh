#!/usr/bin/env bash
# Build the complete runtime object used by native and self-hosting links.
#
# The runtime must be compiled without whole-module dead-code elimination: the stage1
# product references helpers that a small probe program does not reach. The final linker
# performs dead stripping, so retaining the definitions here is both complete and small
# in the resulting executable.
set -euo pipefail

ROOT="$(cd -- "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$ROOT/../../Go projects/structpy-tree}"
STAGE0_BIN="${ELISACORE_BIN:-$ELISA_CORE/compiler/bin/elisac}"
OUT="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"

[[ -x "$STAGE0_BIN" ]] || {
  echo "missing stage0 compiler: $STAGE0_BIN" >&2
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
if [[ -s "$OUT" && ! "$SRC" -nt "$OUT" && ! "$REAL_STAGE0" -nt "$OUT" && "${ELISA_RUNTIME_FORCE:-0}" != 1 ]]; then
  exit 0
fi
TMP="$OUT.$$.tmp"
"$STAGE0_BIN" -emit obj -O0 -o "$TMP" "$SRC" || { rm -f "$TMP"; exit 1; }
mv -f "$TMP" "$OUT"
echo "wrote $OUT"
