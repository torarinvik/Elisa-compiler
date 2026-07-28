#!/usr/bin/env bash
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISACORE_BIN="${ELISACORE_BIN:-$HOME/.elisac/elisac}"
LLVM_CONFIG="${LLVM_CONFIG:-/opt/homebrew/opt/llvm/bin/llvm-config}"
if [ ! -x "$ELISACORE_BIN" ] || [ ! -x "$LLVM_CONFIG" ]; then
    echo "backend_guest_overlay_source_smoke SKIP: tools missing"
    exit 0
fi
mkdir -p "$ROOT/build"
if ! "$ELISACORE_BIN" -emit obj -O2 -o "$ROOT/build/emit_native.o" "$ROOT/test/breadth/emit_native.elisa" 2>"$ROOT/build/emit_native_rebuild.log"; then
    echo "backend_guest_overlay_source_smoke FAILED: emit_native did not compile"
    exit 1
fi
if ! clang -o "$ROOT/build/emit_native" "$ROOT/build/emit_native.o" -L"$($LLVM_CONFIG --libdir)" -lLLVM -Wl,-rpath,"$($LLVM_CONFIG --libdir)"; then
    echo "backend_guest_overlay_source_smoke FAILED: link emit_native"
    exit 1
fi
IR="$ROOT/build/guest_overlay_source.ll"
if ! cat "$ROOT/test/breadth/guest_overlay_source_smoke.elisa" | "$ROOT/build/emit_native" >"$IR" 2>"$ROOT/build/guest_overlay_source.err"; then
    echo "backend_guest_overlay_source_smoke FAILED: emit returned non-zero"
    cat "$ROOT/build/guest_overlay_source.err"
    exit 1
fi
if rg -q "elisa.declined" "$IR"; then
    echo "backend_guest_overlay_source_smoke FAILED: module declined"
    exit 1
fi
if ! rg -q "MemoryManager_ReadU64" "$IR"; then
    echo "backend_guest_overlay_source_smoke FAILED: missing MemoryManager_ReadU64"
    exit 1
fi
if ! rg -q ", 40" "$IR"; then
    echo "backend_guest_overlay_source_smoke FAILED: missing +40 field offset"
    exit 1
fi
# Module functions carry `internal` linkage since ce054cd (it is what stops the
# duplicate-symbol collisions against the runtime object), so allow it here.
if ! rg -q "define (internal )?i64 @read_ext2\\(i64" "$IR"; then
    echo "backend_guest_overlay_source_smoke FAILED: carrier params not i64"
    exit 1
fi
echo "backend_guest_overlay_source_smoke OK"
