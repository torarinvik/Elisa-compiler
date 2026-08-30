#!/usr/bin/env bash
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISACORE_BIN="${ELISACORE_BIN:-$ROOT/../../Go projects/structpy-tree/compiler/bin/elisac}"
LLVM_CONFIG="${LLVM_CONFIG:-/opt/homebrew/opt/llvm/bin/llvm-config}"
if [ ! -x "$ELISACORE_BIN" ] || [ ! -x "$LLVM_CONFIG" ]; then
    echo "easm_enforcement_property_smoke SKIP: tools missing"
    exit 0
fi
mkdir -p "$ROOT/build"
if ! "$ELISACORE_BIN" -emit obj -O2 -o "$ROOT/build/easm_enforcement_property_smoke.o" "$ROOT/test/breadth/easm_enforcement_property_smoke.elisa" 2>"$ROOT/build/easm_enforcement_property_smoke.log"; then
    echo "easm_enforcement_property_smoke FAILED: did not compile"
    rg -n "error:" "$ROOT/build/easm_enforcement_property_smoke.log" | tail -20
    exit 1
fi
if ! clang -o "$ROOT/build/easm_enforcement_property_smoke" "$ROOT/build/easm_enforcement_property_smoke.o" -L"$($LLVM_CONFIG --libdir)" -lLLVM -Wl,-rpath,"$($LLVM_CONFIG --libdir)"; then
    echo "easm_enforcement_property_smoke FAILED: link"
    exit 1
fi
if "$ROOT/build/easm_enforcement_property_smoke"; then
    echo "easm_enforcement_property_smoke OK"
else
    echo "easm_enforcement_property_smoke FAILED: enforcement property broken (exit $?)"
    exit 1
fi
