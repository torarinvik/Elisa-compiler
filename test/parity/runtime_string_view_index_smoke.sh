#!/usr/bin/env bash
# Check string-view indexing bounds with both compilers at O0 and O3.
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
RUNTIME="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
TIMEOUT="$(command -v gtimeout || command -v timeout)"
[[ -x "$STAGE0" && -x "$STAGE1" && -f "$RUNTIME" ]] || { echo "missing compiler or runtime" >&2; exit 2; }
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-index-bounds.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
bash "$ROOT/scripts/write_profiler_hook_fallbacks.sh" > "$WORK/hooks.c"
"$TIMEOUT" -k 1s 29s clang -O2 -c "$WORK/hooks.c" -o "$WORK/hooks.o"
for stage in 0 1; do
  compiler="$STAGE0"
  [[ "$stage" == 1 ]] && compiler="$STAGE1"
  for level in 0 3; do
    object="$WORK/stage${stage}-o${level}.o"
    executable="$WORK/stage${stage}-o${level}"
    "$TIMEOUT" -k 1s 29s "$compiler" -emit obj "-O$level" -o "$object" "$ROOT/test/parity/fixtures/runtime_string_view_index_bounds.elisa"
    if [[ "$stage" == 0 ]]; then
      "$TIMEOUT" -k 1s 29s clang $ELISA_LD_DEAD_STRIP $ELISA_LINK_EXE_FLAGS "$object" "$WORK/hooks.o" -o "$executable"
    else
      "$TIMEOUT" -k 1s 29s clang $ELISA_LD_DEAD_STRIP $ELISA_LINK_EXE_FLAGS "$object" "$RUNTIME" -o "$executable"
    fi
    "$TIMEOUT" -k 1s 5s "$executable"
  done
done
echo "runtime_string_view_index_smoke OK"
