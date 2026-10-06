#!/usr/bin/env bash
# `place.field <- f(place.field)` with an lmut parameter and a void result is the
# docs/120 §8 arg-manifest on a field path: the call mutates the field through its
# reference argument and nothing is stored. stage1 used to lower the void result as a
# store, which LLVM rejected by crashing the compiler (DataLayout::getABITypeAlign).
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
SOURCE="$ROOT/test/fixtures/lmut_field/manifest.elisa"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1" || exit $?
RUNTIME="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
[[ -f "$RUNTIME" ]] || { echo "lmut field manifest smoke FAIL: no runtime object" >&2; exit 1; }

WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-lmut-field.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

for optimization in O0 O2; do
    ELISA_STAGE1_BIN="$STAGE1" bash "$ROOT/scripts/elisac_stage1.sh" "-$optimization" \
        -o "$WORK/stage1-$optimization.o" "$SOURCE" >/dev/null
    clang -Wl,-undefined,dynamic_lookup -Wl,-dead_strip \
        -o "$WORK/stage1-$optimization" "$WORK/stage1-$optimization.o" "$RUNTIME"
    set +e
    "$WORK/stage1-$optimization"
    rc=$?
    set -e
    [[ "$rc" -eq 115 ]] || { echo "lmut field manifest smoke FAIL ($optimization): stage1 returned $rc, expected 115" >&2; exit 1; }
done

echo "lmut field manifest smoke OK: a field-path lmut call writes through and stores nothing at O0/O2"
