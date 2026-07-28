#!/usr/bin/env bash
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISACORE_BIN="${ELISACORE_BIN:-$HOME/.elisac/elisac}"
LLVM_CONFIG="${LLVM_CONFIG:-/opt/homebrew/opt/llvm/bin/llvm-config}"
if [ ! -x "$ELISACORE_BIN" ] || [ ! -x "$LLVM_CONFIG" ]; then
    echo "easm_guest_overlay_api_smoke SKIP: stage0 compiler or llvm-config not found"
    exit 0
fi
mkdir -p "$ROOT/build"
if ! "$ELISACORE_BIN" -emit obj -O2 -o "$ROOT/build/easm_guest_overlay_api_smoke.o" "$ROOT/test/breadth/easm_guest_overlay_api_smoke.elisa" 2>"$ROOT/build/easm_guest_overlay_api_smoke.log"; then
    echo "easm_guest_overlay_api_smoke FAILED: resolver API did not compile"
    sed -n '1,30p' "$ROOT/build/easm_guest_overlay_api_smoke.log"
    exit 1
fi
if ! clang -o "$ROOT/build/easm_guest_overlay_api_smoke" "$ROOT/build/easm_guest_overlay_api_smoke.o" -L"$("$LLVM_CONFIG" --libdir)" -lLLVM -Wl,-rpath,"$("$LLVM_CONFIG" --libdir)"; then
    echo "easm_guest_overlay_api_smoke FAILED: could not link resolver test"
    exit 1
fi
if "$ROOT/build/easm_guest_overlay_api_smoke"; then
    echo "easm_guest_overlay_api_smoke OK"
else
    echo "easm_guest_overlay_api_smoke FAILED: resolver accepted an invalid overlay access"
    exit 1
fi
