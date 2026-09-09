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
RUNTIME_OBJ="$ROOT/build/runtime/elisacore_runtime.o"
[ -f "$RUNTIME_OBJ" ] || { echo "backend_trace_smoke SKIP: no runtime object"; exit 0; }
FALLBACK_OBJ="$BUILD/runtime_fallback.o"
clang -c -fPIC -fno-builtin -O2 -o "$FALLBACK_OBJ" "$ROOT/scripts/pymodule_runtime_fallback.c"
PROFILE_OBJ="$BUILD/profile_hooks.o"
clang -c -O2 -o "$PROFILE_OBJ" "$ROOT/test/parity/profile_hooks.c"

"$ELISACORE_BIN" -emit obj -O2 -o "$BUILD/driver.o" "$ROOT/test/breadth/emit_trace.elisa" \
    >"$BUILD/build.log" 2>&1
clang -x c -c -o "$BUILD/puts_shim.o" - <<'EOF'
#include <stdio.h>
int trace_puts(const char *s) __asm__("___ovl__puts__cstr__puts");
int trace_puts(const char *s) { return puts(s); }
EOF
clang -o "$BUILD/emit_trace" "$BUILD/driver.o" "$FALLBACK_OBJ" "$PROFILE_OBJ" "$BUILD/puts_shim.o" \
    -L"$LIBDIR" -lLLVM -Wl,-rpath,"$LIBDIR"

src=$'def helper(x: i64) -> i64:\n    y: i64 = x + 1\n    return y\n\ndef main() -> i64:\n    return helper(41)\n'
printf '%s' "$src" | "$BUILD/emit_trace" > "$BUILD/trace.ll"
# Trace IDs are the current stable ABI: the legacy declarations remain for host
# compatibility, while emitted calls use the ID-carrying forms so a trace can be
# correlated across independently compiled units.
grep -Eq 'declare void @elisa_trace_record(_id)?\(ptr, i32' "$BUILD/trace.ll"
grep -q 'call void @elisa_trace_record' "$BUILD/trace.ll"
grep -Eq 'declare void @elisa_trace_function_entry(_id)?\(ptr, i32' "$BUILD/trace.ll"
grep -q 'call void @elisa_trace_function_entry' "$BUILD/trace.ll"
grep -Eq 'declare void @elisa_trace_function_exit(_id)?\(ptr, i32' "$BUILD/trace.ll"
grep -q 'call void @elisa_trace_function_exit' "$BUILD/trace.ll"
grep -Eq 'declare void @elisa_trace_record_value(_id)?\(ptr, i32' "$BUILD/trace.ll"
grep -q 'call void @elisa_trace_record_value' "$BUILD/trace.ll"
grep -q 'declare void @elisa_trace_install_fault_handler()' "$BUILD/trace.ll"
grep -q 'call void @elisa_trace_install_fault_handler()' "$BUILD/trace.ll"
"$LLC" -filetype=obj -o "$BUILD/trace.o" "$BUILD/trace.ll"
echo "backend trace smoke OK"
