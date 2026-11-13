#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"  # host flags/paths: scripts/platform.sh
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISACORE_BIN="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN" || exit $?
LLVM_CONFIG="${LLVM_CONFIG:-$ELISA_LLVM_BIN_DIR/llvm-config}"
[ -x "$ELISACORE_BIN" ] || { echo "backend aos smoke FAIL: no elisac" >&2; exit 1; }
[ -x "$LLVM_CONFIG" ] || { echo "backend aos smoke FAIL: no llvm-config" >&2; exit 1; }

BUILD="$ROOT/build/aos_smoke"
mkdir -p "$BUILD"
RUNTIME_OBJ="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
[ -f "$RUNTIME_OBJ" ] || { echo "backend aos smoke FAIL: no runtime object" >&2; exit 1; }
FALLBACK_OBJ="$BUILD/runtime_fallback.o"
clang -c -fPIC -fno-builtin -O2 -o "$FALLBACK_OBJ" "$ROOT/scripts/pymodule_runtime_fallback.c"
PROFILE_OBJ="$BUILD/profile_hooks.o"
clang -c -O2 -o "$PROFILE_OBJ" "$ROOT/test/parity/profile_hooks.c"

EMITTER="${ELISA_EMIT_NATIVE:-$ROOT/build/emit_native}"
REPO_ROOT="$ROOT" ELISA_EMIT_NATIVE="$EMITTER" ELISACORE_BIN="$ELISACORE_BIN" bash "$ROOT/test/parity/build_emit_native.sh"
"$EMITTER" < "$ROOT/test/breadth/packed_aos_fixture.elisa" > "$BUILD/aos.ll"
grep -q 'declare ptr @ctx_aos_store_new(ptr, i64)' "$BUILD/aos.ll"
grep -q 'declare.*@ctx_aos_store_alloc(ptr, ptr)' "$BUILD/aos.ll"
# The runtime declares `ctx_aos_store_record(state, index: usize)`, so the index is
# i64 (commit 33320f9 moved AoS record indices to 64-bit); this assertion said i32.
grep -q 'declare ptr @ctx_aos_store_record(ptr, i64)' "$BUILD/aos.ll"

"${LLC:-$ELISA_LLVM_BIN_DIR/llc}" -filetype=obj -o "$BUILD/aos.o" "$BUILD/aos.ll"
clang $ELISA_LD_DEAD_STRIP $ELISA_LINK_EXE_FLAGS -o "$BUILD/aos" "$BUILD/aos.o" "$RUNTIME_OBJ" "$FALLBACK_OBJ" "$PROFILE_OBJ"
set +e
"$BUILD/aos"
rc=$?
set -e
test "$rc" -eq 42
echo "backend aos smoke OK"
