#!/usr/bin/env bash
# Stage1 backend smoke: compile Elisa -> native and assert the program's real BEHAVIOR.
#
# The whole point is that this asserts an EXIT CODE, not "the compiler didn't crash":
# stage1 lexes + parses the source, its own backend drives LLVM-C to build a module, and
# we assemble/link/RUN the result. If any link in that chain is wrong, the exit code is
# wrong.
#
# Build notes (both learned the hard way, see llvm_c.elisa):
#   * `-emit obj` output is self-contained (its only undefined symbols are libc); do NOT
#     also link elisacore_runtime.o or you get duplicate symbols.
#   * `-emit c-archive` MIS-COMPILES this tree — the packed-store analysis fails on the
#     unmodified test/breadth/parse_report.elisa too, so it is a pre-existing stage0 bug,
#     not a backend one. Hence `-emit obj` + clang here.
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISACORE_BIN="${ELISACORE_BIN:-$HOME/.elisac/elisac}"
LLVM_CONFIG="${LLVM_CONFIG:-/opt/homebrew/opt/llvm/bin/llvm-config}"

if [ ! -x "$ELISACORE_BIN" ]; then echo "backend_native_smoke SKIP: no elisac at $ELISACORE_BIN"; exit 0; fi
if [ ! -x "$LLVM_CONFIG" ]; then echo "backend_native_smoke SKIP: no llvm-config at $LLVM_CONFIG"; exit 0; fi

LIBDIR="$("$LLVM_CONFIG" --libdir)"
LLC="$(dirname "$LLVM_CONFIG")/llc"
BUILD="$ROOT/build"
mkdir -p "$BUILD"

# 1. Build the stage1 native emitter (itself an Elisa program).
if ! "$ELISACORE_BIN" -emit obj -O2 -o "$BUILD/emit_native.o" "$ROOT/test/breadth/emit_native.elisa" 2>"$BUILD/emit_native.buildlog"; then
    echo "backend_native_smoke FAILED: could not compile emit_native.elisa"; sed -n '1,10p' "$BUILD/emit_native.buildlog"; exit 1
fi
if ! clang -o "$BUILD/emit_native" "$BUILD/emit_native.o" -L"$LIBDIR" -lLLVM -Wl,-rpath,"$LIBDIR" 2>"$BUILD/emit_native.linklog"; then
    echo "backend_native_smoke FAILED: could not link emit_native"; sed -n '1,10p' "$BUILD/emit_native.linklog"; exit 1
fi

pass=0
total=0

# run_case <name> <elisa-source> <expected-exit-code>
run_case() {
    local name="$1" src="$2" want="$3"
    total=$((total + 1))
    local ll="$BUILD/case_$name.ll" obj="$BUILD/case_$name.o" exe="$BUILD/case_$name"

    if ! printf '%b' "$src" | "$BUILD/emit_native" > "$ll" 2>/dev/null; then
        echo "  FAIL $name: emitter declined (UNSUPPORTED) or errored"; return
    fi
    if ! "$LLC" -filetype=obj "$ll" -o "$obj" 2>/dev/null; then
        echo "  FAIL $name: llc rejected the emitted IR (backend produced invalid module)"; return
    fi
    if ! clang -o "$exe" "$obj" 2>/dev/null; then
        echo "  FAIL $name: link failed"; return
    fi
    "$exe"
    local got=$?
    if [ "$got" -ne "$want" ]; then
        echo "  FAIL $name: exit code $got, want $want"; return
    fi
    pass=$((pass + 1))
}

# The spine's modeled subset: a parameterless `-> i64` returning an int expression.
run_case return_42        'def main() -> i64:\n    return 42\n'   42
run_case return_0         'def main() -> i64:\n    return 0\n'     0
run_case return_7         'def main() -> i64:\n    return 7\n'     7
# Exit codes are taken mod 256 by the shell; 200 stays in range and is not a boundary.
run_case return_200       'def main() -> i64:\n    return 200\n'  200

# Arithmetic. Precedence/grouping are asserted by VALUE (2+3*4 == 14, not 20), so a
# backend that ignored precedence could not pass.
run_case precedence       'def main() -> i64:\n    return 2 + 3 * 4\n'    14
run_case grouping         'def main() -> i64:\n    return (2 + 3) * 4\n'  20
run_case subtraction      'def main() -> i64:\n    return 50 - 8\n'       42
run_case division         'def main() -> i64:\n    return 100 / 7\n'      14
run_case remainder        'def main() -> i64:\n    return 100 % 7\n'       2
run_case unary_minus      'def main() -> i64:\n    return -5 + 47\n'      42

# --- differential against stage0 -----------------------------------------------------
# The strongest oracle available: compile the SAME source with the reference compiler and
# require identical observable behavior. Hardcoding an expected value only checks what we
# guessed; this checks what Elisa actually means. Signed div/rem is where a backend most
# plausibly diverges (sdiv/srem vs udiv/urem), so the corners are the payload here.
diff_case() {
    local name="$1" src="$2"
    total=$((total + 1))
    local ll="$BUILD/diff_$name.ll"

    if ! printf '%b' "$src" | "$BUILD/emit_native" > "$ll" 2>/dev/null; then
        echo "  FAIL diff_$name: stage1 declined to emit"; return
    fi
    "$LLC" -filetype=obj "$ll" -o "$BUILD/diff_$name.o" 2>/dev/null || { echo "  FAIL diff_$name: llc rejected stage1 IR"; return; }
    clang -o "$BUILD/diff_${name}_s1" "$BUILD/diff_$name.o" 2>/dev/null || { echo "  FAIL diff_$name: stage1 link"; return; }
    "$BUILD/diff_${name}_s1"; local got1=$?

    printf '%b' "$src" > "$BUILD/diff_$name.elisa"
    if ! "$ELISACORE_BIN" -emit obj -o "$BUILD/diff_${name}_s0.o" "$BUILD/diff_$name.elisa" 2>/dev/null; then
        echo "  SKIP diff_$name: stage0 could not compile the reference"; total=$((total - 1)); return
    fi
    clang -o "$BUILD/diff_${name}_s0" "$BUILD/diff_${name}_s0.o" 2>/dev/null || { echo "  FAIL diff_$name: stage0 link"; return; }
    "$BUILD/diff_${name}_s0"; local got0=$?

    if [ "$got1" -ne "$got0" ]; then
        echo "  FAIL diff_$name: stage1=$got1 stage0=$got0 (backends disagree)"; return
    fi
    pass=$((pass + 1))
}

diff_case neg_rem     'def main() -> i64:\n    return -7 % 2\n'
diff_case neg_div     'def main() -> i64:\n    return -7 / 2\n'
diff_case rem_neg_rhs 'def main() -> i64:\n    return 7 % -2\n'
diff_case precedence  'def main() -> i64:\n    return 2 + 3 * 4\n'
diff_case div         'def main() -> i64:\n    return 100 / 7\n'

# An UNSUPPORTED input must be DECLINED, never silently mis-emitted. A call is outside
# the modeled subset (no call emission yet), so the emitter must exit 2. Keep this case
# pointed at something genuinely unmodeled as coverage grows.
total=$((total + 1))
printf '%b' 'def g() -> i64:\n    return 1\n\ndef main() -> i64:\n    return g()\n' | "$BUILD/emit_native" >/dev/null 2>&1
if [ $? -eq 2 ]; then
    pass=$((pass + 1))
else
    echo "  FAIL declines_unsupported: emitter did not decline an unmodeled construct"
fi

if [ "$pass" -ne "$total" ]; then
    echo "backend_native_smoke FAILED: passed=$pass total=$total"
    exit 1
fi
echo "backend_native_smoke OK: $pass/$total native compile-and-run checks"
