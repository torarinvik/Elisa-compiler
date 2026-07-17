#!/usr/bin/env bash
# The DRIVER gate: stage1 emits a native OBJECT itself (target machine +
# LLVMTargetMachineEmitToFile), with NO `llc` in the pipeline.
#
# This is deliberately a separate script from backend_native_smoke.sh. That one pipes IR
# text through llc, which is the right harness for the 241 behavioural checks; this one
# exists to prove the backend no longer NEEDS llc -- the capability DWARF and -Wperf are
# blocked on, since both are invisible in IR text and -Wperf's check is post-optimization.
RUN() { if command -v timeout >/dev/null 2>&1; then timeout 20 "$@"; else "$@"; fi; }
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISACORE_BIN="${ELISACORE_BIN:-$HOME/.elisac/elisac}"
LLVM_CONFIG="${LLVM_CONFIG:-/opt/homebrew/opt/llvm/bin/llvm-config}"
[ -x "$ELISACORE_BIN" ] || { echo "backend_obj_smoke SKIP: no elisac"; exit 0; }
[ -x "$LLVM_CONFIG" ] || { echo "backend_obj_smoke SKIP: no llvm-config"; exit 0; }
# arm64-only: the driver binds LLVMInitializeAArch64* directly, because
# LLVMInitializeNativeTarget is a `static inline` with no symbol to bind.
[ "$(uname -m)" = "arm64" ] || { echo "backend_obj_smoke SKIP: driver is arm64-only"; exit 0; }

LIBDIR="$("$LLVM_CONFIG" --libdir)"
BUILD="$ROOT/build"; mkdir -p "$BUILD"
RUNTIME_OBJ="$BUILD/runtime/elisacore_runtime.o"
[ -f "$RUNTIME_OBJ" ] || { echo "backend_obj_smoke SKIP: no runtime object"; exit 0; }

"$ELISACORE_BIN" -emit obj -O2 -o "$BUILD/emit_obj.o" "$ROOT/test/breadth/emit_obj.elisa" 2>/dev/null \
  || { echo "backend_obj_smoke FAILED: could not compile emit_obj.elisa"; exit 1; }
clang -o "$BUILD/emit_obj" "$BUILD/emit_obj.o" -L"$LIBDIR" -lLLVM -Wl,-rpath,"$LIBDIR" 2>/dev/null \
  || { echo "backend_obj_smoke FAILED: could not link emit_obj"; exit 1; }

pass=0; total=0
obj_case() {
    local name="$1" src="$2" want="$3"
    total=$((total + 1))
    local dir="$BUILD/obj_$name"; rm -rf "$dir"; mkdir -p "$dir"
    # emit_obj writes stage1_out.o into the CWD, so each case gets its own directory.
    if ! ( cd "$dir" && printf '%b' "$src" | RUN "$BUILD/emit_obj" >/dev/null 2>&1 ); then
        echo "  FAIL obj_$name: emit_obj declined or errored"; return
    fi
    [ -f "$dir/stage1_out.o" ] || { echo "  FAIL obj_$name: no object emitted"; return; }
    clang -o "$dir/prog" "$dir/stage1_out.o" "$RUNTIME_OBJ" 2>/dev/null \
      || { echo "  FAIL obj_$name: link"; return; }
    RUN "$dir/prog"; local got=$?
    if [ "$got" -ne "$want" ]; then echo "  FAIL obj_$name: got $got want $want"; return; fi
    pass=$((pass + 1))
}

obj_case scalar   'def add(a: i64, b: i64) -> i64:\n    return a + b\n\ndef main() -> i64:\n    return add(40, 2)\n' 42
obj_case recursion 'def fact(n: i64) -> i64:\n    return 1 if n <= 1 else n * fact(n - 1)\n\ndef main() -> i64:\n    return fact(5) - 78\n' 42
obj_case darray   'def main() -> i64:\n    xs: mutable darray[i64] = []\n    xs.push(42)\n    return xs[0] can Unsafe.UncheckedIndex\n' 42
obj_case comprehension 'def main() -> i64:\n    xs: darray[i64] = [i for i in 0..<10]\n    return (xs[3] can Unsafe.UncheckedIndex) + 39\n' 42
obj_case struct   'struct P:\n    x: i64\n    y: i64\n\ndef main() -> i64:\n    p: P = P{x: 40, y: 2}\n    return p.x + p.y\n' 42

if [ "$pass" -ne "$total" ]; then echo "backend_obj_smoke FAILED: passed=$pass total=$total"; exit 1; fi
echo "backend_obj_smoke OK: $pass/$total objects emitted by stage1 (no llc)"
