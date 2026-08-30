#!/usr/bin/env bash
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISACORE_BIN="${ELISACORE_BIN:-$ROOT/../../Go projects/structpy-tree/compiler/bin/elisac}"
LLVM_CONFIG="${LLVM_CONFIG:-/opt/homebrew/opt/llvm/bin/llvm-config}"
if [ ! -x "$ELISACORE_BIN" ] || [ ! -x "$LLVM_CONFIG" ]; then
    echo "easm_provenance_merge_smoke SKIP: stage0 compiler or llvm-config not found"
    exit 0
fi
mkdir -p "$ROOT/build"
if ! "$ELISACORE_BIN" -emit obj -O2 -o "$ROOT/build/easm_provenance_merge_smoke.o" "$ROOT/test/breadth/easm_provenance_merge_smoke.elisa" 2>"$ROOT/build/easm_provenance_merge_smoke.log"; then
    echo "easm_provenance_merge_smoke FAILED: provenance merge API did not compile"
    rg -n "error:" "$ROOT/build/easm_provenance_merge_smoke.log" | tail -20
    exit 1
fi
if ! clang -o "$ROOT/build/easm_provenance_merge_smoke" "$ROOT/build/easm_provenance_merge_smoke.o" -L"$($LLVM_CONFIG --libdir)" -lLLVM -Wl,-rpath,"$($LLVM_CONFIG --libdir)"; then
    echo "easm_provenance_merge_smoke FAILED: could not link provenance merge test"
    exit 1
fi
if "$ROOT/build/easm_provenance_merge_smoke"; then
    echo "easm_provenance_merge_smoke OK"
else
    echo "easm_provenance_merge_smoke FAILED: conflicting branch provenance was accepted"
    exit 1
fi
