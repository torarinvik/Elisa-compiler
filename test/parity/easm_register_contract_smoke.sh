#!/usr/bin/env bash
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISACORE_BIN="${ELISACORE_BIN:-$ROOT/../../Go projects/structpy-tree/compiler/bin/elisac}"
LLVM_CONFIG="${LLVM_CONFIG:-/opt/homebrew/opt/llvm/bin/llvm-config}"
if [ ! -x "$ELISACORE_BIN" ] || [ ! -x "$LLVM_CONFIG" ]; then
    echo "easm_register_contract_smoke SKIP: stage0 compiler or llvm-config not found"
    exit 0
fi
mkdir -p "$ROOT/build"
if ! "$ELISACORE_BIN" -emit obj -O2 -o "$ROOT/build/easm_register_contract_smoke.o" "$ROOT/test/breadth/easm_register_contract_smoke.elisa" 2>"$ROOT/build/easm_register_contract_smoke.log"; then
    echo "easm_register_contract_smoke FAILED: stage1 verifier test did not compile"
    sed -n '1,20p' "$ROOT/build/easm_register_contract_smoke.log"
    exit 1
fi
# The OPTIONAL hooks a real link resolves to the compiler's weak fallbacks.
# Without them this link fails outright on _elisa_profile_* (the arena calls
# the profiler ABI unconditionally), which is what kept this gate red.
source "$ROOT/test/parity/native_optional_hook_objects.sh"
elisa_native_optional_hook_objects "$ROOT/build" "$ROOT"
if ! clang -o "$ROOT/build/easm_register_contract_smoke" "$ROOT/build/easm_register_contract_smoke.o" "${ELISA_OPTIONAL_HOOK_OBJECTS[@]}" -L"$("$LLVM_CONFIG" --libdir)" -lLLVM -Wl,-rpath,"$("$LLVM_CONFIG" --libdir)"; then
    echo "easm_register_contract_smoke FAILED: could not link verifier test"
    exit 1
fi
if "$ROOT/build/easm_register_contract_smoke"; then
    echo "easm_register_contract_smoke OK"
else
    echo "easm_register_contract_smoke FAILED: invalid register contracts were accepted"
    exit 1
fi
