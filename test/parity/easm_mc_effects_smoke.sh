#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
ELISACORE_BIN=${ELISACORE_BIN:-"$ROOT/../../Go projects/structpy-tree/compiler/bin/elisac"}
LLVM_CONFIG=${LLVM_CONFIG:-/opt/homebrew/opt/llvm/bin/llvm-config}
LLVM_MC=${LLVM_MC:-/opt/homebrew/opt/llvm/bin/llvm-mc}
CXX=${CXX:-/opt/homebrew/opt/llvm/bin/clang++}
BUILD="$ROOT/build"

if [ ! -x "$ELISACORE_BIN" ] || [ ! -x "$LLVM_CONFIG" ] || [ ! -x "$LLVM_MC" ] || [ ! -x "$CXX" ]; then
    echo "easm_mc_effects_smoke SKIP: stage0 compiler and LLVM MC toolchain not found"
    exit 0
fi

mkdir -p "$BUILD"
if ! timeout 45 "$ELISACORE_BIN" -emit obj -O2 -o "$BUILD/easm_effect_driver.o" \
    "$ROOT/test/breadth/easm_effect_driver.elisa" >"$BUILD/easm_effect_driver.log" 2>&1; then
    echo "easm_mc_effects_smoke FAILED: could not compile effect driver"
    sed -n '1,80p' "$BUILD/easm_effect_driver.log"
    exit 1
fi

# The OPTIONAL hooks a real link resolves to the compiler's weak fallbacks. The arena
# calls the profiler ABI unconditionally, so without them this link fails on
# _elisa_profile_* -- and here the error went to a log file, so the gate only ever
# said "could not link".
source "$ROOT/test/parity/native_optional_hook_objects.sh"
elisa_native_optional_hook_objects "$BUILD" "$ROOT"
if ! timeout 45 "$CXX" "$BUILD/easm_effect_driver.o" "${ELISA_OPTIONAL_HOOK_OBJECTS[@]}" -o "$BUILD/easm_effect_driver" \
    -L"$($LLVM_CONFIG --libdir)" -lLLVM -Wl,-rpath,"$($LLVM_CONFIG --libdir)" \
    >"$BUILD/easm_effect_driver.linklog" 2>&1; then
    echo "easm_mc_effects_smoke FAILED: could not link effect driver"
    sed -n '1,80p' "$BUILD/easm_effect_driver.linklog"
    exit 1
fi

timeout 45 python3 "$ROOT/scripts/easm_mc_effects_check.py" \
    --driver "$BUILD/easm_effect_driver" --llvm-config "$LLVM_CONFIG" \
    --llvm-mc "$LLVM_MC" --cxx "$CXX"
