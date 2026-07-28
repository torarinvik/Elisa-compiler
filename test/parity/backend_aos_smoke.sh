#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISACORE_BIN="${ELISACORE_BIN:-$HOME/.elisac/elisac}"
LLVM_CONFIG="${LLVM_CONFIG:-/opt/homebrew/opt/llvm/bin/llvm-config}"
[ -x "$ELISACORE_BIN" ] || { echo "backend aos smoke SKIP: no elisac"; exit 0; }
[ -x "$LLVM_CONFIG" ] || { echo "backend aos smoke SKIP: no llvm-config"; exit 0; }

BUILD="$ROOT/build/aos_smoke"
mkdir -p "$BUILD"
LIBDIR="$($LLVM_CONFIG --libdir)"

"$ELISACORE_BIN" -emit obj -O2 -o "$BUILD/driver.o" "$ROOT/test/breadth/emit_native.elisa" >/dev/null 2>&1
clang -o "$BUILD/driver" "$BUILD/driver.o" -L"$LIBDIR" -lLLVM -Wl,-rpath,"$LIBDIR"
"$BUILD/driver" < "$ROOT/test/breadth/packed_aos_fixture.elisa" > "$BUILD/aos.ll"
grep -q 'declare ptr @ctx_aos_store_new(ptr, i64)' "$BUILD/aos.ll"
grep -q 'declare.*@ctx_aos_store_alloc(ptr, ptr)' "$BUILD/aos.ll"
# The runtime declares `ctx_aos_store_record(state, index: usize)`, so the index is
# i64 (commit 33320f9 moved AoS record indices to 64-bit); this assertion said i32.
grep -q 'declare ptr @ctx_aos_store_record(ptr, i64)' "$BUILD/aos.ll"

/opt/homebrew/opt/llvm/bin/llc -filetype=obj -o "$BUILD/aos.o" "$BUILD/aos.ll"
clang -Wl,-dead_strip -o "$BUILD/aos" "$BUILD/aos.o" "$ROOT/build/runtime/elisacore_runtime.o"
set +e
"$BUILD/aos"
rc=$?
set -e
test "$rc" -eq 42
echo "backend aos smoke OK"
