#!/usr/bin/env bash
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISACORE_BIN="${ELISACORE_BIN:-$HOME/.elisac/elisac}"
LLVM_CONFIG="${LLVM_CONFIG:-/opt/homebrew/opt/llvm/bin/llvm-config}"
if [ ! -x "$ELISACORE_BIN" ] || [ ! -x "$LLVM_CONFIG" ]; then
    echo "easm_template_patch_smoke SKIP: stage0 compiler or llvm-config not found"
    exit 0
fi
mkdir -p "$ROOT/build"
if ! "$ELISACORE_BIN" -emit obj -O2 -o "$ROOT/build/easm_template_patch_smoke.o" "$ROOT/test/breadth/easm_template_patch_smoke.elisa" 2>"$ROOT/build/easm_template_patch_smoke.log"; then
    echo "easm_template_patch_smoke FAILED: stage1 template patch test did not compile"
    sed -n '1,20p' "$ROOT/build/easm_template_patch_smoke.log"
    exit 1
fi
if ! clang -o "$ROOT/build/easm_template_patch_smoke" "$ROOT/build/easm_template_patch_smoke.o" -L"$("$LLVM_CONFIG" --libdir)" -lLLVM -Wl,-rpath,"$("$LLVM_CONFIG" --libdir)"; then
    echo "easm_template_patch_smoke FAILED: could not link patch test"
    exit 1
fi
set +e
"$ROOT/build/easm_template_patch_smoke"
status=$?
set -e
if [ "$status" -eq 42 ]; then
    echo "easm_template_patch_smoke OK"
else
    echo "easm_template_patch_smoke FAILED: expected exit 42, got $status"
    exit 1
fi
