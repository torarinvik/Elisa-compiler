#!/usr/bin/env bash
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISACORE_BIN="${ELISACORE_BIN:-$HOME/.elisac/elisac}"
LLVM_CONFIG="${LLVM_CONFIG:-/opt/homebrew/opt/llvm/bin/llvm-config}"
if [ ! -x "$ELISACORE_BIN" ] || [ ! -x "$LLVM_CONFIG" ]; then
    echo "easm_backend_api_smoke SKIP: stage0 compiler or llvm-config not found"
    exit 0
fi
mkdir -p "$ROOT/build"
if ! "$ELISACORE_BIN" -emit obj -O2 -o "$ROOT/build/easm_backend_api_smoke.o" "$ROOT/test/breadth/easm_backend_api_smoke.elisa" 2>"$ROOT/build/easm_backend_api_smoke.log"; then
    echo "easm_backend_api_smoke FAILED: backend API did not compile"
    rg -n "error:" "$ROOT/build/easm_backend_api_smoke.log" | tail -20
    exit 1
fi
if ! clang -o "$ROOT/build/easm_backend_api_smoke" "$ROOT/build/easm_backend_api_smoke.o" -L"$($LLVM_CONFIG --libdir)" -lLLVM -Wl,-rpath,"$($LLVM_CONFIG --libdir)"; then
    echo "easm_backend_api_smoke FAILED: could not link backend API test"
    exit 1
fi
if "$ROOT/build/easm_backend_api_smoke"; then
    echo "easm_backend_api_smoke OK"
else
    echo "easm_backend_api_smoke FAILED: derived effects or emitted-body selection was wrong"
    exit 1
fi
