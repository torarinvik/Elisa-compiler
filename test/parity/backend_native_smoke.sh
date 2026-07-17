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
diff_case generic_explicit  'def identity[T](x: T) -> T:\n    return x\n\ndef main() -> i64:\n    return identity[i64](42)\n'
diff_case generic_two_insts 'def identity[T](x: T) -> T:\n    return x\n\ndef main() -> i64:\n    a: u8 = 200\n    b: i64 = 2\n    return identity[u8](a).i64() - identity[i64](b) - 156\n'
diff_case generic_f64       'def identity[T](x: T) -> T:\n    return x\n\ndef main() -> i64:\n    x: f64 = 42.5\n    return identity(x).i64()\n'
diff_case darray_push  'def main() -> i64:\n    xs: mutable darray[i64] = []\n    xs.push(40)\n    xs.push(2)\n    return xs[0] + xs[1]\n'
diff_case darray_grow  'def main() -> i64:\n    xs: mutable darray[i64] = []\n    for i in 0..<500:\n        xs.push(1)\n    total: mutable i64 = 0\n    for j in 0..<500:\n        total <- total + xs[j]\n    return total - 458\n'
diff_case darray_u8    'def main() -> i64:\n    xs: mutable darray[u8] = []\n    xs.push(200)\n    xs.push(100)\n    return xs[0].i64() - xs[1].i64() - 58\n'
diff_case array_literal 'def main() -> i64:\n    xs: i64[3] = [10, 30, 2]\n    return xs[0] + xs[1] + xs[2]\n'
diff_case array_u8      'def main() -> i64:\n    xs: u8[3] = [200, 100, 50]\n    return xs[0].i64() - xs[1].i64() - xs[2].i64() - 8\n'
diff_case array_rw      'def main() -> i64:\n    xs: mutable i64[5] = [0, 0, 0, 0, 0]\n    for i in 0..<5:\n        xs[i] <- i * 2\n    total: mutable i64 = 0\n    for j in 0..<5:\n        total <- total + xs[j]\n    return total + 22\n'
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
# A generic calling ANOTHER generic is not modeled yet (the worklist drains, but the inner
# call's type does not resolve through the outer instantiation's bindings). Declines.
decline_case generic_chained 'def wrap[T](x: T) -> T:\n    return identity(x)\n\ndef identity[T](x: T) -> T:\n    return x\n\ndef main() -> i64:\n    n: i64 = 42\n    return wrap(n)\n'
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
