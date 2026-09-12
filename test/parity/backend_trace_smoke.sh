#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISACORE_BIN="${ELISACORE_BIN:-$ROOT/../../Go projects/structpy-tree/compiler/bin/elisac}"
LLVM_CONFIG="${LLVM_CONFIG:-/opt/homebrew/opt/llvm/bin/llvm-config}"
LLC="${LLC:-/opt/homebrew/opt/llvm/bin/llc}"
[ -x "$ELISACORE_BIN" ] || { echo "backend_trace_smoke SKIP: no elisac"; exit 0; }
[ -x "$LLVM_CONFIG" ] || { echo "backend_trace_smoke SKIP: no llvm-config"; exit 0; }
[ -x "$LLC" ] || { echo "backend_trace_smoke SKIP: no llc"; exit 0; }

BUILD="$ROOT/build/trace_smoke"
mkdir -p "$BUILD"
LIBDIR="$($LLVM_CONFIG --libdir)"

"$ELISACORE_BIN" -emit obj -O2 -o "$BUILD/driver.o" "$ROOT/test/breadth/emit_trace.elisa" \
    >"$BUILD/build.log" 2>&1
clang -x c -c -o "$BUILD/puts_shim.o" - <<'EOF'
#include <stdio.h>
int trace_puts(const char *s) __asm__("___ovl__puts__cstr__puts");
int trace_puts(const char *s) { return puts(s); }
EOF
# The OPTIONAL hooks a real link resolves to the compiler's weak fallbacks.
# Without them this link fails outright on _elisa_profile_* (the arena calls
# the profiler ABI unconditionally), which is what kept this gate red.
source "$ROOT/test/parity/native_optional_hook_objects.sh"
elisa_native_optional_hook_objects "$BUILD" "$ROOT"
clang -o "$BUILD/emit_trace" "$BUILD/driver.o" "${ELISA_OPTIONAL_HOOK_OBJECTS[@]}" "$BUILD/puts_shim.o" \
    -L"$LIBDIR" -lLLVM -Wl,-rpath,"$LIBDIR"

src=$'def helper(x: i64) -> i64:\n    y: i64 = x + 1\n    return y\n\ndef main() -> i64:\n    return helper(41)\n'
printf '%s' "$src" | "$BUILD/emit_trace" > "$BUILD/trace.ll"
# The function entry/exit hooks carry a stable IDENTITY as a third argument
# (e25efbd7, 036b61d6). These assertions still named the pre-id two-argument
# signature, so the `declare` checks failed outright while the `call` checks
# passed by substring accident against `..._entry_id`. Both now name the real ABI.
grep -q 'declare void @elisa_trace_record(ptr, i32)' "$BUILD/trace.ll"
grep -q 'call void @elisa_trace_record' "$BUILD/trace.ll"
grep -q 'declare void @elisa_trace_function_entry_id(ptr, i32, i64)' "$BUILD/trace.ll"
grep -q 'call void @elisa_trace_function_entry_id' "$BUILD/trace.ll"
grep -q 'declare void @elisa_trace_function_exit_id(ptr, i32, i64)' "$BUILD/trace.ll"
grep -q 'call void @elisa_trace_function_exit_id' "$BUILD/trace.ll"
grep -q 'declare void @elisa_trace_record_value(ptr, i32, ptr, i64, i32)' "$BUILD/trace.ll"
grep -q 'call void @elisa_trace_record_value' "$BUILD/trace.ll"
grep -q 'declare void @elisa_trace_install_fault_handler()' "$BUILD/trace.ll"
grep -q 'call void @elisa_trace_install_fault_handler()' "$BUILD/trace.ll"
"$LLC" -filetype=obj -o "$BUILD/trace.o" "$BUILD/trace.ll"
echo "backend trace smoke OK"
