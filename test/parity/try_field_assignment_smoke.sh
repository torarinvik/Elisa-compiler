#!/usr/bin/env bash
# A named fallible call assigned into a record field must propagate its error before
# modifying the field and store the success payload on the success path.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE0="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
RUNTIME_OBJ="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
LLVM_CONFIG="${LLVM_CONFIG:-/opt/homebrew/opt/llvm/bin/llvm-config}"
CLANG="${ELISA_CLANG:-$(dirname -- "$LLVM_CONFIG")/clang}"
FIXTURE="$ROOT/test/repro/try_field_assignment.elisa"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-try-field-assignment.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

bash "$ROOT/scripts/assert_stage0_fresh.sh" "$STAGE0"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
[[ -x "$CLANG" ]] || { echo "try field assignment smoke: missing clang: $CLANG" >&2; exit 2; }
[[ -f "$RUNTIME_OBJ" ]] || { echo "try field assignment smoke: missing runtime object: $RUNTIME_OBJ" >&2; exit 2; }

"$STAGE0" -emit obj -O0 -o "$WORK/stage0.o" "$FIXTURE"
bash "$ROOT/scripts/write_profiler_hook_fallbacks.sh" >"$WORK/hooks.c"
LIBDIR="$("$LLVM_CONFIG" --libdir)"
"$CLANG" -Wl,-dead_strip -o "$WORK/stage0" "$WORK/stage0.o" "$RUNTIME_OBJ" \
    "$WORK/hooks.c" -L"$LIBDIR" -lLLVM -Wl,-rpath,"$LIBDIR" -Wl,-stack_size,0x20000000

ELISACORE_BIN="$STAGE0" ELISA_STAGE1_BIN="$STAGE1" ELISA_RUNTIME_OBJ="$RUNTIME_OBJ" \
    bash "$ROOT/scripts/elisac_stage1.sh" -emit exe -O0 -o "$WORK/stage1" "$FIXTURE"

set +e
"$WORK/stage0"
stage0_rc=$?
"$WORK/stage1"
stage1_rc=$?
set -e
if [[ "$stage0_rc" -ne 123 || "$stage1_rc" -ne "$stage0_rc" ]]; then
    echo "try field assignment smoke FAILED: stage0=$stage0_rc stage1=$stage1_rc expected=123" >&2
    exit 1
fi
echo "try field assignment smoke OK: success payload stores; error propagation preserves the field"
