#!/usr/bin/env bash
# Build the complete runtime object used by native and self-hosting links.
#
# The runtime must be compiled without whole-module dead-code elimination: the stage1
# product references helpers that a small probe program does not reach. The final linker
# performs dead stripping, so retaining the definitions here is both complete and small
# in the resulting executable.
set -euo pipefail

ROOT="$(cd -- "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAGE0_BIN="${ELISACORE_BIN:-${HOME}/.elisac/elisac}"
OUT="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"

[[ -x "$STAGE0_BIN" ]] || {
  echo "missing stage0 compiler: $STAGE0_BIN" >&2
  exit 2
}
mkdir -p "$(dirname "$OUT")"
"$STAGE0_BIN" -emit obj -O0 -o "$OUT" "$ROOT/elisacore_std/native_runtime_support.elisa"
echo "wrote $OUT"
