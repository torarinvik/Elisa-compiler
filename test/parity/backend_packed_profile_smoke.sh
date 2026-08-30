#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISACORE_BIN="${ELISACORE_BIN:-$ROOT/../../Go projects/structpy-tree/compiler/bin/elisac}"
LLVM_CONFIG="${LLVM_CONFIG:-/opt/homebrew/opt/llvm/bin/llvm-config}"
[ -x "$ELISACORE_BIN" ] || { echo "backend packed profile smoke SKIP: no elisac"; exit 0; }
[ -x "$LLVM_CONFIG" ] || { echo "backend packed profile smoke SKIP: no llvm-config"; exit 0; }

BUILD="$ROOT/build/packed_profile_smoke"
mkdir -p "$BUILD"
LIBDIR="$($LLVM_CONFIG --libdir)"

"$ELISACORE_BIN" -emit obj -O2 -o "$BUILD/driver.o" "$ROOT/test/breadth/emit_native.elisa" >/dev/null 2>&1
clang -o "$BUILD/driver" "$BUILD/driver.o" -L"$LIBDIR" -lLLVM -Wl,-rpath,"$LIBDIR"

src=$'@packed_profile(retained_reads)\npacked enum Node:\n    Leaf(v: i64)\n    Tag(t: i64)\n\ndef build(owner: Arena) -> i64:\n    store: Node.Store[Local] = Node.Store(owner)\n    result: mutable i64 = 0\n    in store:\n        n: Node = new Node.Leaf(v: 42)\n        result <- match n:\n            Node.Leaf(v): v\n            Node.Tag(t): t\n    return result\n\ndef main() -> i64:\n    region r(4096):\n        return build(r)\n'
printf '%s' "$src" | "$BUILD/driver" > "$BUILD/profile.ll"
grep -q 'declare ptr @ctx_packed_store_state_new(ptr, i64)' "$BUILD/profile.ll"
grep -q 'declare.*@ctx_packed_store_alloc_fixed_tagged_index_result' "$BUILD/profile.ll"
grep -q 'call i64 @ctx_packed_store_read_index_word(ptr .* i32 .* i64 1)' "$BUILD/profile.ll"
/opt/homebrew/opt/llvm/bin/llc -filetype=obj -o "$BUILD/profile.o" "$BUILD/profile.ll"
clang -o "$BUILD/profile" "$BUILD/profile.o" "$ROOT/build/runtime/elisacore_runtime.o"
set +e
"$BUILD/profile"
status=$?
set -e
test "$status" -eq 42
echo "backend packed profile smoke OK"
