#!/usr/bin/env bash
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISACORE_BIN="${ELISACORE_BIN:-$ROOT/../../Go projects/structpy-tree/compiler/bin/elisac}"
LLVM_CONFIG="${LLVM_CONFIG:-/opt/homebrew/opt/llvm/bin/llvm-config}"
if [ ! -x "$ELISACORE_BIN" ] || [ ! -x "$LLVM_CONFIG" ]; then
    echo "easm_native_driver_smoke SKIP: stage0 compiler or llvm-config not found"
    exit 0
fi
mkdir -p "$ROOT/build"
if ! "$ELISACORE_BIN" -emit obj -O2 -o "$ROOT/build/easm_native_driver.o" "$ROOT/test/breadth/easm_native_driver.elisa" 2>"$ROOT/build/easm_native_driver.log"; then
    echo "easm_native_driver_smoke FAILED: stage1 driver did not compile"
    sed -n '1,20p' "$ROOT/build/easm_native_driver.log"
    exit 1
fi
if ! clang -o "$ROOT/build/easm_native_driver" "$ROOT/build/easm_native_driver.o" -L"$("$LLVM_CONFIG" --libdir)" -lLLVM -Wl,-rpath,"$("$LLVM_CONFIG" --libdir)"; then
    echo "easm_native_driver_smoke FAILED: could not link stage1 driver"
    exit 1
fi
assembly=$(printf 'module native\ntarget x86_64\nexport def finish() -> void abi c:\n    ret\n' | "$ROOT/build/easm_native_driver")
case "$assembly" in
    *".globl finish"*"finish:"*"ret"*) echo "easm_native_driver_smoke OK" ;;
    *) echo "easm_native_driver_smoke FAILED: unexpected assembly"; printf '%s\n' "$assembly"; exit 1 ;;
esac
