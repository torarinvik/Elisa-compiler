#!/usr/bin/env bash
# The full default runtime defines a reserved trace callback already predeclared
# by declare_runtime. Reuse must keep the canonical symbol, link, and run.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
RUNTIME_OBJ="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
LLVM_CONFIG="${LLVM_CONFIG:-$(command -v llvm-config || true)}"
LLVM_NM="${LLVM_NM:-$(command -v llvm-nm || true)}"
if [[ -z "$LLVM_NM" && -n "$LLVM_CONFIG" && -x "$LLVM_CONFIG" ]]; then
    LLVM_BINDIR="$("$LLVM_CONFIG" --bindir)"
    [[ -x "$LLVM_BINDIR/llvm-nm" ]] && LLVM_NM="$LLVM_BINDIR/llvm-nm"
fi
LLVM_NM="${LLVM_NM:-$(command -v nm || true)}"
CLANG="${ELISA_CLANG:-$(command -v clang || true)}"
FIXTURE="$ROOT/test/parity/fixtures/trace_callback_decl_reuse.elisa"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"
[[ -x "$STAGE1" ]] || { echo "trace_callback_decl_reuse FAIL: no stage1 compiler" >&2; exit 1; }
[[ -f "$RUNTIME_OBJ" ]] || { echo "trace_callback_decl_reuse FAIL: no runtime object" >&2; exit 1; }
[[ -x "$LLVM_NM" ]] || { echo "trace_callback_decl_reuse FAIL: no llvm-nm at $LLVM_NM" >&2; exit 1; }
[[ -x "$CLANG" ]] || { echo "trace_callback_decl_reuse FAIL: no clang" >&2; exit 1; }

case "$(uname -s)" in
    Linux) LINK_FLAGS=(-no-pie -Wl,--gc-sections); LINK_LIBS=(-lm) ;;
    Darwin) LINK_FLAGS=(-Wl,-dead_strip); LINK_LIBS=() ;;
    *) echo "trace_callback_decl_reuse FAIL: unsupported host $(uname -s)" >&2; exit 2 ;;
esac

"$CLANG" -c -O2 -o "$WORK/profile_hooks.o" "$ROOT/test/parity/profile_hooks.c"

link_and_run() {
    local label="$1" object="$2"
    "$CLANG" "${LINK_FLAGS[@]}" -o "$WORK/$label" "$object" "$RUNTIME_OBJ" "$WORK/profile_hooks.o" "${LINK_LIBS[@]}"
    "$WORK/$label"
}

# Keep an uninstrumented full-runtime control to ensure ordinary bundled runtime
# definitions retain their existing behavior.
"$STAGE1" -emit obj -O2 -o "$WORK/control.o" "$FIXTURE"
link_and_run control "$WORK/control.o"

# Exercise each instrumentation switch independently. The native driver linker
# currently has a Darwin-only dead-strip option, so emit objects and use the host
# platform linker flags here instead.
for mode in ftrace ftrace-functions; do
    object="$WORK/$mode.o"
    "$STAGE1" -emit obj -O2 "-$mode" -o "$object" "$FIXTURE"
    symbols="$WORK/$mode.symbols"
    "$LLVM_NM" "$object" >"$symbols"
    grep -Eq ' U _?elisa_trace_install_fault_handler$' "$symbols"
    if grep -Eq 'elisa_trace_[[:alnum:]_]+\.[0-9]+' "$symbols"; then
        echo "trace_callback_decl_reuse FAIL: suffixed trace callback symbol in $mode object" >&2
        exit 1
    fi
    if grep -Eq ' [TtWw] _?elisa_trace_(record(_id|_value(_id)?)?|function_(entry|exit)(_id)?|install_fault_handler)$' "$symbols"; then
        echo "trace_callback_decl_reuse FAIL: collector callback definition in $mode object" >&2
        exit 1
    fi
    link_and_run "$mode" "$object"
done
echo "trace_callback_decl_reuse OK: uninstrumented, -ftrace, and -ftrace-functions link/run"
