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
#
# Every compiled binary runs under a TIMEOUT. A wrong loop does not fail, it HANGS, and an
# untimed gate hangs with it (observed: a stage0-compiled `while` spun at 100% CPU
# forever). A timeout turns that into an ordinary failure.
RUN() {
    if command -v timeout >/dev/null 2>&1; then timeout 10 "$@"; else "$@"; fi
}
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
    RUN "$exe"
    local got=$?
    if [ "$got" -eq 124 ]; then echo "  FAIL $name: TIMED OUT (runaway loop?)"; return; fi
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

# Locals, assignment, control flow, calls.
run_case local            'def main() -> i64:\n    x: i64 = 40\n    return x + 2\n'                                     42
run_case assign           'def main() -> i64:\n    x: mutable i64 = 1\n    x <- 42\n    return x\n'                     42
run_case if_then          'def main() -> i64:\n    x: i64 = 5\n    if x > 3:\n        return 42\n    return 0\n'       42
# Both arms return: the join block is unreachable and must still be terminated.
run_case if_else_both_ret 'def main() -> i64:\n    x: i64 = 1\n    if x > 3:\n        return 0\n    else:\n        return 42\n'  42
# A real loop: sums 1..9 == 45, so an off-by-one or a mis-wired backedge shows up.
run_case while_sum        'def main() -> i64:\n    i: mutable i64 = 0\n    total: mutable i64 = 0\n    while i < 9:\n        i <- i + 1\n        total <- total + i\n    return total\n'  45
run_case call             'def double(n: i64) -> i64:\n    return n * 2\n\ndef main() -> i64:\n    return double(21)\n'  42
# Forward reference: `main` calls a function declared LATER. Passes only because
# emit_module declares every function before emitting any body.
run_case call_forward     'def main() -> i64:\n    return helper(42)\n\ndef helper(n: i64) -> i64:\n    return n\n'      42
run_case recursion        'def fact(n: i64) -> i64:\n    if n <= 1:\n        return 1\n    return n * fact(n - 1)\n\ndef main() -> i64:\n    return fact(5)\n'  120

# for-range loops, break/continue, bitwise, bool.
run_case for_range        'def main() -> i64:\n    total: mutable i64 = 0\n    for i in 0..<10:\n        total <- total + i\n    return total\n'   45
run_case for_inclusive    'def main() -> i64:\n    total: mutable i64 = 0\n    for i in 1..=5:\n        total <- total + i\n    return total\n'     15
# `break if` must leave the loop: without it this would sum 0..99 == 4950.
run_case for_break        'def main() -> i64:\n    total: mutable i64 = 0\n    for i in 0..<100:\n        break if i > 5\n        total <- total + i\n    return total\n'  15
# `continue` must still run the loop STEP — targeting the head instead would hang.
run_case for_continue     'def main() -> i64:\n    total: mutable i64 = 0\n    for i in 0..<10:\n        continue if i % 2 == 0\n        total <- total + i\n    return total\n'  25
run_case nested_for       'def main() -> i64:\n    total: mutable i64 = 0\n    for i in 0..<3:\n        for j in 0..<3:\n            total <- total + 1\n    return total\n'  9
run_case while_true_break 'def main() -> i64:\n    i: mutable i64 = 0\n    while true:\n        i <- i + 1\n        break if i >= 7\n    return i\n'  7
run_case bitwise          'def main() -> i64:\n    a: i64 = 12\n    b: i64 = 10\n    return (a & b) + (a | b) + (a ^ b) + (a << 1) + (a >> 2)\n'  55
run_case bool_local       'def main() -> i64:\n    flag: bool = true\n    if flag:\n        return 42\n    return 0\n'  42

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
    RUN "$BUILD/diff_${name}_s1"; local got1=$?

    printf '%b' "$src" > "$BUILD/diff_$name.elisa"
    if ! "$ELISACORE_BIN" -emit obj -o "$BUILD/diff_${name}_s0.o" "$BUILD/diff_$name.elisa" 2>/dev/null; then
        echo "  SKIP diff_$name: stage0 could not compile the reference"; total=$((total - 1)); return
    fi
    clang -o "$BUILD/diff_${name}_s0" "$BUILD/diff_${name}_s0.o" 2>/dev/null || { echo "  FAIL diff_$name: stage0 link"; return; }
    RUN "$BUILD/diff_${name}_s0"; local got0=$?

    if [ "$got1" -eq 124 ] || [ "$got0" -eq 124 ]; then
        echo "  FAIL diff_$name: TIMED OUT (stage1=$got1 stage0=$got0)"; return
    fi
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
diff_case while_sum   'def main() -> i64:\n    i: mutable i64 = 0\n    total: mutable i64 = 0\n    while i < 9:\n        i <- i + 1\n        total <- total + i\n    return total\n'
diff_case recursion   'def fact(n: i64) -> i64:\n    if n <= 1:\n        return 1\n    return n * fact(n - 1)\n\ndef main() -> i64:\n    return fact(5)\n'
diff_case call_fwd    'def main() -> i64:\n    return helper(42)\n\ndef helper(n: i64) -> i64:\n    return n\n'
diff_case for_range   'def main() -> i64:\n    total: mutable i64 = 0\n    for i in 0..<10:\n        total <- total + i\n    return total\n'
diff_case for_break   'def main() -> i64:\n    total: mutable i64 = 0\n    for i in 0..<100:\n        break if i > 5\n        total <- total + i\n    return total\n'
diff_case for_continue 'def main() -> i64:\n    total: mutable i64 = 0\n    for i in 0..<10:\n        continue if i % 2 == 0\n        total <- total + i\n    return total\n'
diff_case bitwise     'def main() -> i64:\n    a: i64 = 12\n    b: i64 = 10\n    return (a & b) + (a | b) + (a ^ b) + (a << 1) + (a >> 2)\n'
# `>>` must be ARITHMETIC (AShr): -8 >> 1 == -4. A logical shift would give a huge
# positive number, so this pins the signedness choice against the reference compiler.
diff_case ashr_negative 'def main() -> i64:\n    a: i64 = -8\n    return (a >> 1) + 100\n'
diff_case bitnot      'def main() -> i64:\n    a: i64 = 5\n    return ~a + 200\n'

# An UNSUPPORTED input must be DECLINED, never silently mis-emitted.
decline_case() {
    local name="$1" src="$2"
    total=$((total + 1))
    printf '%b' "$src" | "$BUILD/emit_native" >/dev/null 2>&1
    if [ $? -eq 2 ]; then pass=$((pass + 1)); else echo "  FAIL decline_$name: emitter did not decline"; fi
}

# `-> f64` is outside the modeled i64 subset.
decline_case float_return 'def main() -> f64:\n    return 1\n'
# `i = i + 1` is a DECLARATION, not a store: stage0 lowers a bare `name = value` to a fresh
# VarDeclStmt, so in a loop body it declares a shadow and the outer `i` never moves — an
# INFINITE LOOP with no diagnostic (observed). stage1's parser folds `<-` and `=` into the
# same Stmt.Assign, so the backend must reject `=` explicitly rather than emit a store and
# silently disagree with the reference compiler.
decline_case eq_is_not_assign 'def main() -> i64:\n    i: mutable i64 = 0\n    while i < 3:\n        i = i + 1\n    return i\n'
# A `|captures|` annotation on a loop is not modeled.
decline_case loop_captures 'def main() -> i64:\n    i: mutable i64 = 0\n    while i < 3 |i|:\n        i <- i + 1\n    return i\n'
# Iterating a CONTAINER needs the container ABI; only integer ranges are modeled.
decline_case for_over_container 'def main() -> i64:\n    xs: darray[i64] = [1, 2]\n    total: mutable i64 = 0\n    for x in xs:\n        total <- total + x\n    return total\n'
# `break` outside any loop must decline, not branch to nowhere.
decline_case break_outside_loop 'def main() -> i64:\n    break\n    return 0\n'

if [ "$pass" -ne "$total" ]; then
    echo "backend_native_smoke FAILED: passed=$pass total=$total"
    exit 1
fi
echo "backend_native_smoke OK: $pass/$total native compile-and-run checks"
