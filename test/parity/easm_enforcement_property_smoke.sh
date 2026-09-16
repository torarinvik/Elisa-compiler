#!/usr/bin/env bash
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISACORE_BIN="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN" || exit $?
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
# The OPTIONAL hooks a real link resolves to the compiler's weak fallbacks.
# Without them this link fails outright on _elisa_profile_* (the arena calls
# the profiler ABI unconditionally), which is what kept this gate red.
source "$ROOT/test/parity/native_optional_hook_objects.sh"
elisa_native_optional_hook_objects "$ROOT/build" "$ROOT"
if ! clang -o "$ROOT/build/easm_enforcement_property_smoke" "$ROOT/build/easm_enforcement_property_smoke.o" "${ELISA_OPTIONAL_HOOK_OBJECTS[@]}" -L"$($LLVM_CONFIG --libdir)" -lLLVM -Wl,-rpath,"$($LLVM_CONFIG --libdir)"; then
    echo "easm_enforcement_property_smoke FAILED: link"
    exit 1
fi
if "$ROOT/build/easm_enforcement_property_smoke"; then
    echo "easm_enforcement_property_smoke OK"
else
    echo "easm_enforcement_property_smoke FAILED: enforcement property broken (exit $?)"
    exit 1
fi
