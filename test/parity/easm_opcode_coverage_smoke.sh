#!/usr/bin/env bash
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISACORE_BIN="${ELISACORE_BIN:-$ROOT/../../Go projects/structpy-tree/compiler/bin/elisac}"
LLVM_CONFIG="${LLVM_CONFIG:-/opt/homebrew/opt/llvm/bin/llvm-config}"
if [ ! -x "$ELISACORE_BIN" ] || [ ! -x "$LLVM_CONFIG" ]; then
    echo "easm_opcode_coverage_smoke SKIP: stage0 compiler or llvm-config not found"
    exit 0
fi
mkdir -p "$ROOT/build"
if ! "$ELISACORE_BIN" -emit obj -O2 -o "$ROOT/build/easm_opcode_coverage_smoke.o" "$ROOT/test/breadth/easm_opcode_coverage_smoke.elisa" 2>"$ROOT/build/easm_opcode_coverage_smoke.log"; then
    echo "easm_opcode_coverage_smoke FAILED: opcode coverage test did not compile"
    tail -20 "$ROOT/build/easm_opcode_coverage_smoke.log"
    exit 1
fi
clang -o "$ROOT/build/easm_opcode_coverage_smoke" "$ROOT/build/easm_opcode_coverage_smoke.o" -L"$("$LLVM_CONFIG" --libdir)" -lLLVM -Wl,-rpath,"$("$LLVM_CONFIG" --libdir)"
if "$ROOT/build/easm_opcode_coverage_smoke"; then
    echo "easm_opcode_coverage_smoke OK"
else
    echo "easm_opcode_coverage_smoke FAILED: stage1 operation/capability parity regressed"
    exit 1
fi
