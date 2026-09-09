#!/usr/bin/env bash
# Rebuild the stage1 DRIVERS (emit_native / emit_obj) and FAIL LOUDLY if stage0 rejects the
# tree. Compiling by hand and eyeballing the output does not work: stage0 prints hundreds of
# warning lines whose text contains "error" (error_out_param, __error_set_family, ...), so a
# `grep error` over the log reports success while the object was never written -- and every
# gate then runs the PREVIOUS binary and reports on code that no longer exists. That happened
# for a whole batch of "verified" results. The only reliable signal is the exit status plus
# the object's mtime.
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$ROOT/../../Go projects/structpy-tree}"
ELISACORE_BIN="${ELISACORE_BIN:-$ELISA_CORE/compiler/bin/elisac}"
LLVM_CONFIG="${LLVM_CONFIG:-/opt/homebrew/opt/llvm/bin/llvm-config}"
LIBDIR="$("$LLVM_CONFIG" --libdir)"
BUILD="$ROOT/build"; mkdir -p "$BUILD"

# The compiler drivers embed the Elisa runtime's callback/varargs ABI and the optional
# profiler hooks.  Those symbols are supplied by a host in normal compiler invocations,
# but a standalone driver must still link them weakly so that resolver and backend smoke
# tests cannot start with null dynamic-lookup call targets or fail at link time.
FALLBACK_OBJ="$BUILD/runtime_fallback.o"
PROFILE_OBJ="$BUILD/profile_hooks.o"
if ! clang -c -fPIC -fno-builtin -O2 -o "$FALLBACK_OBJ" "$ROOT/scripts/pymodule_runtime_fallback.c"; then
    echo "build_drivers FAILED: could not compile runtime fallback" >&2
    exit 1
fi
if ! clang -c -O2 -o "$PROFILE_OBJ" "$ROOT/test/parity/profile_hooks.c"; then
    echo "build_drivers FAILED: could not compile profiler hooks" >&2
    exit 1
fi

status=0
for driver in emit_native emit_obj; do
    log="$BUILD/$driver.buildlog"
    if ! "$ELISACORE_BIN" -emit obj -O2 -o "$BUILD/$driver.o" "$ROOT/test/breadth/$driver.elisa" >"$log" 2>&1; then
        echo "build_drivers FAILED: stage0 rejected $driver.elisa"
        grep -v "warning:" "$log" | head -10 | sed 's/^/    /'
        status=1; continue
    fi
    # -stack_size 512MB (the arm64 ld64 max): these embed src/backend, whose emit_expression
    # recurses once per AST level — see the depth guard in codegen_scope.elisa's
    # expression_type and scripts/elisac_stage1.sh's seed_build for the same flag on the
    # product binary.
    if ! clang -o "$BUILD/$driver" "$BUILD/$driver.o" "$FALLBACK_OBJ" "$PROFILE_OBJ" -L"$LIBDIR" -lLLVM -Wl,-rpath,"$LIBDIR" -Wl,-stack_size,0x20000000 2>>"$log"; then
        echo "build_drivers FAILED: could not link $driver"; status=1; continue
    fi
    echo "build_drivers ok: $driver"
done
exit $status
