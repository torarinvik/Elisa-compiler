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

# Extract elisacore_runtime.o from a throwaway c-archive. Emitted programs link against
# it because a darray's backing comes from the Elisa runtime (arena_alloc/realloc/free) —
# the backend is no longer self-contained once containers are in play. Scalar programs
# simply do not reference these symbols, so linking it unconditionally is harmless.
RUNTIME_DIR="$BUILD/runtime"
mkdir -p "$RUNTIME_DIR"
printf 'def main() -> i64:\n    s: mutable darray[u8] = []\n    s.push(1)\n    return s.count.i64() - 1\n' > "$RUNTIME_DIR/probe.elisa"
if "$ELISACORE_BIN" -emit c-archive -o "$RUNTIME_DIR/probe.a" "$RUNTIME_DIR/probe.elisa" 2>/dev/null; then
    ( cd "$RUNTIME_DIR" && ar x probe.a elisacore_runtime.o 2>/dev/null )
fi
RUNTIME_OBJ="$RUNTIME_DIR/elisacore_runtime.o"
if [ ! -f "$RUNTIME_OBJ" ]; then
    echo "backend_native_smoke FAILED: could not extract elisacore_runtime.o"; exit 1
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
    if ! clang -o "$exe" "$obj" "$RUNTIME_OBJ" 2>/dev/null; then
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

# Logical operators, compound assignment, value-if.
run_case and_or_not       'def main() -> i64:\n    a: i64 = 5\n    r: mutable i64 = 0\n    if a > 1 and a < 10:\n        r <- r + 1\n    if a > 100 or a == 5:\n        r <- r + 2\n    if not (a == 9):\n        r <- r + 4\n    return r\n'  7
run_case compound_assign  'def main() -> i64:\n    x: mutable i64 = 10\n    x += 5\n    x -= 2\n    x *= 3\n    return x\n'  39
run_case compound_bitwise 'def main() -> i64:\n    x: mutable i64 = 12\n    x &= 10\n    x |= 5\n    x ^= 1\n    x <<= 2\n    return x\n'  48
run_case value_if         'def main() -> i64:\n    a: i64 = 5\n    return 42 if a > 1 else 7\n'  42
# SHORT-CIRCUIT proof: the right-hand side divides by zero. If `and`/`or` evaluated it
# eagerly the process would die on SIGFPE (136) instead of returning 42, so these two
# cases cannot pass unless the short-circuit is real.
run_case short_circuit_and 'def main() -> i64:\n    a: i64 = 0\n    return 1 if a != 0 and (10 / a) > 0 else 42\n'  42
run_case short_circuit_or  'def main() -> i64:\n    a: i64 = 0\n    return 42 if a == 0 or (10 / a) > 0 else 1\n'  42

# Integer `match`. Arms are an ORDERED compare chain: match_first proves the first
# matching arm wins, not the last.
run_case match_hit        'def classify(n: i64) -> i64:\n    return match n:\n        0: 100\n        1: 42\n        _: 300\n\ndef main() -> i64:\n    return classify(1)\n'  42
run_case match_first      'def classify(n: i64) -> i64:\n    return match n:\n        0: 42\n        1: 200\n        _: 300\n\ndef main() -> i64:\n    return classify(0)\n'  42
run_case match_default    'def classify(n: i64) -> i64:\n    return match n:\n        0: 100\n        _: 42\n\ndef main() -> i64:\n    return classify(99)\n'  42
# A negative literal pattern: the sign must survive parse_int_literal + ConstInt.
run_case match_negative   'def classify(n: i64) -> i64:\n    return match n:\n        -1: 42\n        _: 7\n\ndef main() -> i64:\n    return classify(-1)\n'  42
run_case match_as_value   'def main() -> i64:\n    n: i64 = 2\n    v: i64 = match n:\n        1: 10\n        2: 40\n        _: 0\n    return v + 2\n'  42

# Integer WIDTHS and SIGNEDNESS. These are the cases an i64-only backend gets wrong:
# stage0 lowers unsigned `/` and `>>` to udiv/lshr, and widening follows the SOURCE's
# signedness (zext vs sext).
run_case u8_unsigned_div  'def divide(a: u8, b: u8) -> u8:\n    return a / b\n\ndef main() -> i64:\n    return divide(200, 3).i64()\n'  66
run_case u8_unsigned_shr  'def shift(a: u8) -> u8:\n    return a >> 1\n\ndef main() -> i64:\n    return shift(200).i64()\n'  100
# u8 200 -> i64 must ZERO-extend (200). Sign-extending would give -56.
run_case u8_zero_extend   'def main() -> i64:\n    a: u8 = 200\n    return a.i64()\n'  200
# i8 -56 -> i64 must SIGN-extend (-56, +100 == 44). Zero-extending would give 200.
run_case i8_sign_extend   'def main() -> i64:\n    a: i8 = -56\n    return a.i64() + 100\n'  44
run_case i32_arithmetic   'def main() -> i64:\n    a: i32 = 1000\n    b: i32 = 3\n    c: i32 = a / b\n    return c.i64()\n'  77
# 4000000000 > 100 is TRUE unsigned; read as a signed i32 it is negative and FALSE.
run_case u32_compare      'def main() -> i64:\n    a: u32 = 4000000000\n    return 42 if a > 100 else 7\n'  42

# FLOATS. A different instruction family end to end (fadd/fdiv/fcmp), plus int<->float
# conversion. 7.5+2.0=9.5->9, 7.5/2.0=3.75->3, 7.5*2.0=15 => 27, which also pins that
# float->int TRUNCATES toward zero rather than rounding.
run_case f64_arithmetic   'def main() -> i64:\n    x: f64 = 7.5\n    y: f64 = 2.0\n    a: f64 = x + y\n    b: f64 = x / y\n    c: f64 = x * y\n    return a.i64() + b.i64() + c.i64()\n'  27
run_case f64_from_int     'def main() -> i64:\n    n: i64 = 7\n    x: f64 = n.f64()\n    y: f64 = x / 2.0\n    return y.i64()\n'  3
run_case f64_compare      'def main() -> i64:\n    x: f64 = 1.5\n    return 42 if x < 2.0 else 7\n'  42
run_case f64_negate       'def main() -> i64:\n    x: f64 = 7.5\n    y: f64 = -x\n    return y.i64() + 49\n'  42
run_case f64_params       'def scale(x: f64, k: f64) -> f64:\n    return x * k\n\ndef main() -> i64:\n    return scale(10.5, 4.0).i64()\n'  42
# 7.9 -> 7 proves truncation toward zero (rounding would give 8).
run_case f64_truncates    'def main() -> i64:\n    x: f64 = 7.9\n    return x.i64() + 35\n'  42
# u8 -> f64 must go through uitofp: sitofp would read 200 as -56.
run_case u8_to_f64        'def main() -> i64:\n    a: u8 = 200\n    x: f64 = a.f64()\n    return x.i64()\n'  200
run_case f32_arithmetic   'def main() -> i64:\n    x: f32 = 2.5\n    y: f32 = x * 4.0\n    return y.i64() + 32\n'  42

# STRUCTS: declaration, brace construction, field read.
run_case struct_basic     'struct Point:\n    x: i64\n    y: i64\n\ndef main() -> i64:\n    p: Point = Point{x: 40, y: 2}\n    return p.x + p.y\n'  42
# Mixed field widths/kinds in one layout: u8 + i64 + f64. 200 + 5 + 2 - 165 == 42.
run_case struct_mixed     'struct Rec:\n    a: u8\n    b: i64\n    c: f64\n\ndef main() -> i64:\n    r: Rec = Rec{a: 200, b: 5, c: 2.5}\n    return r.a.i64() + r.b + r.c.i64() - 165\n'  42
# Fields given OUT OF ORDER: construction maps by NAME, not by position. If it mapped
# positionally this would compute 2 + 40 into the wrong slots and misread on load.
run_case struct_field_order 'struct S:\n    first: i64\n    second: i64\n\ndef main() -> i64:\n    s: S = S{second: 2, first: 40}\n    return s.first + s.second\n'  42
# The struct is declared AFTER main: struct types are registered in their own pass before
# any signature is resolved, so declaration order cannot matter.
run_case struct_forward   'def main() -> i64:\n    p: Point = Point{x: 40, y: 2}\n    return p.x + p.y\n\nstruct Point:\n    x: i64\n    y: i64\n'  42
run_case struct_in_cond   'struct P:\n    x: i64\n    y: i64\n\ndef main() -> i64:\n    p: P = P{x: 10, y: 20}\n    return 42 if p.y > p.x else 7\n'  42

# AGGREGATE ABI: structs as parameters and return values.
#
# No explicit sret/byval lowering is needed. Both stage0 and stage1 hand LLVM the struct
# TYPE by value in the signature and let LLVM's own target lowering apply the platform ABI
# (small structs in registers on arm64, larger ones indirect). Since both go through the
# same lowering, they agree by construction — which the differentials below confirm rather
# than assume.
run_case struct_param     'struct Point:\n    x: i64\n    y: i64\n\ndef total(p: Point) -> i64:\n    return p.x + p.y\n\ndef main() -> i64:\n    p: Point = Point{x: 40, y: 2}\n    return total(p)\n'  42
run_case struct_return    'struct Point:\n    x: i64\n    y: i64\n\ndef make(a: i64, b: i64) -> Point:\n    return Point{x: a, y: b}\n\ndef main() -> i64:\n    p: Point = make(40, 2)\n    return p.x + p.y\n'  42
run_case struct_roundtrip 'struct Point:\n    x: i64\n    y: i64\n\ndef total(p: Point) -> i64:\n    return p.x + p.y\n\ndef make(a: i64, b: i64) -> Point:\n    return Point{x: a, y: b}\n\ndef main() -> i64:\n    return total(make(40, 2))\n'  42
# 40 bytes: past the register-passing threshold, so this is the indirect/sret path.
run_case struct_large_abi 'struct Big:\n    a: i64\n    b: i64\n    c: i64\n    d: i64\n    e: i64\n\ndef sum(g: Big) -> i64:\n    return g.a + g.b + g.c + g.d + g.e\n\ndef main() -> i64:\n    g: Big = Big{a: 10, b: 10, c: 10, d: 10, e: 2}\n    return sum(g)\n'  42
# A mixed int/float layout is the case a hand-rolled ABI most easily gets wrong.
run_case struct_mixed_abi 'struct M:\n    a: u8\n    b: f64\n\ndef total(m: M) -> i64:\n    return m.a.i64() + m.b.i64()\n\ndef main() -> i64:\n    return total(M{a: 40, b: 2.5})\n'  42
run_case struct_two_args  'struct P:\n    x: i64\n    y: i64\n\ndef add(a: P, b: P) -> P:\n    return P{x: a.x + b.x, y: a.y + b.y}\n\ndef main() -> i64:\n    r: P = add(P{x: 30, y: 1}, P{x: 10, y: 1})\n    return r.x + r.y\n'  42

# FIXED ARRAYS: `T[N]` types, literals, index read/write.
run_case array_literal    'def main() -> i64:\n    xs: i64[3] = [10, 30, 2]\n    return xs[0] + xs[1] + xs[2]\n'  42
run_case array_assign     'def main() -> i64:\n    xs: mutable i64[3] = [1, 1, 1]\n    xs[0] <- 40\n    xs[1] <- 2\n    xs[2] <- 0\n    return xs[0] + xs[1] + xs[2]\n'  42
# A DYNAMIC index (the loop variable): a constant-only GEP would not compile this.
run_case array_dynamic_index 'def main() -> i64:\n    xs: i64[4] = [10, 10, 20, 2]\n    total: mutable i64 = 0\n    for i in 0..<4:\n        total <- total + xs[i]\n    return total\n'  42
# Element type drives load/store width: u8 elements, not i64.
run_case array_u8         'def main() -> i64:\n    xs: u8[3] = [200, 100, 50]\n    return xs[0].i64() - xs[1].i64() - xs[2].i64() - 8\n'  42
run_case array_f64        'def main() -> i64:\n    xs: f64[2] = [40.5, 1.5]\n    return (xs[0] + xs[1]).i64()\n'  42
# Write then read back through dynamic indices: 0+2+4+6+8 == 20, +22 == 42.
run_case array_write_loop 'def main() -> i64:\n    xs: mutable i64[5] = [0, 0, 0, 0, 0]\n    for i in 0..<5:\n        xs[i] <- i * 2\n    total: mutable i64 = 0\n    for j in 0..<5:\n        total <- total + xs[j]\n    return total + 22\n'  42

# DARRAY — dynamic containers, backed by Elisa's RUNTIME (arena_alloc/realloc/free) and by
# a per-function AUTO REGION. This is the first slice where the backend is not
# self-contained: representation ({ptr items, i64 count, i64 capacity}), Arena layout, the
# 256 initial capacity and the grow rule are all stage0's, read out of its own `-emit llvm`
# output — they are dictated by the shared runtime, not chosen here.
run_case darray_push      'def main() -> i64:\n    xs: mutable darray[i64] = []\n    xs.push(40)\n    xs.push(2)\n    return xs[0] + xs[1]\n'  42
run_case darray_count     'def main() -> i64:\n    xs: mutable darray[i64] = []\n    xs.push(7)\n    xs.push(7)\n    xs.push(7)\n    return xs.count * 14\n'  42
run_case darray_loop      'def main() -> i64:\n    xs: mutable darray[i64] = []\n    for i in 0..<10:\n        xs.push(i)\n    total: mutable i64 = 0\n    for j in 0..<10:\n        total <- total + xs[j]\n    return total - 3\n'  42
run_case darray_u8        'def main() -> i64:\n    xs: mutable darray[u8] = []\n    xs.push(200)\n    xs.push(100)\n    return xs[0].i64() - xs[1].i64() - 58\n'  42
run_case darray_write     'def main() -> i64:\n    xs: mutable darray[i64] = []\n    xs.push(1)\n    xs.push(1)\n    xs[0] <- 40\n    xs[1] <- 2\n    return xs[0] + xs[1]\n'  42
# 500 pushes past the 256 initial capacity: this is the arena_realloc GROW path. A push
# that never grew would pass the smaller cases and fail only here.
run_case darray_grow      'def main() -> i64:\n    xs: mutable darray[i64] = []\n    for i in 0..<500:\n        xs.push(1)\n    total: mutable i64 = 0\n    for j in 0..<500:\n        total <- total + xs[j]\n    return total - 458\n'  42

# GENERICS — monomorphization. The gate for dict/set/user generics.
#
# Generic parameters are NOT on Decl.Func: they live in a FILE-level side table keyed by the
# function's LINE (a row whose line has the high bit set is a BOUND, not a parameter).
# Instantiations are named `identity__i64`, matching stage0's scheme read from its IR.
run_case generic_explicit  'def identity[T](x: T) -> T:\n    return x\n\ndef main() -> i64:\n    return identity[i64](42)\n'  42
run_case generic_inferred  'def identity[T](x: T) -> T:\n    return x\n\ndef main() -> i64:\n    n: i64 = 42\n    return identity(n)\n'  42
# TWO distinct instantiations of one template in one program: identity__u8 returns i8,
# identity__i64 returns i64. Getting this wrong emits `sub i8 %a, i64 %b` — invalid IR.
run_case generic_two_insts 'def identity[T](x: T) -> T:\n    return x\n\ndef main() -> i64:\n    a: u8 = 200\n    b: i64 = 2\n    return identity[u8](a).i64() - identity[i64](b) - 156\n'  42
# One instantiation, called twice: emitted ONCE (a duplicate definition would not link).
run_case generic_reused    'def identity[T](x: T) -> T:\n    return x\n\ndef main() -> i64:\n    a: i64 = 40\n    b: i64 = 2\n    return identity(a) + identity(b)\n'  42
run_case generic_f64       'def identity[T](x: T) -> T:\n    return x\n\ndef main() -> i64:\n    x: f64 = 42.5\n    return identity(x).i64()\n'  42

# NESTED generics — a generic calling a generic. This CRASHED the emitter (SIGTRAP) until
# the cause was found: `structs.binding_names <- []` in a callee does not clear the caller's
# darray, it rebinds the field to callee-region memory that is freed on return. Popping
# instead fixes it. These cases are the regression guard for that.
run_case generic_nested    'def wrap[T](x: T) -> T:\n    return identity(x)\n\ndef identity[T](x: T) -> T:\n    return x\n\ndef main() -> i64:\n    n: i64 = 42\n    return wrap(n)\n'  42
# Three deep: each level instantiates the next while the outer bindings are still live.
run_case generic_nested_3  'def a3[T](x: T) -> T:\n    return a2(x)\n\ndef a2[T](x: T) -> T:\n    return a1(x)\n\ndef a1[T](x: T) -> T:\n    return x\n\ndef main() -> i64:\n    n: i64 = 42\n    return a3(n)\n'  42
# Nested AND two type arguments: wrap__u8 -> identity__u8, wrap__i64 -> identity__i64.
run_case generic_nested_2t 'def wrap[T](x: T) -> T:\n    return identity(x)\n\ndef identity[T](x: T) -> T:\n    return x\n\ndef main() -> i64:\n    a: u8 = 200\n    b: i64 = 2\n    return wrap(a).i64() - wrap(b) - 156\n'  42

# REFERENCES (`T&` / `mutable T&`), field assignment, and `void`.
#
# A reference is just a `ptr` — stage0 lowers `def bump(n: mutable i64&)` to
# `define void @bump(ptr)` and `bump(x)` to `call void @bump(ptr %x)`. That fits: locals are
# already allocas, so passing `&local` IS passing the slot, and no `&` operator is needed at
# the call site — the expected type drives it. Mutability stays a frontend concern.
# In the AST `T&` is a POSTFIX Expr.Unary(Ampersand, T) (the parser tells it from infix
# bitwise-and by looking past the whole `&` run).
run_case ref_read         'struct P:\n    x: i64\n    y: i64\n\ndef total(p: P&) -> i64:\n    return p.x + p.y\n\ndef main() -> i64:\n    p: P = P{x: 40, y: 2}\n    return total(p)\n'  42
# Mutation THROUGH a reference must be visible in the caller — a by-value copy returns 41.
run_case ref_mutate       'struct Counter:\n    value: mutable i64\n\ndef bump(c: mutable Counter&) -> void:\n    c.value <- c.value + 1\n\ndef main() -> i64:\n    c: mutable Counter = Counter{value: 41}\n    bump(c)\n    return c.value\n'  42
# Accumulate through a ref across a loop: 0+1+..+8 == 36, +6 == 42.
run_case ref_accumulate   'struct Acc:\n    total: mutable i64\n\ndef add(a: mutable Acc&, n: i64) -> void:\n    a.total <- a.total + n\n\ndef main() -> i64:\n    a: mutable Acc = Acc{total: 0}\n    for i in 0..<9:\n        add(a, i)\n    return a.total + 6\n'  42
run_case field_assign     'struct P:\n    x: mutable i64\n    y: i64\n\ndef main() -> i64:\n    p: mutable P = P{x: 1, y: 2}\n    p.x <- 40\n    return p.x + p.y\n'  42
# `void`: a bare `return`, a void call in statement position (its result must be UNNAMED —
# LLVM rejects a named void instruction), and a void body running off the end.
run_case void_call        'def noop() -> void:\n    return\n\ndef main() -> i64:\n    noop()\n    return 42\n'  42
run_case void_fallthrough 'struct C:\n    v: mutable i64\n\ndef setit(c: mutable C&) -> void:\n    c.v <- 42\n\ndef main() -> i64:\n    c: mutable C = C{v: 0}\n    setit(c)\n    return c.v\n'  42

# OPTIONALS (`T?`) — `{i1 has_value, T value}`, stage0's layout read from its `-emit llvm`
# (`%Optional__i64 = type { i1, i64 }`). In the AST `T?` is a POSTFIX Expr.Unary(Question, T),
# and `null` is an IDENT named "null", not its own node.
#
# Elisa has no `some(x)`: a payload-typed expression in an optional context IS the optional,
# so the backend wraps implicitly. A value-`if`/`match` is EXCLUDED from that — it threads
# `expected` to its arms, which wrap themselves; wrapping the whole form would push the
# payload type into the arms and reject `42 if flag else null`.
run_case optional_local   'def main() -> i64:\n    v: i64? = 42\n    if v is found:\n        return found\n    return 0\n'  42
run_case optional_null    'def main() -> i64:\n    v: i64? = null\n    if v is found:\n        return found\n    return 42\n'  42
# An optional RETURN with mixed value/null arms — the case that breaks a naive wrap.
run_case optional_return  'def pick(flag: bool) -> i64?:\n    return 42 if flag else null\n\ndef main() -> i64:\n    v: i64? = pick(true)\n    if v is found:\n        return found\n    return 0\n'  42
# The null path of the same function: proves the tag is real, not always-true.
run_case optional_absent  'def pick(flag: bool) -> i64?:\n    return 42 if flag else null\n\ndef main() -> i64:\n    v: i64? = pick(false)\n    if v is found:\n        return found\n    return 42\n'  42
# A non-i64 payload: the wrap must use the payload's own width.
run_case optional_u8      'def main() -> i64:\n    v: u8? = 200\n    if v is found:\n        return found.i64() - 158\n    return 0\n'  42

# --- IR-shape check against stage0 ---------------------------------------------------
# For values whose EXIT CODE cannot observe the difference (a string literal's contents,
# with no `extern strlen` to measure it), assert instead that stage1 emits the same IR LINE
# stage0 does. Weaker than a behavioral differential, so it is used only where behavior is
# genuinely unobservable -- never as a substitute for one.
ir_case() {
    local name="$1" src="$2" pattern="$3"
    total=$((total + 1))
    local ll="$BUILD/ir_$name.ll" s0ll="$BUILD/ir_${name}_s0.ll"
    if ! printf '%b' "$src" | "$BUILD/emit_native" > "$ll" 2>/dev/null; then
        echo "  FAIL ir_$name: stage1 declined"; return
    fi
    printf '%b' "$src" > "$BUILD/ir_$name.elisa"
    if ! "$ELISACORE_BIN" -emit llvm -o "$s0ll" "$BUILD/ir_$name.elisa" 2>/dev/null; then
        echo "  SKIP ir_$name: stage0 rejects this program"; return
    fi
    local got want
    got="$(grep -cE "$pattern" "$ll" 2>/dev/null || true)"
    want="$(grep -cE "$pattern" "$s0ll" 2>/dev/null || true)"
    if [ "$got" -ge 1 ] && [ "$want" -ge 1 ]; then
        pass=$((pass + 1)); echo "  ok       ir_$name: both emit /$pattern/"
    else
        echo "  FAIL ir_$name: stage1=$got stage0=$want for /$pattern/"
    fi
}

# The literal's storage must be a private unnamed_addr [N x i8] with a NUL terminator, and
# it must reach a cstr parameter as a bare `ptr` -- exactly stage0's shape.
ir_case cstr_global_shape 'def main() -> i64:\n    s: cstr = "hi"\n    return 42\n' '^@str = private unnamed_addr constant \[3 x i8\] c"hi\\00"'
ir_case cstr_param_is_ptr 'def take(s: cstr) -> i64:\n    return 42\n\ndef main() -> i64:\n    return take("hi")\n' 'define i64 @take\(ptr'

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
    clang -o "$BUILD/diff_${name}_s1" "$BUILD/diff_$name.o" "$RUNTIME_OBJ" 2>/dev/null || { echo "  FAIL diff_$name: stage1 link"; return; }
    RUN "$BUILD/diff_${name}_s1"; local got1=$?

    # The stage0 reference is built with -emit c-archive, NOT -emit obj: a program that
    # touches the runtime (any struct construction does) leaves `arena_free` undefined in
    # a bare object, and the link fails. That failure used to hit the SKIP path below, so
    # struct cases were silently NEVER compared. A skip that hides a missing comparison is
    # worse than no test.
    printf '%b' "$src" > "$BUILD/diff_$name.elisa"
    if ! "$ELISACORE_BIN" -emit c-archive -o "$BUILD/diff_${name}_s0.a" "$BUILD/diff_$name.elisa" 2>/dev/null; then
        echo "  SKIP diff_$name: stage0 rejects this program (not a backend divergence)"; total=$((total - 1)); return
    fi
    clang -o "$BUILD/diff_${name}_s0" "$BUILD/diff_${name}_s0.a" 2>/dev/null || { echo "  FAIL diff_$name: stage0 link"; return; }
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
diff_case and_or_not  'def main() -> i64:\n    a: i64 = 5\n    r: mutable i64 = 0\n    if a > 1 and a < 10:\n        r <- r + 1\n    if a > 100 or a == 5:\n        r <- r + 2\n    if not (a == 9):\n        r <- r + 4\n    return r\n'
diff_case compound    'def main() -> i64:\n    x: mutable i64 = 10\n    x += 5\n    x -= 2\n    x *= 3\n    return x\n'
diff_case short_circuit 'def main() -> i64:\n    a: i64 = 0\n    return 1 if a != 0 and (10 / a) > 0 else 42\n'
diff_case generic_nested   'def wrap[T](x: T) -> T:\n    return identity(x)\n\ndef identity[T](x: T) -> T:\n    return x\n\ndef main() -> i64:\n    n: i64 = 42\n    return wrap(n)\n'
diff_case generic_nested_2t 'def wrap[T](x: T) -> T:\n    return identity(x)\n\ndef identity[T](x: T) -> T:\n    return x\n\ndef main() -> i64:\n    a: u8 = 200\n    b: i64 = 2\n    return wrap(a).i64() - wrap(b) - 156\n'
diff_case generic_explicit  'def identity[T](x: T) -> T:\n    return x\n\ndef main() -> i64:\n    return identity[i64](42)\n'
diff_case generic_two_insts 'def identity[T](x: T) -> T:\n    return x\n\ndef main() -> i64:\n    a: u8 = 200\n    b: i64 = 2\n    return identity[u8](a).i64() - identity[i64](b) - 156\n'
diff_case generic_f64       'def identity[T](x: T) -> T:\n    return x\n\ndef main() -> i64:\n    x: f64 = 42.5\n    return identity(x).i64()\n'
diff_case darray_push  'def main() -> i64:\n    xs: mutable darray[i64] = []\n    xs.push(40)\n    xs.push(2)\n    return xs[0] + xs[1]\n'
diff_case darray_grow  'def main() -> i64:\n    xs: mutable darray[i64] = []\n    for i in 0..<500:\n        xs.push(1)\n    total: mutable i64 = 0\n    for j in 0..<500:\n        total <- total + xs[j]\n    return total - 458\n'
diff_case darray_u8    'def main() -> i64:\n    xs: mutable darray[u8] = []\n    xs.push(200)\n    xs.push(100)\n    return xs[0].i64() - xs[1].i64() - 58\n'
diff_case array_literal 'def main() -> i64:\n    xs: i64[3] = [10, 30, 2]\n    return xs[0] + xs[1] + xs[2]\n'
diff_case array_u8      'def main() -> i64:\n    xs: u8[3] = [200, 100, 50]\n    return xs[0].i64() - xs[1].i64() - xs[2].i64() - 8\n'
diff_case array_rw      'def main() -> i64:\n    xs: mutable i64[5] = [0, 0, 0, 0, 0]\n    for i in 0..<5:\n        xs[i] <- i * 2\n    total: mutable i64 = 0\n    for j in 0..<5:\n        total <- total + xs[j]\n    return total + 22\n'
diff_case optional_return 'def pick(flag: bool) -> i64?:\n    return 42 if flag else null\n\ndef main() -> i64:\n    v: i64? = pick(true)\n    if v is found:\n        return found\n    return 0\n'
diff_case optional_absent 'def pick(flag: bool) -> i64?:\n    return 42 if flag else null\n\ndef main() -> i64:\n    v: i64? = pick(false)\n    if v is found:\n        return found\n    return 42\n'
diff_case optional_u8     'def main() -> i64:\n    v: u8? = 200\n    if v is found:\n        return found.i64() - 158\n    return 0\n'
# A `const enum` IS its backing scalar (stage0 emits `def code(c: Color)` as
# `define i64 @code(i8 %0)`), and a variant is its DECLARATION-ORDER ordinal — `Color.Red`
# in an arm lowers to `icmp eq i8 %c, 0`. Nothing is boxed and there is no tag word.
diff_case enum_match 'const enum Color of u8:\n    Red\n    Green\n    Blue\n\ndef code(c: Color) -> i64:\n    return match c:\n        Color.Red: 1\n        Color.Green: 42\n        _: 3\n\ndef main() -> i64:\n    return code(Color.Green)\n'
diff_case enum_first 'const enum Color of u8:\n    Red\n    Green\n    Blue\n\ndef main() -> i64:\n    return match Color.Red:\n        Color.Red: 42\n        _: 0\n'
diff_case enum_last  'const enum Color of u8:\n    Red\n    Green\n    Blue\n\ndef main() -> i64:\n    return match Color.Blue:\n        Color.Red: 0\n        Color.Green: 1\n        Color.Blue: 42\n'
diff_case enum_local 'const enum Color of u8:\n    Red\n    Green\n    Blue\n\ndef main() -> i64:\n    c: Color = Color.Blue\n    return match c:\n        Color.Blue: 42\n        _: 0\n'
diff_case enum_default 'const enum Color of u8:\n    Red\n    Green\n    Blue\n\ndef code(c: Color) -> i64:\n    return match c:\n        Color.Red: 1\n        _: 42\n\ndef main() -> i64:\n    return code(Color.Blue)\n'
# UFCS: a postfix call unifies casts and UFCS — `p.get()` where `get` is a FUNCTION is
# exactly `get(p)`, while `x.i64()` where the name is a TYPE stays a conversion.
diff_case ufcs_receiver 'struct P:\n    x: i64\n\ndef get(p: P) -> i64:\n    return p.x\n\ndef main() -> i64:\n    p: P = P{x: 42}\n    return p.get()\n'
diff_case ufcs_extra_args 'def add(a: i64, b: i64) -> i64:\n    return a + b\n\ndef main() -> i64:\n    x: i64 = 40\n    return x.add(2)\n'
diff_case ufcs_chained 'def double(n: i64) -> i64:\n    return n * 2\n\ndef main() -> i64:\n    x: i64 = 10\n    return x.double().double() + 2\n'
# The receiver is argument 0, so it is emitted at the PARAMETER's type, not defaulted to
# i64 — a u8 receiver must stay a u8.
diff_case ufcs_u8_receiver 'def widen(b: u8) -> i64:\n    return b.i64()\n\ndef main() -> i64:\n    v: u8 = 200\n    return v.widen() - 158\n'
diff_case ufcs_void 'struct Acc:\n    total: mutable i64\n\ndef bump(a: mutable Acc&) -> void:\n    a.total <- a.total + 42\n\ndef main() -> i64:\n    a: mutable Acc = Acc{total: 0}\n    a.bump()\n    return a.total\n'
# A cast is still a cast, not a UFCS call to a function that happens to be missing.
diff_case ufcs_cast_unaffected 'def main() -> i64:\n    a: u8 = 200\n    return a.i64() - 158\n'
# A `type` alias is a NAME for an existing type with no representation of its own, so it
# resolves to the target and disappears. (`alias` is the EFFECT keyword, not this.)
diff_case type_alias_return 'type Num = i64\n\ndef main() -> Num:\n    return 42\n'
# An alias may name another alias, but only one already DECLARED: resolution is a single
# in-order pass because stage0 rejects a forward reference ("unknown type B").
diff_case type_alias_chain 'type B = i64\ntype A = B\n\ndef main() -> A:\n    return 42\n'
diff_case type_alias_struct 'struct P:\n    x: i64\n\ntype Pt = P\n\ndef main() -> i64:\n    p: Pt = Pt{x: 42}\n    return p.x\n'
# The alias carries the target's WIDTH and SIGNEDNESS: a u8 alias must stay a u8, not
# silently become the i64 default.
diff_case type_alias_u8 'type Byte = u8\n\ndef main() -> i64:\n    b: Byte = 200\n    return b.i64() - 158\n'
diff_case type_alias_param 'type Num = i64\n\ndef add(a: Num, b: Num) -> Num:\n    return a + b\n\ndef main() -> i64:\n    return add(40, 2)\n'
# A GLOBAL const is INLINED at its use site — stage0 emits no `@LIMIT` global and no load
# (`LIMIT + NAME.i64()` lowers to `sadd(42, 7)`), so the backend folds it to a value.
diff_case const_basic 'const LIMIT: i64 = 42\n\ndef main() -> i64:\n    return LIMIT\n'
diff_case const_refs_const 'const A: i64 = 40\nconst B: i64 = A + 2\n\ndef main() -> i64:\n    return B\n'
# Consts allow a FORWARD reference (stage0 accepts this) — the exact opposite of `type`
# aliases, which require declaration order. Hence a fixpoint fold here, one pass there.
diff_case const_forward 'const A: i64 = B + 2\nconst B: i64 = 40\n\ndef main() -> i64:\n    return A\n'
# The const carries its declared WIDTH: a u8 const must stay a u8, not the i64 default.
diff_case const_u8 'const B: u8 = 200\n\ndef main() -> i64:\n    return B.i64() - 158\n'
# A LOCAL shadows a global const of the same name.
diff_case const_shadowed_by_local 'const V: i64 = 1\n\ndef main() -> i64:\n    V: i64 = 42\n    return V\n'
diff_case const_in_arithmetic 'const A: i64 = 40\nconst B: i64 = 2\n\ndef main() -> i64:\n    return A + B\n'
# `const A: mutable i64 = 42` is accepted by stage0, so `is_mutable` must not decline.
diff_case const_mutable_global 'const A: mutable i64 = 42\n\ndef main() -> i64:\n    return A\n'
# MODULES. stage0 emits `module M: def fetch()` as `define i64 @M.fetch` — DOT-mangled,
# though the call spelling is `M::fetch()` (`::` parses to Expr.Scope, a node kind distinct
# from Expr.Field, so a qualified call is never confused with UFCS).
diff_case module_call 'module M:\n    def fetch() -> i64:\n        return 42\n\ndef main() -> i64:\n    return M::fetch()\n'
diff_case module_args 'module M:\n    def add(a: i64, b: i64) -> i64:\n        return a + b\n\ndef main() -> i64:\n    return M::add(40, 2)\n'
# A module function and a top-level function may share a NAME — they are keyed on the
# (owner, name) pair, so `M::pick` and `pick` are different functions.
diff_case module_name_collision 'module M:\n    def pick() -> i64:\n        return 40\n\ndef pick() -> i64:\n    return 2\n\ndef main() -> i64:\n    return M::pick() + pick()\n'
diff_case module_two_modules 'module A:\n    def val() -> i64:\n        return 40\n\nmodule B:\n    def val() -> i64:\n        return 2\n\ndef main() -> i64:\n    return A::val() + B::val()\n'
# A module function calling another function in the SAME module still spells the call
# qualified, so the owner must resolve from inside a module body too.
diff_case module_internal_call 'module M:\n    def base() -> i64:\n        return 40\n\n    def total() -> i64:\n        return M::base() + 2\n\ndef main() -> i64:\n    return M::total()\n'
diff_case module_u8_param 'module M:\n    def widen(b: u8) -> i64:\n        return b.i64()\n\ndef main() -> i64:\n    v: u8 = 200\n    return M::widen(v) - 158\n'
# STRING LITERALS. stage0 lowers `"hi"` to `@str = private unnamed_addr constant [3 x i8]
# c"hi\00"` plus a `ptr` to it; a cstr param is `define i64 @take(ptr)`. These fixtures pin
# compile-and-run parity, but note the exit code CANNOT observe the string's contents --
# that needs `extern strlen`, which is blocked on the stage1 AST discarding an extern's
# return type. The `ir_case` below pins the global's actual shape instead.
diff_case cstr_local 'def main() -> i64:\n    s: cstr = "hi"\n    return 42\n'
diff_case cstr_param 'def take(s: cstr) -> i64:\n    return 42\n\ndef main() -> i64:\n    return take("hi")\n'
diff_case cstr_two_literals 'def take(s: cstr) -> i64:\n    return 42\n\ndef main() -> i64:\n    a: cstr = "one"\n    b: cstr = "two"\n    return take(a) - take(b) + 42\n'
diff_case cstr_empty 'def main() -> i64:\n    s: cstr = ""\n    return 42\n'
diff_case cstr_reassign 'def main() -> i64:\n    s: mutable cstr = "a"\n    s <- "b"\n    return 42\n'
diff_case ref_mutate   'struct Counter:\n    value: mutable i64\n\ndef bump(c: mutable Counter&) -> void:\n    c.value <- c.value + 1\n\ndef main() -> i64:\n    c: mutable Counter = Counter{value: 41}\n    bump(c)\n    return c.value\n'
diff_case ref_accumulate 'struct Acc:\n    total: mutable i64\n\ndef add(a: mutable Acc&, n: i64) -> void:\n    a.total <- a.total + n\n\ndef main() -> i64:\n    a: mutable Acc = Acc{total: 0}\n    for i in 0..<9:\n        add(a, i)\n    return a.total + 6\n'
diff_case struct_param 'struct Point:\n    x: i64\n    y: i64\n\ndef total(p: Point) -> i64:\n    return p.x + p.y\n\ndef main() -> i64:\n    p: Point = Point{x: 40, y: 2}\n    return total(p)\n'
diff_case struct_large 'struct Big:\n    a: i64\n    b: i64\n    c: i64\n    d: i64\n    e: i64\n\ndef sum(g: Big) -> i64:\n    return g.a + g.b + g.c + g.d + g.e\n\ndef main() -> i64:\n    g: Big = Big{a: 10, b: 10, c: 10, d: 10, e: 2}\n    return sum(g)\n'
diff_case struct_mixed_abi 'struct M:\n    a: u8\n    b: f64\n\ndef total(m: M) -> i64:\n    return m.a.i64() + m.b.i64()\n\ndef main() -> i64:\n    return total(M{a: 40, b: 2.5})\n'
diff_case struct_two_args 'struct P:\n    x: i64\n    y: i64\n\ndef add(a: P, b: P) -> P:\n    return P{x: a.x + b.x, y: a.y + b.y}\n\ndef main() -> i64:\n    r: P = add(P{x: 30, y: 1}, P{x: 10, y: 1})\n    return r.x + r.y\n'
diff_case struct_basic 'struct Point:\n    x: i64\n    y: i64\n\ndef main() -> i64:\n    p: Point = Point{x: 40, y: 2}\n    return p.x + p.y\n'
diff_case struct_mixed 'struct Rec:\n    a: u8\n    b: i64\n    c: f64\n\ndef main() -> i64:\n    r: Rec = Rec{a: 200, b: 5, c: 2.5}\n    return r.a.i64() + r.b + r.c.i64() - 165\n'
diff_case struct_order 'struct S:\n    first: i64\n    second: i64\n\ndef main() -> i64:\n    s: S = S{second: 2, first: 40}\n    return s.first + s.second\n'
diff_case f64_arith   'def main() -> i64:\n    x: f64 = 7.5\n    y: f64 = 2.0\n    a: f64 = x + y\n    b: f64 = x / y\n    c: f64 = x * y\n    return a.i64() + b.i64() + c.i64()\n'
diff_case f64_trunc   'def main() -> i64:\n    x: f64 = 7.9\n    return x.i64() + 35\n'
diff_case u8_to_f64   'def main() -> i64:\n    a: u8 = 200\n    x: f64 = a.f64()\n    return x.i64()\n'
diff_case f32         'def main() -> i64:\n    x: f32 = 2.5\n    y: f32 = x * 4.0\n    return y.i64() + 32\n'
diff_case u8_div      'def divide(a: u8, b: u8) -> u8:\n    return a / b\n\ndef main() -> i64:\n    return divide(200, 3).i64()\n'
diff_case u8_shr      'def shift(a: u8) -> u8:\n    return a >> 1\n\ndef main() -> i64:\n    return shift(200).i64()\n'
diff_case u8_zext     'def main() -> i64:\n    a: u8 = 200\n    return a.i64()\n'
diff_case i8_sext     'def main() -> i64:\n    a: i8 = -56\n    return a.i64() + 100\n'
diff_case u32_cmp     'def main() -> i64:\n    a: u32 = 4000000000\n    return 42 if a > 100 else 7\n'
diff_case match_chain 'def classify(n: i64) -> i64:\n    return match n:\n        0: 100\n        1: 200\n        -1: 300\n        _: 400\n\ndef main() -> i64:\n    return classify(-1) - classify(0)\n'


# An UNSUPPORTED input must be DECLINED, never silently mis-emitted.
decline_case() {
    local name="$1" src="$2"
    total=$((total + 1))
    printf '%b' "$src" | "$BUILD/emit_native" >/dev/null 2>&1
    if [ $? -eq 2 ]; then pass=$((pass + 1)); else echo "  FAIL decline_$name: emitter did not decline"; fi
}

# `-> f64` is outside the modeled i64 subset.
# Bitwise operators have no float form.
# A NESTED struct field needs the inner layout resolved first; only scalar fields are modeled.
# A literal shorter than the declared extent would leave elements undef.
# A non-empty darray literal would need a push (plus the grow path) per element.
# `dict` is NOT the next container increment — it is gated behind GENERICS.
#
# stage0 does not lower a dict inline the way it does a darray (which needs only the
# arena_alloc/arena_realloc primitives). It calls MONOMORPHIZED std generics —
# `arena_dict_get_mut__i64__i64`, `arena_dict_find_index__i64__i64` — and pulls the std in:
# a three-line dict program emits 102 functions. Supporting dict therefore requires generic
# instantiation plus compiling elisacore_std/collections.elisa (error unions, refs,
# optional-of-ref), not an ABI to mirror. Until then it must DECLINE, not half-emit.
# A `const enum` is exactly its backing scalar, so it is modeled. The two enum forms that
# are NOT scalars must decline rather than silently narrow to an ordinal compare:
# a PAYLOAD-carrying variant is packed-store territory (register_enum skips it), and a
# non-`const` enum is not the backing scalar at all.
decline_case enum_payload_variant 'enum Shape:\n    Circle(r: i64)\n    Square(s: i64)\n\ndef main() -> i64:\n    return match Shape.Circle(1):\n        Shape.Circle: 42\n        _: 0\n'
decline_case enum_not_const 'enum Color of u8:\n    Red\n    Green\n\ndef main() -> i64:\n    return match Color.Red:\n        Color.Red: 42\n        _: 0\n'
# A CYCLIC alias never resolves. Resolution iterates to a fixpoint rather than recursing
# at each mention precisely so this DECLINES instead of recursing forever — a naive
# resolver stack-overflows here.
decline_case type_alias_cycle 'type A = B\ntype B = A\n\ndef main() -> A:\n    return 42\n'
# A FORWARD reference is not a language feature — stage0 rejects it, so stage1 must not
# quietly resolve it and emit code for a program the reference compiler refuses.
decline_case type_alias_forward 'type A = B\ntype B = i64\n\ndef main() -> A:\n    return 42\n'
# stage0 rejects both of these as not "a compile-time value", so stage1 must not fold them.
# The cycle is why folding iterates to a fixpoint instead of substituting the initializer
# expression at each use: substitution would recurse forever here.
decline_case const_cycle 'const A: i64 = B\nconst B: i64 = A\n\ndef main() -> i64:\n    return A\n'
decline_case const_from_call 'def f() -> i64:\n    return 42\n\nconst A: i64 = f()\n\ndef main() -> i64:\n    return A\n'
# A NESTED module (`A::B::get`) nests Scope inside Scope, whose head is not an Ident. One
# owner column cannot express a dotted path, so it declines rather than mangling a wrong
# symbol and silently calling the wrong function.
decline_case nested_module 'module A:\n    module B:\n        def fetch() -> i64:\n            return 42\n\ndef main() -> i64:\n    return A::B::fetch()\n'
# A cstr carries no LENGTH, so `.count`, indexing and comparison need the runtime and are
# not modeled. Emitting a raw GEP for `s[0]` would be an unchecked read past the end.
decline_case cstr_index 'def main() -> i64:\n    s: cstr = "hi"\n    return s[0].i64()\n'
decline_case cstr_count 'def main() -> i64:\n    s: cstr = "hi"\n    return s.count.i64()\n'
# TUPLES are blocked on the stage1 AST, not on the backend. A tuple IS an anonymous struct
# ({ i64, i64 }, GEP by index, passed/returned by value -- stage0's IR), which the existing
# struct machinery already covers. But `Expr.Tuple(elements, line)` stores NO LABELS: the
# parser consumes them and keeps only the element types (parser_expr.elisa ~266, and the
# node's own comment says so). `t.a` needs the label to resolve to index 0, and `t.0` is not
# valid Elisa (it lexes as FLOAT ".0"), so a tuple's fields cannot be read at all. Declining
# is therefore the whole of what the backend can soundly do here.
decline_case tuple_field_access 'def main() -> i64:\n    t: (a: i64, b: i64) = (40, 2)\n    return t.a + t.b\n'
decline_case tuple_return 'def pair() -> (a: i64, b: i64):\n    return (40, 2)\n\ndef main() -> i64:\n    t: (a: i64, b: i64) = pair()\n    return t.a + t.b\n'
decline_case dict_needs_generics 'def main() -> i64:\n    d: mutable dict[i64, i64] = {}\n    return 0\n'
decline_case darray_nonempty_literal 'def main() -> i64:\n    xs: mutable darray[i64] = [1, 2]\n    return xs[0]\n'
decline_case array_short_literal 'def main() -> i64:\n    xs: i64[3] = [1, 2]\n    return xs[0]\n'
decline_case struct_nested 'struct Inner:\n    v: i64\n\nstruct Outer:\n    i: Inner\n\ndef main() -> i64:\n    o: Outer = Outer{i: Inner{v: 42}}\n    return o.i.v\n'
# Construction must name EVERY field: a missing one would silently leave a slot undef.
decline_case struct_partial 'struct P:\n    x: i64\n    y: i64\n\ndef main() -> i64:\n    p: P = P{x: 42}\n    return p.x\n'
decline_case float_bitwise 'def main() -> i64:\n    x: f64 = 2.0\n    y: f64 = x & x\n    return y.i64()\n'
# MIXED WIDTHS have no implicit conversion in the subset: silently extending one side
# would invent semantics the language does not have.
decline_case mixed_widths 'def main() -> i64:\n    a: i32 = 1\n    b: i64 = 2\n    c: i64 = a + b\n    return c\n'
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
# A match GUARD is a second per-arm condition; not modeled. Ignoring it emitted the arm
# unconditionally — a silent MISCOMPILE (stage1 gave 100 where stage0 gives 42), caught by
# this fixture.
decline_case match_guard 'def classify(n: i64) -> i64:\n    return match n:\n        0 if n > 1: 100\n        _: 42\n\ndef main() -> i64:\n    return classify(0)\n'
# A BINDING arm is INVALID Elisa in an integer match — stage0: "top-level integer match arm
# must use an integer literal or _". Treating it as a catch-all made stage1 emit code for a
# program the language rejects.
decline_case match_binding_arm 'def classify(n: i64) -> i64:\n    return match n:\n        0: 100\n        other: other + 2\n\ndef main() -> i64:\n    return classify(40)\n'

if [ "$pass" -ne "$total" ]; then
    echo "backend_native_smoke FAILED: passed=$pass total=$total"
    exit 1
fi
echo "backend_native_smoke OK: $pass/$total native compile-and-run checks"
