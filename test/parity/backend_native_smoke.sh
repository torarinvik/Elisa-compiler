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
# A MISSPELLED or not-yet-defined check helper is `command not found` -- which bash reports
# on stderr and then keeps going, so the check never runs, `total` never increments, and the
# gate still prints OK. That is a gate that silently stops testing. Trap it: any unknown
# command marks the run failed (observed with a `stage1_ir_case` call placed above its own
# definition, which cost two checks with a green result).
command_not_found_handle() { echo "  FAIL: unknown command '$1' -- a check did not run"; helper_missing=1; }
helper_missing=0

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
# `_ = EXPR` — explicit discard of a call result (emit for side effects, drop the value).
run_case discard_call     'def helper(x: i64) -> i64:\n    return x + 1\n\ndef main() -> i64:\n    _ = helper(5)\n    return 42\n'  42
# No-argument lambda `fn() => …` as a first-class value, and CALLING a no-arg fn value
# `f()` — both were declined edge cases (empty arg array). Plain and capturing.
run_case lambda_noarg     'def call(f: fn() -> i64) -> i64:\n    return f()\n\ndef main() -> i64:\n    return call(fn() => 42)\n'  42
run_case lambda_noarg_cap 'def call(f: fn() -> i64) -> i64:\n    return f()\n\ndef main() -> i64:\n    n: i64 = 42\n    return call(fn() => n)\n'  42

# Membership `x in [literal array]` over a numeric element type: an OR-chain of equality
# compares. Asserted by VALUE (hit vs miss), in both a ternary condition and an if-condition,
# and the empty list is constant-false.
run_case in_hit           'def main() -> i64:\n    x: i64 = 3\n    return 42 if x in [1, 2, 3] else 7\n'  42
run_case in_miss          'def main() -> i64:\n    x: i64 = 9\n    return 42 if x in [1, 2, 3] else 7\n'  7
run_case in_empty         'def main() -> i64:\n    x: i64 = 9\n    return 42 if x in [] else 7\n'  7
run_case in_if_stmt       'def main() -> i64:\n    x: i64 = 2\n    if x in [1, 2, 3]:\n        return 42\n    return 7\n'  42
run_case in_expr_elems    'def main() -> i64:\n    x: i64 = 4\n    a: i64 = 2\n    return 1 if x in [a, a + 2, 7] else 0\n'  1

# Fixed-array LOCAL, both spellings stage0 accepts: canonical `T[N]` and explicit
# `array[T, N]`. Declared from a literal, indexed by literal and by variable.
run_case array_tn_local   'def main() -> i64:\n    xs: array[i64, 3] = [10, 42, 30]\n    return xs[1]\n'  42
run_case array_canon_local 'def main() -> i64:\n    xs: i64[3] = [7, 8, 9]\n    return xs[2]\n'  9
run_case array_var_index   'def main() -> i64:\n    xs: array[i64, 4] = [1, 2, 3, 36]\n    i: mutable i64 = 0\n    s: mutable i64 = 0\n    while i < 4:\n        s <- s + xs[i.usize()]\n        i <- i + 1\n    return s\n'  42

# Named tuples: a `(x: T, y: U)` type is a synthesized anonymous struct. Local from a
# literal + `.field` access; from a function's tuple RETURN (which must resolve to the
# SAME synthesized struct as the local — structural memo); and expression-valued fields.
run_case tuple_local_field 'def main() -> i64:\n    r: (x: i64, y: i64) = (3, 42)\n    return r.y\n'  42
run_case tuple_field_x     'def main() -> i64:\n    r: (x: i64, y: i64) = (40, 2)\n    return r.x + 2\n'  42
run_case tuple_from_return 'def swap(a: i64, b: i64) -> (x: i64, y: i64):\n    return (b, a)\n\ndef main() -> i64:\n    r: (x: i64, y: i64) = swap(42, 7)\n    return r.y\n'  42
run_case tuple_expr_fields 'def main() -> i64:\n    a: i64 = 20\n    r: (x: i64, y: i64) = (a, a + 2)\n    return r.x + r.y\n'  42

# Atomics: `atomic[T]` is a std struct `{value:T}`; a call to a std atomic op on an
# `atomic[int]&` (store/load/fetch_add/...) lowers to a REAL LLVM atomic instruction
# (SeqCst), not the plain-field-access function body. Verified by VALUE (single-threaded,
# the atomic instruction still returns the right result). The `struct atomic` + op defs
# stand in for the std here (backend_native_smoke has no std concatenation).
run_case atomic_store_load 'struct atomic[T]:\n    value: mutable T\n\ndef store(s: mutable atomic[i64]&, v: i64) -> void:\n    s.value <- v\n\ndef load(s: atomic[i64]&) -> i64:\n    return s.value\n\ndef main() -> i64:\n    a: mutable atomic[i64] = atomic[i64]{value: 0}\n    store(&a, 42)\n    return load(&a)\n'  42
run_case atomic_fetch_add 'struct atomic[T]:\n    value: mutable T\n\ndef store(s: mutable atomic[i64]&, v: i64) -> void:\n    s.value <- v\n\ndef load(s: atomic[i64]&) -> i64:\n    return s.value\n\ndef fetch_add(s: mutable atomic[i64]&, v: i64) -> i64:\n    return s.value\n\ndef main() -> i64:\n    a: mutable atomic[i64] = atomic[i64]{value: 0}\n    store(&a, 40)\n    fetch_add(&a, 2)\n    return load(&a)\n'  42
run_case atomic_exchange 'struct atomic[T]:\n    value: mutable T\n\ndef exchange(s: mutable atomic[i64]&, v: i64) -> i64:\n    return s.value\n\ndef main() -> i64:\n    a: mutable atomic[i64] = atomic[i64]{value: 42}\n    return exchange(&a, 7)\n'  42

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
run_case struct_partial   'struct Point:\n    x: i64\n    y: i64\n\ndef main() -> i64:\n    p: Point = Point{x: 40}\n    return p.x + p.y + 2\n'  42
run_case struct_positional 'struct Point:\n    x: i64\n    y: i64\n\ndef main() -> i64:\n    p: Point = Point{40, 2}\n    return p.x + p.y\n'  42
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

# GENERIC STRUCTS: `struct Box[T]` monomorphized per type argument (dict prerequisite —
# `dict[K,V]` is the runtime `DynDict[K,V]` template). Construction + field read verify by
# value, so a backend that dropped the type argument could not produce these exits.
run_case generic_struct_basic  'struct Box[T]:\n    value: mutable T\n\ndef main() -> i64:\n    b: mutable Box[i64] = Box[i64]{value: 42}\n    return b.value\n'  42
# Two type parameters, mixed widths: the layout must bind K and T independently.
run_case generic_struct_pair   'struct Pair[K, T]:\n    a: mutable K\n    b: mutable T\n\ndef main() -> i64:\n    p: mutable Pair[i64, i32] = Pair[i64, i32]{a: 40, b: 2}\n    return p.a + p.b.i64()\n'  42
# By-value generic-struct parameter: the instantiation must resolve in a signature too.
run_case generic_struct_param  'struct Box[T]:\n    value: mutable T\n\ndef unwrap(b: Box[i64]) -> i64:\n    return b.value\n\ndef main() -> i64:\n    return unwrap(Box[i64]{value: 42})\n'  42
# Nested generic struct: `Outer[i64]` contains an `Inner[i64]`, each materialized once.
run_case generic_struct_nested 'struct Inner[T]:\n    v: mutable T\n\nstruct Outer[T]:\n    inner: mutable Inner[T]\n\ndef main() -> i64:\n    o: mutable Outer[i64] = Outer[i64]{inner: Inner[i64]{v: 42}}\n    return o.inner.v\n'  42
# One instantiation reused across two locals: emitted ONCE (a duplicate type would still
# link, but the memo is what keeps `Box[i64]` a single type).
run_case generic_struct_reuse  'struct Box[T]:\n    value: mutable T\n\ndef main() -> i64:\n    a: mutable Box[i64] = Box[i64]{value: 40}\n    b: mutable Box[i64] = Box[i64]{value: 2}\n    return a.value + b.value\n'  42
# EMPTY DICT LITERAL `{}`: `dict[K,V]` is the runtime `DynDict[K,V]` template, and `{}` is
# its zero value (null items, 0 count/…). A fresh dict reads count 0. (Full put/get needs the
# std dict generics; this covers the type mapping + literal + field read.)
run_case dict_empty_literal 'struct DynDict[K, T]:\n    items: mutable i64\n    count: mutable usize\n    used: mutable usize\n    capacity: mutable usize\n    arena: mutable i64\n\ndef main() -> i64:\n    d: mutable dict[i64, i64] = {}\n    return d.count.i64() + 42\n'  42
# DICT METHOD DISPATCH: `d.get(k)` / `d.put(k,v)` are SYNTHESIZED calls to the std generics
# `arena_dict_get` / `arena_dict_put_or_panic` (NOT UFCS to a `get`/`put` fn), with the [K,T]
# taken from the receiver's DynDict type and — for the mutating put — the region threaded as
# the LEADING argument. A single-slot hand-written std proves the whole lowering: put writes,
# get reads back through the returned `T&?`.
run_case dict_get_dispatch 'struct Bucket[K, T]:\n    key: mutable K\n    value: mutable T\n    used: mutable u8\n\nstruct DynDict[K, T]:\n    slot: mutable Bucket[K, T]\n    count: mutable usize\n\ndef arena_dict_get[K, T](m: DynDict[K, T]&, key: K) -> T&?:\n    return &m.slot.value if m.slot.used == 1 and m.slot.key == key else null\n\ndef main() -> i64:\n    d: mutable DynDict[i64, i64] = DynDict[i64, i64]{slot: Bucket[i64, i64]{key: 5, value: 42, used: 1}, count: 1}\n    if d.get(5) is v:\n        return v\n    return 0\n'  42
run_case dict_put_get_cycle 'struct Bucket[K, T]:\n    key: mutable K\n    value: mutable T\n    used: mutable u8\n\nstruct DynDict[K, T]:\n    slot: mutable Bucket[K, T]\n    count: mutable usize\n\ndef arena_dict_put_or_panic[K, T](a: mutable Arena&, m: mutable DynDict[K, T]&, key: K, value: T) -> T&?:\n    m.slot.key <- key\n    m.slot.value <- value\n    m.slot.used <- 1\n    return &m.slot.value\n\ndef arena_dict_get[K, T](m: DynDict[K, T]&, key: K) -> T&?:\n    return &m.slot.value if m.slot.used == 1 and m.slot.key == key else null\n\ndef main() -> i64:\n    d: mutable DynDict[i64, i64] = DynDict[i64, i64]{slot: Bucket[i64, i64]{key: 0, value: 0, used: 0}, count: 0}\n    d.put(5, 42)\n    if d.get(5) is v:\n        return v\n    return 0\n'  42
# A ref binding used as an ARITHMETIC operand (`total <- total + a`, the canonical dict
# accumulate loop) — the mixed-width guard must compare the ref TARGET, not the pointer.
run_case dict_get_accumulate 'struct Bucket[K, T]:\n    key: mutable K\n    value: mutable T\n    used: mutable u8\n\nstruct DynDict[K, T]:\n    slot: mutable Bucket[K, T]\n    count: mutable usize\n\ndef arena_dict_get[K, T](m: DynDict[K, T]&, key: K) -> T&?:\n    return &m.slot.value if m.slot.used == 1 and m.slot.key == key else null\n\ndef main() -> i64:\n    d: mutable DynDict[i64, i64] = DynDict[i64, i64]{slot: Bucket[i64, i64]{key: 1, value: 42, used: 1}, count: 1}\n    total: mutable i64 = 0\n    if d.get(1) is a:\n        total <- total + a\n    return total\n'  42
# `void&` / `T&` EXTERN parameter lowers to a pointer (provenance-bearing), not the bare
# referent — a bare `void` argument is invalid IR. Exercised via a real cxx-style memset decl.
run_case extern_ref_param 'extern memset(dest: mutable void&, val: int, n: usize) -> mutable void&\n\ndef main() -> i64:\n    return 42\n'  42

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
run_case darray_literal   'def main() -> i64:\n    xs: darray[i64] = [40, 2, 99]\n    return xs[0] + xs[1]\n'  42
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
# MULTI-TYPE-PARAMETER generics: `f[K, T]` binds two type params independently. The dict
# prerequisite — `arena_dict_put[K, T]` / `arena_dict_get[K, T]`. Returning K vs T proves
# each parameter is tracked, not conflated.
run_case generic_multi_first  'def pick[K, T](a: K, b: T) -> K:\n    return a\n\ndef main() -> i64:\n    return pick[i64, i32](42, 7)\n'  42
run_case generic_multi_second 'def second[K, T](a: K, b: T) -> T:\n    return b\n\ndef main() -> i64:\n    return second[i32, i64](7, 42)\n'  42
# Mixed widths across params: the u8 and i64 arguments must adopt their own parameter type.
run_case generic_multi_widths 'def combine[K, T](a: K, b: T) -> i64:\n    return a.i64() + b.i64()\n\ndef main() -> i64:\n    return combine[u8, i64](40, 2)\n'  42
# Two distinct instantiations of the SAME two-param template must be emitted once each.
run_case generic_multi_two_insts 'def pick[K, T](a: K, b: T) -> K:\n    return a\n\ndef main() -> i64:\n    return pick[i64, i32](40, 1) + pick[i64, u8](2, 3)\n'  42
# `trusted X:` / `can X:` blocks (compile-time trust/effect grants, no runtime lowering),
# `assert` (runtime check like `requires`), and `decreases` (a termination obligation, no
# runtime effect). All three appear in the std dict internals. Verified by VALUE: the body
# still runs / the check passes.
run_case trusted_block 'def main() -> i64:\n    x: mutable i64 = 0\n    trusted Unsafe.AssumeProgress:\n        x <- 42\n    return x\n'  42
run_case assert_holds  'def main() -> i64:\n    x: i64 = 42\n    assert x == 42\n    return x\n'  42
run_case decreases_skip 'def main() -> i64:\n    r: mutable i64 = 5\n    total: mutable i64 = 0\n    while r > 0:\n        decreases r\n        total <- total + r\n        r <- r - 1\n    return total + 27\n'  42
# `ctx_hash_value(key)` — the compiler-emitted hash builtin the runtime dict uses. A scalar
# key zero-extends to u64 and runs ctx_hash_u64 (splitmix64, in elisacore_runtime.o). The hash
# is deterministic, so two hashes of the same key are equal.
run_case ctx_hash_value 'def main() -> i64:\n    k: i64 = 42\n    h1: u64 = ctx_hash_value(k)\n    h2: u64 = ctx_hash_value(k)\n    return 42 if h1 == h2 else 0\n'  42
# INFERENCE by UNIFICATION: a generic whose parameter is `Map[T]&`, called with a
# `Map[i64]` argument, must infer T=i64 (unify the annotation against the arg's
# instantiation) — NOT T=Map[i64] (the whole arg type). The dict `.put`/`.get` machinery:
# infer K,T from the receiver's `dict[K,T]`.
run_case generic_infer_struct 'struct Bucket[T]:\n    value: mutable T\n\nstruct Map[T]:\n    slot: mutable Bucket[T]\n\ndef peek[T](m: Map[T]&, dummy: T) -> T:\n    return m.slot.value\n\ndef main() -> i64:\n    m: mutable Map[i64] = Map[i64]{slot: Bucket[i64]{value: 42}}\n    return peek(m, 0)\n'  42
# Inference PLUS a ref-optional return read through the binding — the whole dict read
# shape: unify K/T, return `&field` as `T&?`, bind and deref.
run_case generic_infer_refopt 'struct Bucket[T]:\n    value: mutable T\n    used: mutable u8\n\nstruct Map[T]:\n    slot: mutable Bucket[T]\n\ndef map_get[T](m: Map[T]&, dummy: T) -> T&?:\n    return &m.slot.value if m.slot.used == 1 else null\n\ndef main() -> i64:\n    m: mutable Map[i64] = Map[i64]{slot: Bucket[i64]{value: 42, used: 1}}\n    if map_get(m, 0) is v:\n        return v\n    return 0\n'  42

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
# EXPLICIT address-of `&place` + a REF used in a value context (auto-deref through the
# pointer). The dict READ path: `arena_dict_get` returns `&bucket.value` as a `T&?`, and
# `if d.get(k) is a: … a …` reads through the bound `mutable T&`.
run_case ref_addr_field   'struct Box:\n    value: mutable i64\n\ndef get_ref(b: Box&) -> i64&:\n    return &b.value\n\ndef main() -> i64:\n    b: mutable Box = Box{value: 42}\n    r: i64& = get_ref(b)\n    return r\n'  42
# Ref-OPTIONAL `T&?`: `&place` when present, `null` when absent, `is` binds the ref.
run_case ref_optional     'struct Box:\n    value: mutable i64\n    used: mutable u8\n\ndef get_ref(b: Box&) -> i64&?:\n    return &b.value if b.used == 1 else null\n\ndef main() -> i64:\n    b: mutable Box = Box{value: 42, used: 1}\n    if get_ref(b) is v:\n        return v\n    return 0\n'  42
# Absent case of a ref-optional: the null branch is taken, so the fallback returns.
run_case ref_optional_absent 'struct Box:\n    value: mutable i64\n    used: mutable u8\n\ndef get_ref(b: Box&) -> i64&?:\n    return &b.value if b.used == 1 else null\n\ndef main() -> i64:\n    b: mutable Box = Box{value: 7, used: 0}\n    if get_ref(b) is v:\n        return v\n    return 42\n'  42
# `opt == null` / `opt != null` — a PRESENCE test on the optional's tag (no binding, unlike
# `is`). The std dict guards `m.items == null` this way. Both the present and absent branch.
run_case opt_eq_null 'struct Box:\n    value: mutable i64\n    used: mutable u8\n\ndef maybe(b: Box&) -> i64&?:\n    return &b.value if b.used == 1 else null\n\ndef main() -> i64:\n    present: mutable Box = Box{value: 10, used: 1}\n    absent: mutable Box = Box{value: 20, used: 0}\n    total: mutable i64 = 0\n    total <- total + 40 if maybe(present) != null else total\n    total <- total + 2 if maybe(absent) == null else total\n    return total\n'  42
# REF-AS-ARRAY-BASE indexing: `items[i]` where `items: Bucket&` is a C-style pointer base
# (GEP by struct stride). How the std walks `DictBucket[K,T]&` rows. `&arr[0]` supplies the
# base as a ref; `items[1].value` reads the second element in place.
run_case ref_index_base 'struct Bucket:\n    value: mutable i64\n\ndef second_value(items: Bucket&) -> i64:\n    return items[1].value\n\ndef main() -> i64:\n    arr: mutable Bucket[3] = [Bucket{value: 10}, Bucket{value: 42}, Bucket{value: 99}]\n    return second_value(&arr[0])\n'  42
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

# An extern returning a POINTER must declare as `ptr`. The `return_type_name` side table
# keeps only the bare head name (`void`), so before the `__extern_return_ptr` annotation
# this lowered to a `void` return and every FFI allocator was undeclarable.
ir_case extern_ptr_return 'extern malloc(n: usize) -> mutable heap void&\n\ndef main() -> i64:\n    p: mutable heap void& = malloc(64)\n    return 42\n' '^declare ptr @malloc\(i64\)'
ir_case extern_optional_ptr_return 'extern malloc(n: usize) -> mutable heap void&?\n\ndef main() -> i64:\n    p: mutable heap void&? = malloc(64)\n    return 42\n' '^declare ptr @malloc\(i64\)'
# (the heap-optional TAG shape is asserted below, once stage1_ir_case is defined)

# --- stage1-only IR assertions -------------------------------------------------------
# The WEAKEST check in this suite, used only where a differential is IMPOSSIBLE rather than
# merely inconvenient. Unlike ir_case (which requires stage0 to emit the same line), this
# asserts stage1's IR alone -- because stage0 does NOT emit the autovec marker into
# `-emit llvm` output at all, at -O0 or -O2 (verified). There is no reference IR to diff
# against, so "both emit it" cannot be the assertion.
#
# The shape itself was still read out of stage0's SOURCE (llvm_autovec_verify.go), not
# invented: `!llvm.loop !{<self>, !{"elisa.autovec.expected", pos, reason}}`.
stage1_ir_case() {
    local name="$1" src="$2" pattern="$3"
    total=$((total + 1))
    local ll="$BUILD/s1ir_$name.ll"
    if ! printf '%b' "$src" | "$BUILD/emit_native" > "$ll" 2>/dev/null; then
        echo "  FAIL s1ir_$name: stage1 declined"; return
    fi
    if grep -qE "$pattern" "$ll"; then
        pass=$((pass + 1))
    else
        echo "  FAIL s1ir_$name: stage1 IR lacks /$pattern/"
    fi
}

# The ABSENCE assertion needs its own helper: `grep -E` has no negative lookahead (that is
# PCRE), so "must not contain" cannot be spelled as a pattern.
stage1_ir_absent_case() {
    local name="$1" src="$2" pattern="$3"
    total=$((total + 1))
    local ll="$BUILD/s1irabs_$name.ll"
    if ! printf '%b' "$src" | "$BUILD/emit_native" > "$ll" 2>/dev/null; then
        echo "  FAIL s1irabs_$name: stage1 declined"; return
    fi
    if grep -qE "$pattern" "$ll"; then
        echo "  FAIL s1irabs_$name: stage1 IR unexpectedly contains /$pattern/"
    else
        pass=$((pass + 1))
    fi
}

# The module's TARGET. Without a datalayout LLVM assumes i64 is 32-BIT ALIGNED, so every
# `store i64` is emitted `align 4` and the loop vectorizer refuses the loop outright. stage0
# sets both; stage1 set NEITHER, which silently cost alignment and vectorization on ALL
# emitted code while every one of the 244 behavioural checks stayed green. Nothing in this
# suite could see it -- stage0's module header is what gave it away.
stage1_ir_case module_datalayout 'def main() -> i64:\n    return 42\n' '^target datalayout = ".+i64:64'

# For a HEAP pointer, null IS the absent case, so the optional's tag must be a real null
# test. A hardcoded `true` tag reports a FAILED allocation as present and hands the program
# a null it believes is real -- unobservable in any exit code that does not allocate.
stage1_ir_case extern_optional_ptr_null_tag 'extern malloc(n: usize) -> mutable heap void&?\n\ndef main() -> i64:\n    p: mutable heap void&? = malloc(64)\n    if p is real:\n        return 7\n    return 3\n' 'icmp ne ptr %call, null'
# An ordinary (never-null) ref keeps the CONSTANT tag -- the null test is for heap pointers
# only, and widening it to all refs would be a silent behavior change.
stage1_ir_case optional_plain_ref_const_tag 'def main() -> i64:\n    v: i64 = 5\n    r: i64&? = &v\n    if r is real:\n        return 7\n    return 3\n' 'store i1 true'
stage1_ir_case module_triple 'def main() -> i64:\n    return 42\n' '^target triple = "arm64'
stage1_ir_absent_case store_not_underaligned 'def main() -> i64:\n    xs: darray[i64] = [i for i in 0..<10]\n    return (xs[0] can Unsafe.UncheckedIndex) + 42\n' 'store i64 %comp.var.value, ptr %comp.var, align 4'

# The `-Wperf` autovec MARKER on a comprehension's latch branch. It rides in the IR so it
# survives inlining, which is what lets a POST-optimization pass identify a build loop that
# was lowered to be vectorizable and then was not -- the entire basis of -Wperf.
stage1_ir_case autovec_marker 'def main() -> i64:\n    xs: darray[i64] = [i for i in 0..<10]\n    return (xs[0] can Unsafe.UncheckedIndex) + 42\n' 'elisa.autovec.expected'
# The self-reference is asserted SEPARATELY because LLVM requires a loop-ID node's operand 0
# to be the node itself, and silently IGNORES a node that is not -- the marker would be
# "present" and useless.
stage1_ir_case autovec_loop_selfref 'def main() -> i64:\n    xs: darray[i64] = [i for i in 0..<10]\n    return (xs[0] can Unsafe.UncheckedIndex) + 42\n' '^!0 = distinct .\{!0, !1\}'
# A plain for-loop is NOT a comprehension build loop and must NOT be tagged: a marker there
# would make -Wperf demand vectorization of a loop the language never promised to vectorize.
stage1_ir_absent_case autovec_not_plain_loop 'def main() -> i64:\n    total: mutable i64 = 0\n    for i in 0..<10:\n        total <- total + i\n    return total - 3\n' 'elisa.autovec.expected'

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
# CROSS-FN REGION THREADING — the first real piece of region polymorphism. A function
# taking a GROWABLE container by reference gets an implicit trailing `ptr` arena parameter
# and grows through THAT, not through its own auto region: stage0 emits
# `def fill(out: mutable darray[i64]&)` as `define void @fill(ptr, ptr)`, grows via
# `arena_alloc(ptr %1, ...)`, and the call site passes the caller's arena. The backing
# belongs to the CALLER, so a callee-local region would free it at return.
diff_case region_fill_via_ref 'def fill(out: mutable darray[i64]&) -> void:\n    out.push(42)\n\ndef main() -> i64:\n    xs: mutable darray[i64] = []\n    fill(xs)\n    return xs[0]\n'
# 500 pushes force REALLOCATION inside the callee, through the caller's arena.
diff_case region_fill_grows 'def fill(out: mutable darray[i64]&, n: i64) -> void:\n    for i in 0..<n:\n        out.push(1)\n\ndef main() -> i64:\n    xs: mutable darray[i64] = []\n    fill(xs, 500)\n    total: mutable i64 = 0\n    for j in 0..<500:\n        total <- total + xs[j]\n    return total - 458\n'
# Reading through a borrowed darray: the param slot holds a POINTER to the caller's header,
# so count/index need one extra load that a local darray does not.
diff_case region_count_via_ref 'def size(xs: darray[i64]&) -> i64:\n    return xs.count.i64()\n\ndef main() -> i64:\n    ys: mutable darray[i64] = []\n    ys.push(1)\n    ys.push(2)\n    return size(ys) + 40\n'
# `can[Unsafe.UncheckedIndex]` is REQUIRED here, and its absence is not a formality: nothing
# bounds a bare `darray[i64]&`, so stage0's unsafe-permission audit rejects `xs[0]` in this
# function while accepting the same index in main, where the count is provable. (The audit
# runs under -emit c-archive but NOT -emit obj, which is why a bare `-emit obj` probe wrongly
# suggests the unguarded form compiles.) The grant is the POSTFIX `can Unsafe.UncheckedIndex`,
# not a signature `can[Unsafe.UncheckedIndex]` -- the bracketed form still fails the audit.
# The checked spelling `get xs[0] else 0` also passes stage0, but stage1 cannot parse it yet:
# `get` is an ungated contextual keyword there (task_66494fc2).
diff_case region_index_via_ref 'def first(xs: darray[i64]&) -> i64:\n    return xs[0] can Unsafe.UncheckedIndex\n\ndef main() -> i64:\n    ys: mutable darray[i64] = []\n    ys.push(42)\n    return first(ys)\n'
# Two levels: main's arena is threaded through outer into inner.
diff_case region_two_levels 'def inner(out: mutable darray[i64]&) -> void:\n    out.push(42)\n\ndef outer(out: mutable darray[i64]&) -> void:\n    inner(out)\n\ndef main() -> i64:\n    xs: mutable darray[i64] = []\n    outer(xs)\n    return xs[0]\n'
# REGION-RETURN INFERENCE. A container RETURN type is the second trigger for the implicit
# trailing arena param: stage0 emits `def build() -> darray[i64]` as
# `define %DynArray__i64 @build(ptr %0)` and allocates the returned darray's backing from
# the CALLER's region, which the caller frees at its own return.
#
# This case is why the trigger matters. Before region-return inference, stage1 EMITTED it
# and the program exited 139 (SIGSEGV) where stage0 returns 42 -- the callee's region was
# freed at return and the caller read the freed backing. It was declined (95915b5) until the
# mechanism existed; now it is a real differential.
diff_case region_return_owned 'def build() -> darray[i64]:\n    xs: mutable darray[i64] = []\n    xs.push(42)\n    return xs\n\ndef main() -> i64:\n    ys: darray[i64] = build()\n    return ys[0]\n'
# The returned container must survive REALLOCATION inside the callee too.
diff_case region_return_grown 'def build(n: i64) -> darray[i64]:\n    xs: mutable darray[i64] = []\n    for i in 0..<n:\n        xs.push(1)\n    return xs\n\ndef main() -> i64:\n    ys: darray[i64] = build(500)\n    total: mutable i64 = 0\n    for j in 0..<500:\n        total <- total + ys[j]\n    return total - 458\n'
# A returned container passed straight into a function that GROWS it: the same region has to
# reach both, or the push reallocates backing the caller still points at.
diff_case region_return_then_fill 'def build() -> darray[i64]:\n    xs: mutable darray[i64] = []\n    xs.push(40)\n    return xs\n\ndef fill(out: mutable darray[i64]&) -> void:\n    out.push(2)\n\ndef main() -> i64:\n    ys: mutable darray[i64] = build()\n    fill(ys)\n    return ys[0] + ys[1]\n'
# `region NAME:` — a NAMED, SCOPED region. stage0 emits `%r = alloca %Arena`, allocates the
# block's containers from it (`arena_alloc(ptr %r, ...)`), and arena_free's it at scope exit.
# This is the form the language actually offers: `Arena` as a user-facing type is REJECTED
# ("internal runtime carrier type ... use region scopes and inferred container regions"), so
# docs/67's `def make(owner: Arena)` spelling is stale.
diff_case region_scope_darray 'def main() -> i64:\n    total: mutable i64 = 0\n    region r:\n        xs: mutable darray[i64] = []\n        xs.push(42)\n        total <- xs[0] can Unsafe.UncheckedIndex\n    return total\n'
diff_case region_scope_grows 'def main() -> i64:\n    total: mutable i64 = 0\n    region r:\n        xs: mutable darray[i64] = []\n        for i in 0..<500:\n            xs.push(1)\n        for j in 0..<500:\n            total <- total + (xs[j] can Unsafe.UncheckedIndex)\n    return total - 458\n'
diff_case region_scope_empty 'def main() -> i64:\n    region r:\n        v: i64 = 1\n    return 42\n'
# A `return` INSIDE a region block must unwind EVERY live owned region, not just the
# innermost: stage0's IR frees `%r` AND the enclosing auto region on that path. RegionStack
# tracks them the way LoopStack tracks enclosing loops, and the unwind runs innermost-first.
# This used to decline (it freed `r` and LEAKED the auto region -- a leak no exit-code
# differential could ever catch).
diff_case region_return_inside 'def main() -> i64:\n    ys: mutable darray[i64] = []\n    ys.push(1)\n    region r:\n        xs: mutable darray[i64] = []\n        xs.push(42)\n        return xs[0] can Unsafe.UncheckedIndex\n'
diff_case region_return_nested 'def main() -> i64:\n    region outer:\n        xs: mutable darray[i64] = []\n        xs.push(40)\n        region inner:\n            ys: mutable darray[i64] = []\n            ys.push(2)\n            return (xs[0] can Unsafe.UncheckedIndex) + (ys[0] can Unsafe.UncheckedIndex)\n'
# PAYLOAD ENUMS as a tagged union. Read from stage0's IR, not guessed: `%Shape = type
# { i32, [1 x i64] }`, the tag is `extractvalue %Shape %sh, 0` compared with `icmp eq i32`
# against the variant's DECLARATION ordinal, and the payload is a GEP to field 1 loaded at
# the variant's own type. Construction is alloca / zeroinitializer / store tag / store
# payload / load.
diff_case penum_first_variant 'enum Shape:\n    Circle(r: i64)\n    Square(s: i64)\n\ndef area(sh: Shape) -> i64:\n    return match sh:\n        Shape.Circle(r): r\n        Shape.Square(s): s * 2\n\ndef main() -> i64:\n    return area(Shape.Circle(42))\n'
# The SECOND variant proves the tag actually dispatches rather than always taking arm one.
diff_case penum_second_variant 'enum Shape:\n    Circle(r: i64)\n    Square(s: i64)\n\ndef area(sh: Shape) -> i64:\n    return match sh:\n        Shape.Circle(r): r\n        Shape.Square(s): s * 2\n\ndef main() -> i64:\n    return area(Shape.Square(21))\n'
diff_case penum_local 'enum Shape:\n    Circle(r: i64)\n\ndef main() -> i64:\n    s: Shape = Shape.Circle(42)\n    return match s:\n        Shape.Circle(r): r\n'
# A u8 payload must be read back at its OWN width, not as the i64 the slot is sized in.
diff_case penum_u8_payload 'enum Box:\n    Small(v: u8)\n\ndef main() -> i64:\n    b: Box = Box.Small(200)\n    return match b:\n        Box.Small(v): v.i64() - 158\n'
# A payload-free variant alongside a payload-carrying one still gets a tag slot, so its
# ordinal stays its declaration index.
diff_case penum_mixed_variants 'enum Opt:\n    None\n    Some(v: i64)\n\ndef read(o: Opt) -> i64:\n    return match o:\n        Opt.None: 0\n        Opt.Some(v): v\n\ndef main() -> i64:\n    return read(Opt.Some(42)) + read(Opt.None)\n'
# A PLAIN (non-const, payload-free) enum is still a tagged union -- every variant just has
# an empty payload. Passing it through a function defeats stage0's constant folding (a
# same-function match folds to `br i1 true` and proves nothing about the representation).
# Note `enum Color of u8:` WITHOUT `const` is a syntax error in stage0 ("expected :, got
# IDENT(of)") -- `of` belongs to const enums only.
diff_case penum_plain_enum 'enum Color:\n    Red\n    Green\n\ndef code(c: Color) -> i64:\n    return match c:\n        Color.Red: 42\n        Color.Green: 0\n\ndef main() -> i64:\n    return code(Color.Red) + code(Color.Green)\n'
diff_case penum_plain_second 'enum Color:\n    Red\n    Green\n\ndef code(c: Color) -> i64:\n    return match c:\n        Color.Red: 0\n        Color.Green: 42\n\ndef main() -> i64:\n    return code(Color.Green)\n'
# `region NAME(capacity):` takes its backing UP FRONT from the runtime
# (`call ptr @new_region_backend(i64 4096, i64 0)`, with `begin` and `end` both starting at
# it) instead of the lazy strategy an auto region uses. The parser captures the capacity as a
# span of the SOURCE text, so it arrives as clause[1] and is parsed back out -- it is not an
# Expr. This is a prerequisite for the packed-enum store, which needs a sized region.
diff_case region_capacity 'def main() -> i64:\n    total: mutable i64 = 0\n    region r(4096):\n        xs: mutable darray[i64] = []\n        xs.push(42)\n        total <- xs[0] can Unsafe.UncheckedIndex\n    return total\n'
# The sized region must still serve REALLOCATION inside the scope.
diff_case region_capacity_grows 'def main() -> i64:\n    total: mutable i64 = 0\n    region r(65536):\n        xs: mutable darray[i64] = []\n        for i in 0..<500:\n            xs.push(1)\n        for j in 0..<500:\n            total <- total + (xs[j] can Unsafe.UncheckedIndex)\n    return total - 458\n'
# `Arena` as a PARAMETER type: the runtime's region carrier, `{ptr, ptr, i64, i64}`, passed
# BY VALUE (stage0: `define i64 @build(%Arena %0)`, `%r1 = load %Arena, ptr %r` at the call
# site). A region's NAME is bound as an Arena local, so `build(r)` resolves through the
# ordinary Ident path and emits that same load with no special case.
#
# Note the asymmetry: `Arena` is legal HERE but rejected as a region ANNOTATION -- a
# `-> darray[i64] @owner` return is "internal runtime carrier type ... not supported in
# user-facing code". Passable, not annotatable. This is prerequisite 2 of 4 for the
# packed-enum store (cab917f).
diff_case arena_param 'def sink(owner: Arena) -> i64:\n    return 42\n\ndef main() -> i64:\n    region r(4096):\n        return sink(r)\n'
# The callee must be able to BUILD in the arena it was handed -- that is the whole point of
# passing one.
# `in owner:` — ACTIVATING an arena. Passing an arena does not make it the allocation
# target: stage0 rejects the push WITHOUT the in-block ("darray push requires an active in
# <arena>: scope"). The arena is BORROWED inside it, so nothing frees it.
diff_case arena_in_scope 'def fill(owner: Arena, out: mutable darray[i64]&) -> void:\n    in owner:\n        out.push(42)\n\ndef main() -> i64:\n    total: mutable i64 = 0\n    region r(4096):\n        xs: mutable darray[i64] = []\n        fill(r, xs)\n        total <- xs[0] can Unsafe.UncheckedIndex\n    return total\n'
# EXTERNS: `extern strlen(s: cstr) -> usize` -> `declare i64 @strlen(ptr)`, no body, symbol
# resolved at link time. Param and return types are bare NAMES, not Exprs -- the params live
# in the File.extern_params SIDE TABLE and the return type is `return_type_name` on the node,
# so both resolve via scalar_type_of_name.
#
# This was BLOCKED: Decl.Extern had no return-type field and the parser threw the `-> usize`
# away (task_d010c4d5). That fix landed, so this is now portable.
#
# These are also the FIRST cstr fixtures whose EXIT CODE observes a string's CONTENTS --
# `strlen("hello") + 37 == 42`. Until now that was unobservable, which is why cstr leaned on
# ir_case (assert the same IR line) instead of behavior.
diff_case extern_strlen 'extern strlen(s: cstr) -> usize\n\ndef main() -> i64:\n    s: cstr = "hello"\n    return strlen(s).i64() + 37\n'
diff_case extern_strlen_literal 'extern strlen(s: cstr) -> usize\n\ndef main() -> i64:\n    return strlen("0123456789").i64() + 32\n'
diff_case extern_strlen_empty 'extern strlen(s: cstr) -> usize\n\ndef main() -> i64:\n    return strlen("").i64() + 42\n'
# Two args, and a return type that is not the i64 default.
diff_case extern_two_args 'extern strncmp(a: cstr, b: cstr, n: usize) -> i32\n\ndef main() -> i64:\n    return strncmp("abc", "abc", 3).i64() + 42\n'
# NAMED-FIELD construction: `Shape.Circle(r: 42)`, which stage0 accepts alongside the
# positional form. The label is checked against the payload field's DECLARED name -- a label
# naming something else is a different program. This is the last of the four prerequisites
# for the packed-enum store (cab917f), where constructors are written `new Node.Leaf(v: 42)`.
diff_case penum_named_field 'enum Shape:\n    Circle(r: i64)\n\ndef main() -> i64:\n    s: Shape = Shape.Circle(r: 42)\n    return match s:\n        Shape.Circle(r): r\n'
diff_case penum_named_field_u8 'enum Box:\n    Small(v: u8)\n\ndef main() -> i64:\n    b: Box = Box.Small(v: 200)\n    return match b:\n        Box.Small(v): v.i64() - 158\n'
# The AoS STORE, first half: `Node.Store(owner)` asks the runtime for its state and
# assembles `{arena, row_bytes, state}` with three insertvalues -- stage0's exact shape,
# `ctx_packed_store_state_new_variant_sparse(ptr %owner, i64 16)`. row_bytes is the
# `{i32,[N x i64]}` handle at i64 alignment: 8 (tag, padded) + 8*words = 16 for one word.
# The store is runtime-call based, not open-coded, which is why this is bindings + calls.
#
# `Node.Store[Local]`'s TYPESTATE is not modeled: [Local] and [Frozen] have the same layout
# and the distinction is enforced by freeze/move, which still decline.
diff_case packed_store_ctor 'packed enum Node:\n    Leaf(v: i64)\n    Tag(t: i64)\n\ndef build(owner: Arena) -> i64:\n    store: Node.Store[Local] = Node.Store(owner)\n    return 42\n\ndef main() -> i64:\n    region r(4096):\n        return build(r)\n'
# The AoS STORE, end to end. A packed enum's value is an i32 store INDEX -- NOT the
# `{i32, [N x i64]}` row. stage0: `%n = alloca i32`, `store i32 %packed.alloc.index`, and the
# match passes that index to `ctx_packed_store_read_variant_sparse_tag(state, index)`; the
# payload comes back via `read_variant_sparse_word(index, state, 1)` (word 0 is the tag).
# The struct is only the ROW LAYOUT, written at alloc time. Getting that backwards would have
# been a silent miscompile -- the IR is what said otherwise.
diff_case packed_store_leaf 'packed enum Node:\n    Leaf(v: i64)\n    Tag(t: i64)\n\ndef build(owner: Arena) -> i64:\n    store: Node.Store[Local] = Node.Store(owner)\n    result: mutable i64 = 0\n    in store:\n        n: Node = new Node.Leaf(v: 42)\n        result <- match n:\n            Node.Leaf(v): v\n            Node.Tag(t): t\n    return result\n\ndef main() -> i64:\n    region r(4096):\n        return build(r)\n'
# The SECOND variant proves the runtime tag actually dispatches.
diff_case packed_store_tag 'packed enum Node:\n    Leaf(v: i64)\n    Tag(t: i64)\n\ndef build(owner: Arena) -> i64:\n    store: Node.Store[Local] = Node.Store(owner)\n    result: mutable i64 = 0\n    in store:\n        n: Node = new Node.Tag(t: 21)\n        result <- match n:\n            Node.Leaf(v): v\n            Node.Tag(t): t * 2\n    return result\n\ndef main() -> i64:\n    region r(4096):\n        return build(r)\n'
# TWO rows in one store: the second allocation must get its own index, not overwrite the first.
diff_case packed_store_two_rows 'packed enum Node:\n    Leaf(v: i64)\n\ndef build(owner: Arena) -> i64:\n    store: Node.Store[Local] = Node.Store(owner)\n    result: mutable i64 = 0\n    in store:\n        a: Node = new Node.Leaf(v: 40)\n        b: Node = new Node.Leaf(v: 2)\n        av: mutable i64 = 0\n        bv: mutable i64 = 0\n        av <- match a:\n            Node.Leaf(v): v\n        bv <- match b:\n            Node.Leaf(v): v\n        result <- av + bv\n    return result\n\ndef main() -> i64:\n    region r(4096):\n        return build(r)\n'
# EFFECTS have NO backend representation. Verified by diffing stage0's own IR: `def risky(n:
# i64) -> i64 can[Abort.Panic]` and the same function WITHOUT the annotation emit byte-
# identical modules (only source_filename differs). Effects are a SEMANTIC feature, enforced
# entirely before codegen -- there is nothing for a backend to port, and these fixtures exist
# to pin that rather than to exercise machinery.
#
# What they DO pin: the annotation must not make the emitter decline a function it would
# otherwise emit, and an `alias` for an effect must not either.
diff_case effect_annotated 'def risky(n: i64) -> i64 can[Abort.Panic]:\n    return n * 2\n\ndef main() -> i64:\n    return risky(21)\n'
diff_case effect_multi 'def f(n: i64) -> i64 can[Abort.Panic, Memory.Allocate]:\n    return n + 1\n\ndef main() -> i64:\n    return f(41)\n'
diff_case effect_alias 'alias MyFx = Abort.Panic\n\ndef f(n: i64) -> i64 can[MyFx]:\n    return n + 1\n\ndef main() -> i64:\n    return f(41)\n'
# LIST COMPREHENSIONS, lowered PRESIZE-AND-FILL the way stage0 does: compute the count,
# allocate the backing once, set count/capacity UP FRONT, then write each element by index.
#
# Deliberately NOT a push loop. A push loop is behaviourally identical and would pass every
# fixture here, but it reallocates as it grows and defeats the vectorizer -- and vectorization
# is the whole point of the construct (`-Wperf`'s autovec verifier tags exactly these loops
# and reports the ones that failed). Emitting the slow shape for a construct that exists to be
# fast is a divergence no exit code can see, which is why the shape is chosen deliberately
# rather than by whatever passes.
diff_case comprehension_range 'def main() -> i64:\n    xs: darray[i64] = [i for i in 0..<10]\n    return (xs[0] can Unsafe.UncheckedIndex) + 42\n'
diff_case comprehension_expr 'def main() -> i64:\n    xs: darray[i64] = [i * 2 for i in 0..<10]\n    return (xs[3] can Unsafe.UncheckedIndex) + 36\n'
# Every element, not just the first: pins that the fill loop covers the whole range and that
# `count` is the element count rather than the capacity.
diff_case comprehension_sum 'def main() -> i64:\n    xs: darray[i64] = [i for i in 0..<10]\n    total: mutable i64 = 0\n    for j in 0..<xs.count:\n        total <- total + (xs[j] can Unsafe.UncheckedIndex)\n    return total - 3\n'
diff_case comprehension_inclusive 'def main() -> i64:\n    xs: darray[i64] = [i for i in 0..=9]\n    return xs.count.i64() + 32\n'
# An EMPTY range must yield an empty darray, not a negative allocation.
diff_case comprehension_empty 'def main() -> i64:\n    xs: darray[i64] = [i for i in 0..<0]\n    return xs.count.i64() + 42\n'
diff_case comprehension_u8 'def main() -> i64:\n    xs: darray[u8] = [200 for i in 0..<3]\n    return (xs[2] can Unsafe.UncheckedIndex).i64() - 158\n'
# `freeze(move store)` — the store's TYPESTATE. Verified against stage0's IR: it adds NO
# runtime call and no instruction, just a copy of the store value. `Store[Local]` ->
# `Store[Frozen]` is enforced by the SEMANTIC checker (same layout, no runtime effect), and
# `freeze` never even reaches the backend -- the parser discards the marker and yields the
# wrapped value. So `move` emits its operand and that is the whole feature.
#
# This retires the caveat on the AoS store (6b800a1), which noted the typestate was unmodeled
# and that this was "sound only because freeze/move decline". They no longer decline, and the
# reason it stays sound is now a verified fact rather than an assumption: there is nothing to
# model.
diff_case packed_freeze 'packed enum Node:\n    Leaf(v: i64)\n    Tag(t: i64)\n\ndef build(owner: Arena) -> i64:\n    store: mutable Node.Store[Local] = Node.Store(owner)\n    result: mutable i64 = 0\n    in store:\n        n: Node = new Node.Leaf(v: 42)\n        result <- match n:\n            Node.Leaf(v): v\n            Node.Tag(t): t\n    frozen: Node.Store[Frozen] = freeze(move store)\n    return result\n\ndef main() -> i64:\n    region r(4096):\n        return build(r)\n'
# `move` on an ordinary value is likewise just the value.
diff_case move_scalar 'def main() -> i64:\n    a: mutable darray[i64] = []\n    a.push(42)\n    b: darray[i64] = move a\n    return b[0] can Unsafe.UncheckedIndex\n'
# `common:` blocks. A shared field promoted across every variant, laid out INLINE between
# the tag and the payload: stage0 emits `%Expr = {i32, i64, [1 x i64]}` (vs `{i32,[1 x i64]}`
# with none), row_bytes 16 -> 24, and BOTH the payload GEP index and the runtime word index
# shift by the common count. The parser prepends commons to each variant's fields; the count
# now reaches the AST (task_bba94cba, filed from this port and landed).
diff_case common_field_int 'packed enum Expr:\n    common:\n        @storage(inline)\n        span: i64\n    Int(value: i64)\n    Tag(t: i64)\n\ndef build(owner: Arena) -> i64:\n    store: Expr.Store[Local] = Expr.Store(owner)\n    result: mutable i64 = 0\n    in store:\n        e: Expr = new Expr.Int(span: 1, value: 42)\n        result <- match e:\n            Expr.Int(value): value\n            Expr.Tag(t): t\n    return result\n\ndef main() -> i64:\n    region r(4096):\n        return build(r)\n'
# The SECOND variant, proving the tag dispatches AND the payload word index (shifted past the
# common) reads the right field.
diff_case common_field_tag 'packed enum Expr:\n    common:\n        @storage(inline)\n        span: i64\n    Int(value: i64)\n    Tag(t: i64)\n\ndef build(owner: Arena) -> i64:\n    store: Expr.Store[Local] = Expr.Store(owner)\n    result: mutable i64 = 0\n    in store:\n        e: Expr = new Expr.Tag(span: 9, t: 21)\n        result <- match e:\n            Expr.Int(value): value\n            Expr.Tag(t): t * 2\n    return result\n\ndef main() -> i64:\n    region r(4096):\n        return build(r)\n'
# ERROR UNIONS (return side). An `error[E]`-returning fn lowers to `i32 @f(ptr out, args)`:
# an i32 code (0=success, ordinal+1=raised) with the T value written through a leading
# out-pointer. `raise E.V` returns `ordinal+1`; `return x` stores x + returns 0. A non-error
# fn consumes the union with `try CALL else FALLBACK` (call, check code==0, pick value or
# fallback). Only `catch` (the handler) is blocked (task_c19cb583); this is everything else.
diff_case error_union_try_else 'error MyErr:\n    Bad\n\ndef risky(n: i64) -> i64 error[MyErr]:\n    raise MyErr.Bad if n > 100\n    return n * 2\n\ndef main() -> i64:\n    ok: i64 = try risky(20) else 0\n    bad: i64 = try risky(200) else 1\n    return ok + bad + 1\n'
# The SUCCESS path alone (no raise reached): the out-param value must come back intact.
diff_case error_union_success 'error E:\n    X\n\ndef doubler(n: i64) -> i64 error[E]:\n    return n * 2\n\ndef main() -> i64:\n    return try doubler(21) else 0\n'
# The RAISE path alone: the fallback must be taken and the value ignored.
diff_case error_union_raise 'error E:\n    X\n    Y\n\ndef fails(n: i64) -> i64 error[E]:\n    raise E.Y\n\ndef main() -> i64:\n    return try fails(5) else 42\n'
# A u8 success value round-trips through the out-param at its own width.
diff_case error_union_u8 'error E:\n    X\n\ndef mk(n: u8) -> u8 error[E]:\n    return n\n\ndef main() -> i64:\n    v: u8 = try mk(200) else 0\n    return v.i64() - 158\n'
# CONTRACTS: `requires PRED` is a precondition, lowered to `if not PRED: abort`. stage0
# emits a predicate check + panic; a provably-true predicate is optimized away. The SUCCESS
# path (predicate holds) is bit-identical to stage0 -- these fixtures exercise that. (A
# provably-FALSE contract is a stage0 COMPILE error -- "argument provably does not satisfy
# requires" -- not a runtime path, so it is not differentiable here.)
diff_case contract_requires 'def half(n: i64) -> i64:\n    requires n >= 0\n    return n / 2\n\ndef main() -> i64:\n    return half(84)\n'
diff_case contract_two_requires 'def add(a: i64, b: i64) -> i64:\n    requires a > 0\n    requires b > 0\n    return a + b\n\ndef main() -> i64:\n    return add(40, 2)\n'
diff_case contract_requires_u8 'def widen(b: u8) -> i64:\n    requires b > 100\n    return b.i64()\n\ndef main() -> i64:\n    return widen(200) - 158\n'
# NESTED STRUCTS: a struct-typed field, its construction, and multi-level reads (`o.i.v`).
# A struct member is just the inner struct's named handle; bodies are set in a pass before
# any use, and LLVM resolves a still-opaque referenced struct once both bodies land -- so
# declaration order is irrelevant (pinned below). Previously declined ("only scalar fields").
diff_case struct_nested_read 'struct Inner:\n    v: i64\nstruct Outer:\n    i: Inner\n\ndef main() -> i64:\n    o: Outer = Outer{i: Inner{v: 42}}\n    return o.i.v\n'
diff_case struct_nested_three 'struct A:\n    n: i64\nstruct B:\n    a: A\nstruct C:\n    b: B\n\ndef main() -> i64:\n    c: C = C{b: B{a: A{n: 42}}}\n    return c.b.a.n\n'
# The inner struct DECLARED AFTER the outer -- forward reference through the named handle.
diff_case struct_nested_declorder 'struct Outer:\n    i: Inner\nstruct Inner:\n    v: i64\n\ndef main() -> i64:\n    o: Outer = Outer{i: Inner{v: 42}}\n    return o.i.v\n'
# A struct with two struct-typed fields, reading a field of each.
diff_case struct_nested_two_fields 'struct P:\n    x: i64\n    y: i64\nstruct Line:\n    start: P\n    stop: P\n\ndef main() -> i64:\n    l: Line = Line{start: P{x: 40, y: 1}, stop: P{x: 1, y: 1}}\n    return l.start.x + l.stop.x + l.start.y\n'
# NESTED FIELD WRITE (`o.i.v <- 42`) and struct ARRAY element field access/write
# (`a[i].x`) -- the read/write paths route through a shared recursive chain-address helper
# that handles a bare Ident, a nested Field, and an array/darray Index receiver.
diff_case nested_field_write 'struct Inner:\n    v: mutable i64\nstruct Outer:\n    i: mutable Inner\n\ndef main() -> i64:\n    o: mutable Outer = Outer{i: Inner{v: 0}}\n    o.i.v <- 42\n    return o.i.v\n'
diff_case array_of_struct_read 'struct P:\n    x: i64\n\ndef main() -> i64:\n    a: P[2] = [P{x: 40}, P{x: 2}]\n    return a[0].x + a[1].x\n'
diff_case array_of_struct_write 'struct P:\n    x: mutable i64\n\ndef main() -> i64:\n    a: mutable P[2] = [P{x: 0}, P{x: 0}]\n    a[0].x <- 40\n    a[1].x <- 2\n    return a[0].x + a[1].x\n'
# A field of a struct-valued RECEIVER with no address -- a call result (`mk().x`) or any
# temporary. Emit the receiver as a value, spill to a temp, then GEP the field.
diff_case call_result_field 'struct P:\n    x: i64\n    y: i64\n\ndef mk() -> P:\n    return P{x: 40, y: 2}\n\ndef main() -> i64:\n    return mk().x + mk().y\n'
# darray-of-STRUCT. The element stride is the struct's ABI size via LLVMSizeOf (the
# datalayout resolves it), not a hardcoded scalar width -- which is what let struct elements
# stop declining at intern time. push stores the struct by value; `a[i].x` addresses the
# element in place.
diff_case darray_of_struct 'struct P:\n    x: i64\n\ndef main() -> i64:\n    a: mutable darray[P] = []\n    a.push(P{x: 42})\n    return a[0].x\n'
# 100 struct pushes force REALLOCATION with the struct stride, then a per-element field sum.
diff_case darray_struct_grow 'struct P:\n    x: i64\n    y: i64\n\ndef main() -> i64:\n    a: mutable darray[P] = []\n    for i in 0..<100:\n        a.push(P{x: i, y: 1})\n    total: mutable i64 = 0\n    for j in 0..<100:\n        total <- total + a[j].x + a[j].y\n    return total - 5008\n'
# A struct COMPREHENSION -- presize-and-fill with a struct element stride.
diff_case comprehension_struct 'struct P:\n    x: i64\n\ndef main() -> i64:\n    a: darray[P] = [P{x: i} for i in 0..<10]\n    return a[3].x + 39\n'
# CONTAINER IN A STRUCT: a darray FIELD (`struct Bag: items: darray[i64]`). push, count,
# and indexed reads all go through the receiver as a struct field -- the darray-op receiver
# resolvers were extended from Ident-only to an Expr form (Ident or struct field), the
# header sitting inline in the struct.
diff_case struct_darray_push_read 'struct Bag:\n    items: mutable darray[i64]\n\ndef main() -> i64:\n    b: mutable Bag = Bag{items: []}\n    b.items.push(42)\n    return b.items[0] can Unsafe.UncheckedIndex\n'
diff_case struct_darray_count 'struct Bag:\n    items: mutable darray[i64]\n\ndef main() -> i64:\n    b: mutable Bag = Bag{items: []}\n    b.items.push(1)\n    b.items.push(2)\n    return b.items.count.i64() + 40\n'
# Growth through a struct field: 100 pushes reallocate the field's backing.
diff_case struct_darray_grow 'struct Bag:\n    items: mutable darray[i64]\n\ndef main() -> i64:\n    b: mutable Bag = Bag{items: []}\n    for i in 0..<100:\n        b.items.push(1)\n    total: mutable i64 = 0\n    for j in 0..<100:\n        total <- total + (b.items[j] can Unsafe.UncheckedIndex)\n    return total - 58\n'
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

# Per-function tolerance: an unmodeled NON-main function is stripped to a bare
# `declare`. If main references it the LINK must fail — the contract is "never a
# silently-wrong binary", not "whole-module decline". Decline also passes.
stripped_case() {
    local name="$1" src="$2"
    total=$((total + 1))
    local ll="$BUILD/stripped_$name.ll" obj="$BUILD/stripped_$name.o" exe="$BUILD/stripped_$name"
    if ! printf '%b' "$src" | "$BUILD/emit_native" > "$ll" 2>/dev/null; then
        pass=$((pass + 1)); return   # declined: fine
    fi
    if ! "$LLC" -filetype=obj "$ll" -o "$obj" 2>/dev/null; then
        pass=$((pass + 1)); return   # invalid IR rejected loudly: fine
    fi
    if clang -o "$exe" "$obj" "$RUNTIME_OBJ" 2>/dev/null; then
        echo "  FAIL stripped_$name: linked a binary despite the unmodeled helper"; return
    fi
    pass=$((pass + 1))
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
# A `const enum` is exactly its backing scalar. A PAYLOAD-carrying enum is a TAGGED UNION
# `{ i32, [N x i64] }` (stage0's `%Shape = type { i32, [1 x i64] }`) -- NOT the AoS packed
# store, which is `packed enum`, a different subsystem. MULTI-FIELD payload variants
# (`Both(i64, i64)`) lay the fields out as a `{T0, T1, …}` tuple in the `[N x i64]` blob
# (N = widest variant's field count): the constructor stores the tuple at the payload ptr and
# a match arm extracts each field -- verified bit-for-bit against stage0's IR + native runs.
run_case enum_multi_field_payload 'enum Pair:\n    Both(a: i64, b: i64)\n\ndef main() -> i64:\n    return match Pair.Both(1, 2):\n        Pair.Both(a, b): a + b\n'   3
run_case enum_multi_field_mixed_width 'enum P:\n    Pt(i32, i64)\n    None\n\ndef f(p: P) -> i64:\n    return match p:\n        P.Pt(a, b): a.i64() + b\n        _: 0\n\ndef main() -> i64:\n    return f(P.Pt(7, 35))\n'   42
run_case enum_multi_field_three 'enum V:\n    A(i64, i64, i64)\n\ndef s(v: V) -> i64:\n    return match v:\n        V.A(x, y, z): x + y + z\n        _: 0\n\ndef main() -> i64:\n    return s(V.A(10, 20, 30))\n'   60
run_case enum_multi_field_stmt_match 'enum Shape:\n    Rect(i64, i64)\n    None\n\ndef f(s: Shape) -> i64:\n    match s:\n        Shape.Rect(w, h):\n            return w * h\n        _:\n            return 0\n\ndef main() -> i64:\n    return f(Shape.Rect(4, 5))\n'   20
# `if EXPR is Enum.Variant(binders…):` narrowing — the tag test is the condition and each
# payload field binds into the then-block (single-field and multi-field).
run_case penum_is_narrow_single 'enum B:\n    V(i64)\n    None\n\ndef main() -> i64:\n    b: B = B.V(42)\n    if b is B.V(n):\n        return n\n    return 0\n'   42
run_case penum_is_narrow_nomatch 'enum B:\n    V(i64)\n    None\n\ndef main() -> i64:\n    b: B = B.None\n    if b is B.V(n):\n        return n\n    return 7\n'   7
run_case penum_is_narrow_multi 'enum Shape:\n    Rect(i64, i64)\n    None\n\ndef main() -> i64:\n    s: Shape = Shape.Rect(4, 5)\n    if s is Shape.Rect(w, h):\n        return w * h\n    return 0\n'   20
# Global const ARRAY: materialized as `@xs = internal constant [N x i64] […]`, indexed by
# GEP at each use (constant and dynamic index; narrower element widths).
run_case const_array_literal_index 'const xs: i64[3] = [10, 20, 30]\n\ndef main() -> i64:\n    return xs[0] + xs[2]\n'   40
run_case const_array_dynamic_index 'const xs: i64[3] = [10, 20, 30]\n\ndef get(i: i64) -> i64:\n    return xs[i]\n\ndef main() -> i64:\n    return get(1)\n'   20
run_case const_array_u8_elem 'const bs: u8[4] = [1, 2, 3, 4]\n\ndef main() -> i64:\n    return bs[3].i64()\n'   4
# Nested const arrays: `i64[2][3]` -> `[3 x [2 x i64]]` (extents inside-out), a recursively
# built constant global, indexed level by level.
run_case const_array_2d_square 'const g: i64[2][2] = [[1, 2], [3, 4]]\n\ndef main() -> i64:\n    return g[0][1] + g[1][1]\n'   6
run_case const_array_2d_asym 'const g: i64[2][3] = [[1, 2], [3, 4], [5, 6]]\n\ndef main() -> i64:\n    return g[2][1]\n'   6
# A const array of CONST-ENUM values: each variant folds to its ordinal, so the global is a
# `[N x i8]` of ordinals (stage0's `@cs = internal constant [2 x i8] c"\00\02"`).
run_case const_array_of_enum 'const enum C of u8:\n    R\n    G\n    B\n\nconst cs: C[2] = [C.R, C.B]\n\ndef main() -> i64:\n    return match cs[1]:\n        C.B: 2\n        _: 0\n'   2

# `static if` branch SELECTION. The parser keeps every branch (a name declared in two
# branches is not a duplicate), so the backend must pick exactly one -- before it did, a
# per-target const was declared once per branch and everything reading one declined.
# POSIX is true on this host, so the elif wins over both the false if and the else.
run_case static_if_selects_branch 'static if ELISA_TARGET_OS_WINDOWS:\n    const PICK: int = 1\nstatic elif ELISA_TARGET_OS_POSIX:\n    const PICK: int = 42\nstatic else:\n    const PICK: int = 3\n\ndef main() -> i64:\n    return PICK.i64()\n' 42
# NESTED selection: the second chain's condition names a const the FIRST chain declared,
# so selection must iterate to a fixpoint. One pass left `BACKEND` unfoldable, fell to the
# else, and compiled the wrong function -- silently, since both branches are valid code.
run_case static_if_nested_const_chain 'const B_MMAP: int = 1\nconst B_MALLOC: int = 2\n\nstatic if ELISA_TARGET_OS_POSIX:\n    const BACKEND: int = B_MMAP\nstatic else:\n    const BACKEND: int = B_MALLOC\n\nstatic if BACKEND == B_MMAP:\n    def pick() -> i64:\n        return 40\nstatic else:\n    def pick() -> i64:\n        return 7\n\ndef main() -> i64:\n    return pick() + 2\n' 42
# A FUNCTION declared in the untaken branch must not shadow or duplicate the taken one.
run_case static_if_untaken_fn_dropped 'static if ELISA_TARGET_OS_WINDOWS:\n    def who() -> i64:\n        return 1\nstatic else:\n    def who() -> i64:\n        return 42\n\ndef main() -> i64:\n    return who()\n' 42
# cstr byte indexing lowers to ctx_string_index(s, i) -> i64 (stage0's shape).
run_case cstr_index_const 'def main() -> i64:\n    s: cstr = "ABC"\n    return s[0].i64() + s[2].i64()\n'   132
run_case cstr_index_dynamic 'def at(s: cstr, i: i64) -> i64:\n    return s[i]\n\ndef main() -> i64:\n    return at("XYZ", 1)\n'   89
# Nested darray[darray[i64]]: elements are 24-byte inner headers; the container's element
# stride must be sizeof(header), not the scalar-fallback 0 that corrupted every push.
run_case darray_nested_index 'def main() -> i64:\n    m: darray[darray[i64]] = [[1, 2], [3, 4]]\n    return m[0][0] + m[0][1] + m[1][0] + m[1][1]\n'   10
run_case darray_nested_uneven 'def main() -> i64:\n    m: darray[darray[i64]] = [[1, 2, 3], [40, 50]]\n    return m[0][2] + m[1][1]\n'   53
run_case darray_nested_count 'def main() -> i64:\n    m: darray[darray[i64]] = [[1, 2, 3], [4]]\n    return m[0].count.i64() + m[1].count.i64()\n'   4
# Payload-enum value equality: compare the tag fields (a payloadless plain enum is this
# {i32,...} representation, and == / != is the one op not already covered by match/ctor).
run_case penum_equality 'enum C:\n    R\n    G\n\ndef same(x: C, y: C) -> i64:\n    return 1 if x == y else 0\n\ndef main() -> i64:\n    return same(C.G, C.G) * 10 + same(C.R, C.G)\n'   10
# `get OPT else FALLBACK`: yield the optional's payload if present, else the fallback.
run_case get_else_absent 'def main() -> i64:\n    x: i64? = null\n    return get x else 42\n'   42
run_case get_else_present 'def find(n: i64) -> i64?:\n    return n if n > 0 else null\n\ndef main() -> i64:\n    return get find(8) else 99\n'   8
# Implicit-void helper (no `-> void`) that mutates THROUGH a `mutable T&` — must be declared
# (previously the whole declaration was gated on a present return type) and assign through the ref.
run_case implicit_void_ref_assign 'def setto(a: mutable i64&, v: i64):\n    a <- v\n\ndef main() -> i64:\n    x: mutable i64 = 3\n    setto(&x, 9)\n    return x\n'   9
run_case implicit_void_field_mut 'struct P:\n    x: mutable i64\n\ndef bump(p: mutable P&):\n    p.x <- p.x + 1\n\ndef main() -> i64:\n    p: mutable P = P{x: 5}\n    bump(&p)\n    return p.x\n'   6
run_case pass_statement 'def note(x: i64):\n    if x < 0:\n        pass\n\ndef main() -> i64:\n    note(5)\n    return 7\n'   7
run_case dstr_count_index 'def main() -> i64:\n    s: dstr = "hello"\n    return s.count.i64() + s[0].i64()\n'   109
run_case dstr_return 'def greet() -> dstr:\n    return "hi there"\n\ndef main() -> i64:\n    s: dstr = greet()\n    return s.count.i64()\n'   8
run_case generic_returns_darray 'def pair[T](a: T, b: T) -> darray[T]:\n    return [a, b]\n\ndef main() -> i64:\n    xs: darray[i64] = pair(10, 20)\n    return xs[0] + xs[1]\n'   30
run_case struct_field_push_through_ref 'struct Bag:\n    items: mutable darray[i64]\n\ndef add(b: mutable Bag&, v: i64):\n    b.items.push(v)\n\ndef main() -> i64:\n    bag: mutable Bag = Bag{items: []}\n    add(&bag, 7)\n    add(&bag, 8)\n    return bag.items[0] + bag.items[1]\n'   15
run_case struct_with_darray_return 'struct Buf:\n    data: darray[i64]\n    tag: i64\n\ndef make(t: i64) -> Buf:\n    return Buf{data: [10, 20, 30], tag: t}\n\ndef main() -> i64:\n    b: Buf = make(5)\n    return b.data[1] + b.tag\n'   25
run_case const_float 'const HALF: f64 = 0.5\n\ndef area(r: f64) -> f64:\n    return HALF * r * r\n\ndef main() -> i64:\n    return area(4.0).i64()\n'   8
run_case const_bool 'const ON: bool = true\nconst OFF: bool = false\n\ndef main() -> i64:\n    return (5 if ON else 0) + (1 if OFF else 2)\n'   7
run_case for_over_field_ref 'struct Bag:\n    items: darray[i64]\n\ndef total(b: Bag&) -> i64:\n    t: mutable i64 = 0\n    for x in b.items |t|:\n        t <- t + x\n    return t\n\ndef main() -> i64:\n    b: Bag = Bag{items: [1, 2, 3]}\n    return total(&b)\n'   6
run_case for_over_borrowed_darray 'def sum(xs: darray[i64]&) -> i64:\n    t: mutable i64 = 0\n    for x in xs |t|:\n        t <- t + x\n    return t\n\ndef main() -> i64:\n    a: darray[i64] = [5, 10, 15]\n    return sum(&a)\n'   30
run_case darray_ref_write 'def fill(xs: mutable darray[i64]&, v: i64):\n    for i in 0..<3 |xs, v|:\n        xs[i] <- v\n\ndef main() -> i64:\n    a: mutable darray[i64] = [0, 0, 0]\n    fill(&a, 9)\n    return a[0] + a[1] + a[2]\n'   27
run_case array_ref_write 'def zero(a: mutable i64[3]&):\n    a[0] <- 0\n    a[1] <- 0\n    a[2] <- 0\n\ndef main() -> i64:\n    arr: mutable i64[3] = [1, 2, 3]\n    zero(&arr)\n    return arr[0] + arr[1] + arr[2]\n'   0
run_case array_ref_read 'def total(a: i64[4]&) -> i64:\n    return a[0] + a[1] + a[2] + a[3]\n\ndef main() -> i64:\n    arr: i64[4] = [1, 2, 3, 4]\n    return total(&arr)\n'   10
run_case try_value_vardecl 'error Bad:\n    Boom\n\ndef inner(x: i64) -> i64 error[Bad]:\n    raise Bad.Boom if x < 0\n    return x\n\ndef outer(x: i64) -> i64 error[Bad]:\n    v: i64 = try inner(x)\n    return v + 1\n\ndef main() -> i64:\n    catch outer(7):\n        ok:\n            return ok\n        error e:\n            return 0\n'   8
# A packed constructor with NO active store declines: stage0 rejects the same program
# ("packed enum constructor Node.Leaf requires an active in Node.Store: scope"), and there
# is no store to allocate the row from anyway.
decline_case packed_enum_needs_store 'packed enum Node:\n    Leaf(v: i64)\n    Tag(t: i64)\n\ndef read(n: Node) -> i64:\n    return match n:\n        Node.Leaf(v): v\n        Node.Tag(t): t\n\ndef main() -> i64:\n    return read(Node.Leaf(42))\n'
# A RECURSIVE enum is AUTO-PROMOTED to packed by stage0 even though it was never declared
# so ("packed enum constructor Node.Leaf requires an active in Node.Store: scope"), and it
# declines here too -- for the independent reason that its payload is not a scalar.
decline_case recursive_enum_is_packed 'enum Node:\n    Leaf(v: i64)\n    Pair(a: Node, b: Node)\n\ndef main() -> i64:\n    n: Node = Node.Leaf(42)\n    return match n:\n        Node.Leaf(v): v\n        Node.Pair(a, b): 0\n'
# A VARIADIC extern needs a different LLVMFunctionType flag and a call site that knows which
# args are fixed; not modeled, so it declines rather than emitting a wrong signature.
# An UNUSED variadic extern no longer poisons the module (per-fn tolerance): the
# program runs. stage0 compiles this program too, so this is parity, not permissiveness.
# `get OPT else return X` — the CONTROL-FLOW recovery form. The parser used to consume the
# else-clause and THROW IT AWAY, which turned this into `v: i64 = find(n)` (a `T?` bound to
# a `T`, early return gone). The recovery is now retained on the node and lowered: present
# unwraps, absent runs the recovery, which terminates. 6*10+7 -- stage0 agrees.
run_case get_else_control_flow 'def find(n: i64) -> i64?:\n    return 5 if n > 0 else null\n\ndef use(n: i64) -> i64:\n    v: i64 = get find(n) else return 7\n    return v + 1\n\ndef main() -> i64:\n    return use(1) * 10 + use(-1)\n' 67
# `assert PATH != null` NARROWS the optional for what follows, so a plain-ref local may be
# initialized from an optional-ref field. stage0 does this and REJECTS the same assignment
# without the assert (verified both ways); the std dict's find/get/put all depend on it.
run_case narrow_optional_ref_by_assert 'struct Node:\n    v: mutable i64\n\nstruct Holder:\n    p: mutable Node&?\n\ndef fetch(h: Holder&) -> i64:\n    assert h.p != null\n    q: Node& = h.p\n    return q.v\n\ndef main() -> i64:\n    n: mutable Node = Node{v: 42}\n    hold: mutable Holder = Holder{p: &n}\n    return fetch(&hold)\n' 42
# An `if` GUARD narrows the same way inside its then-arm, and `and` chains are walked
# (the dict rehash writes `if old_items != null and old_capacity > 0:`).
run_case narrow_optional_ref_by_guard 'struct Node:\n    v: mutable i64\n\nstruct Holder:\n    p: mutable Node&?\n\ndef fetch(h: Holder&, n: i64) -> i64:\n    if h.p != null and n > 0:\n        q: Node& = h.p\n        return q.v\n    return 7\n\ndef main() -> i64:\n    n: mutable Node = Node{v: 42}\n    hold: mutable Holder = Holder{p: &n}\n    return fetch(&hold, 1)\n' 42
# WITHOUT a proof the assignment must still DECLINE -- narrowing is a fact, not a coercion.
stripped_case narrow_optional_ref_unproven 'struct Node:\n    v: mutable i64\n\nstruct Holder:\n    p: mutable Node&?\n\ndef fetch(h: Holder&) -> i64:\n    q: Node& = h.p\n    return q.v\n\ndef main() -> i64:\n    n: mutable Node = Node{v: 42}\n    hold: mutable Holder = Holder{p: &n}\n    return fetch(&hold)\n'
# A const's type ANNOTATION is optional: `const A = 0x20` takes its type from the
# initializer (stage0's default integer type is `int`). The arena writes every
# ELISA_ARENA_PROT_* / MAP_* flag this way, so leaving these Unmodeled declined every
# function that read one.
run_case const_untyped_int 'const MASK = 0x20\nconst SHIFT = 1\n\ndef main() -> i64:\n    return (MASK >> SHIFT) + 26\n' 42
run_case const_untyped_bool 'const DEBUG = false\n\ndef main() -> i64:\n    return 7 if DEBUG else 42\n' 42
# `x.cast[T]` from an INTEGER source is a real reinterpret (`inttoptr`), not a no-op --
# `arena_region_from_uintptr(raw: uintptr)` in the std is exactly this shape.
# Casting to an OPTIONAL pointer target wraps, and the tag comes from a NULL TEST on the
# source: a null raw pointer must read as ABSENT, not as a present-but-null reference.
run_case cast_int_to_pointer_optional '@internal\ndef as_ptr(raw: uintptr) -> mutable heap u8&:\n    trusted Unsafe.PointerCast:\n        return raw.cast[mutable heap u8&]\n\n@internal\ndef maybe(p: heap u8&) -> u8&?:\n    trusted Unsafe.PointerCast:\n        return p.cast[u8&?]\n\ndef main() -> i64:\n    p: mutable heap u8& = as_ptr(0.uintptr())\n    if maybe(p) is q:\n        return 7\n    return 42\n' 42
# `ptr.cast[uintptr]` — the INVERSE reinterpret: a pointer to an INTEGER (`ptrtoint`). Stashing
# a raw address as a scalar `uintptr` (Slice[T]'s `base` field does exactly this). Round-tripped
# ptr -> uintptr -> ptr -> deref recovers the original value, so the exit code is deterministic.
run_case cast_pointer_to_uintptr_roundtrip 'def main() -> i64:\n    x: mutable i64 = 42\n    u: uintptr = (&x).cast[uintptr] can Unsafe.PointerCast\n    p: i64& = u.cast[i64&] can Unsafe.PointerCast\n    return p\n' 42
# `T(x)` — a value CONVERSION in PREFIX form (the canonical spelling alongside postfix
# `x.T()`). A scalar type name applied to one argument converts it: widen (u8->i64), narrow
# (i64->u8, wraps mod 256), and float truncation (f64->i64) all resolve to the same
# emit_conversion the postfix form uses.
run_case convert_prefix_widen  'def main() -> i64:\n    x: u8 = 200\n    return i64(x) - 158\n' 42
run_case convert_prefix_narrow 'def main() -> i64:\n    x: i64 = 300\n    return u8(x).i64() - 2\n' 42
run_case convert_prefix_ftrunc 'def main() -> i64:\n    x: f64 = 42.9\n    return i64(x)\n' 42
run_case unused_variadic_extern 'extern printf(fmt: cstr, ...) -> i32\n\ndef main() -> i64:\n    return 42\n' 42
# A label that is NOT the payload field's declared name must decline rather than be emitted
# as this constructor -- it names a different program.
decline_case penum_wrong_label 'enum Shape:\n    Circle(r: i64)\n\ndef main() -> i64:\n    s: Shape = Shape.Circle(bogus: 42)\n    return match s:\n        Shape.Circle(r): r\n'
# A FILTERED comprehension declines: the output count is not known up front, so the presized
# form does not apply -- and stage0 itself says only the filter-free form auto-vectorizes.
run_case comprehension_filtered 'def main() -> i64:\n    xs: darray[i64] = [i for i in 0..<10 if i > 5]\n    return xs.count.i64()\n' 4
# `ensure` is a POSTCONDITION over `result`. It is checked at every RETURN, which is where
# `result` exists and where stage0 checks it too (stage0 allocates a `%result` slot, stores
# the returned value, then branches per clause). A holding predicate costs nothing after the
# optimizer, so the success path stays bit-comparable.
run_case contract_ensure 'def inc(n: i64) -> i64:\n    ensure result > n\n    return n + 1\n\ndef main() -> i64:\n    return inc(41)\n' 42
# MULTIPLE clauses chain, and the predicate may read parameters as well as `result`.
run_case contract_ensure_multi 'def maxi(a: i64, b: i64) -> i64:\n    ensure result >= a\n    ensure result >= b\n    return a if a > b else b\n\ndef main() -> i64:\n    return maxi(9, 33) + maxi(7, 2)\n' 40
# A `-> void` fn has no `result` to bind: it must DECLINE rather than drop the check --
# an unenforced contract is worse than an unsupported one.
stripped_case contract_ensure_void 'def touch(n: i64) -> void:\n    ensure n > 0\n    return\n\ndef main() -> i64:\n    touch(1)\n    return 42\n'
decline_case dict_needs_generics 'def main() -> i64:\n    d: mutable dict[i64, i64] = {}\n    return 0\n'
run_case darray_nonempty_literal 'def main() -> i64:\n    xs: mutable darray[i64] = [1, 2]\n    return xs[0] + xs[1] + 39\n' 42
run_case for_over_darray 'def main() -> i64:\n    xs: darray[i64] = [1, 2, 3]\n    total: mutable i64 = 0\n    for x in xs:\n        total <- total + x\n    return total + 36\n' 42
run_case comprehension_const_filter 'def main() -> i64:\n    xs: darray[i64] = [i for i in 0..<10 if false]\n    return xs.count + 42\n' 42
run_case array_short_literal 'def main() -> i64:\n    xs: i64[3] = [40, 0]\n    return xs[0] + xs[1] + xs[2] + 2\n' 42
run_case struct_partial 'struct P:\n    x: i64\n    y: i64\n\ndef main() -> i64:\n    p: P = P{x: 40}\n    return p.x + p.y + 2\n' 42
decline_case float_bitwise 'def main() -> i64:\n    x: f64 = 2.0\n    y: f64 = x & x\n    return y.i64()\n'
run_case mixed_widths 'def main() -> i64:\n    a: i32 = 1\n    b: i64 = 2\n    c: i64 = a + b\n    return c\n' 3
run_case mixed_widths_direct 'def main() -> i64:\n    a: i32 = 1\n    b: i64 = 2\n    return a + b\n' 3
# Direct result-context widening is also covered by this mixed-width case.
# `i = i + 1` is a DECLARATION, not a store: stage0 lowers a bare `name = value` to a fresh
# VarDeclStmt, so in a loop body it declares a shadow and the outer `i` never moves — an
# INFINITE LOOP with no diagnostic (observed). stage1's parser folds `<-` and `=` into the
# same Stmt.Assign, so the backend must reject `=` explicitly rather than emit a store and
# silently disagree with the reference compiler.
decline_case eq_is_not_assign 'def main() -> i64:\n    i: mutable i64 = 0\n    while i < 3:\n        i = i + 1\n    return i\n'
# A `|captures|` annotation on a loop is not modeled.
# Capture-listed loops parse as Expr.Block wrapping the loop; in statement position
# the block is just its statements, so these now compile and RUN.
run_case loop_captures 'def main() -> i64:\n    i: mutable i64 = 0\n    while i < 3 |i|:\n        i <- i + 1\n    return i\n' 3
run_case for_captures 'def main() -> i64:\n    total: mutable i64 = 0\n    for i in 0..<10 |total|:\n        total <- total + i\n    return total\n' 45

# Nested fixed arrays: `i64[3][2]` is [2 x [3 x i64]] (extents inside-out), chained
# GEPs per level. Read, write, and loop-driven variable indexing.
run_case nested_array_read 'def main() -> i64:\n    m: i64[2][2] = [[40, 0], [0, 2]]\n    return (m[0][0] can Unsafe.UncheckedIndex) + (m[1][1] can Unsafe.UncheckedIndex)\n' 42
run_case nested_array_write 'def main() -> i64:\n    m: mutable i64[3][2] = [[1, 2, 3], [4, 5, 6]]\n    m[1][2] <- 40 can Unsafe.UncheckedIndex\n    return (m[1][2] can Unsafe.UncheckedIndex) + (m[0][1] can Unsafe.UncheckedIndex)\n' 42
# `catch f():` — the ERROR-fn ABI (i32 status + out-param): code 0 takes the success
# arm (binding the out value), a nonzero code is ordinal+1 and dispatches down the
# error arms; `_` is the catch-all.
# STATEMENT-position `catch f():` (parses to Stmt.Match with the call scrutinee):
# multi-statement arms, `slot:` binds the out value, `error e:` is the catch-all;
# all-arms-return makes the whole catch a terminator.
run_case stmt_catch_ok 'error E:\n    Oops\n\ndef f(x: i64) -> i64 error[E]:\n    raise E.Oops if x < 0\n    return x * 2\n\ndef main() -> i64:\n    catch f(21):\n        slot:\n            return slot\n        error e:\n            return 7\n' 42
run_case stmt_catch_err 'error E:\n    Oops\n\ndef f(x: i64) -> i64 error[E]:\n    raise E.Oops if x < 0\n    return x * 2\n\ndef main() -> i64:\n    catch f(-1):\n        slot:\n            return slot\n        error e:\n            return 42\n' 42
run_case stmt_catch_variant 'error E:\n    Oops\n    Bad\n\ndef f(x: i64) -> i64 error[E]:\n    raise E.Bad if x > 100\n    raise E.Oops if x < 0\n    return x\n\ndef main() -> i64:\n    catch f(200):\n        slot:\n            return slot\n        E.Oops:\n            return 9\n        E.Bad:\n            return 42\n' 42
run_case catch_success 'error ParseError:\n    BadDigit\n    Overflow\n\ndef parse_num(x: i64) -> i64 error[ParseError]:\n    raise ParseError.BadDigit if x < 0\n    return x * 2\n\ndef main() -> i64:\n    v: i64 = catch parse_num(21):\n        n: n\n        ParseError.BadDigit: 7\n        ParseError.Overflow: 9\n    return v\n' 42
run_case catch_error_arm 'error ParseError:\n    BadDigit\n    Overflow\n\ndef parse_num(x: i64) -> i64 error[ParseError]:\n    raise ParseError.BadDigit if x < 0\n    return x * 2\n\ndef main() -> i64:\n    v: i64 = catch parse_num(-1):\n        n: n\n        ParseError.BadDigit: 42\n        ParseError.Overflow: 9\n    return v\n' 42
run_case catch_second_arm 'error ParseError:\n    BadDigit\n    Overflow\n\ndef parse_num(x: i64) -> i64 error[ParseError]:\n    raise ParseError.Overflow if x > 100\n    raise ParseError.BadDigit if x < 0\n    return x\n\ndef main() -> i64:\n    v: i64 = catch parse_num(200):\n        n: n\n        ParseError.BadDigit: 9\n        ParseError.Overflow: 42\n    return v\n' 42
run_case catch_bind_use 'error ParseError:\n    BadDigit\n\ndef parse_num(x: i64) -> i64 error[ParseError]:\n    raise ParseError.BadDigit if x < 0\n    return x * 2\n\ndef main() -> i64:\n    v: i64 = catch parse_num(20):\n        n: n + 2\n        ParseError.BadDigit: 7\n    return v\n' 42
run_case catch_wildcard 'error ParseError:\n    BadDigit\n\ndef parse_num(x: i64) -> i64 error[ParseError]:\n    raise ParseError.BadDigit if x < 0\n    return x * 2\n\ndef main() -> i64:\n    v: i64 = catch parse_num(-5):\n        n: n\n        _: 42\n    return v\n' 42
run_case nested_array_triple 'def main() -> i64:\n    t: mutable i64[2][2][2] = [[[1, 2], [3, 4]], [[5, 6], [7, 8]]]\n    t[1][0][1] <- 36 can Unsafe.UncheckedIndex\n    return (t[1][0][1] can Unsafe.UncheckedIndex) + (t[0][1][0] can Unsafe.UncheckedIndex) + (t[0][0][0] can Unsafe.UncheckedIndex) + 2\n' 42
run_case nested_array_loop 'def main() -> i64:\n    m: mutable i64[4][3] = [[0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]]\n    total: mutable i64 = 0\n    for r in 0..<3:\n        for c in 0..<4 |m, total, r|:\n            m[r][c] <- (r * 4 + c) can Unsafe.UncheckedIndex\n            total <- total + (m[r][c] can Unsafe.UncheckedIndex)\n    return total - 24\n' 42
# Darray iteration uses the container header ABI and binds each element by value.
run_case for_over_container 'def main() -> i64:\n    xs: darray[i64] = [1, 2]\n    total: mutable i64 = 0\n    for x in xs:\n        total <- total + x\n    return total + 39\n' 42
run_case for_darray_continue 'def main() -> i64:\n    xs: darray[i64] = [1, 2, 3, 4]\n    total: mutable i64 = 0\n    for x in xs:\n        continue if x == 2\n        total <- total + x\n    return total + 34\n' 42
run_case for_darray_break 'def main() -> i64:\n    xs: darray[i64] = [1, 2, 3, 4]\n    total: mutable i64 = 0\n    for x in xs:\n        break if x == 3\n        total <- total + x\n    return total + 39\n' 42
# `break` outside any loop must decline, not branch to nowhere.
decline_case break_outside_loop 'def main() -> i64:\n    break\n    return 0\n'
# A match GUARD is a second per-arm condition; not modeled. Ignoring it emitted the arm
# unconditionally — a silent MISCOMPILE (stage1 gave 100 where stage0 gives 42), caught by
# this fixture.
run_case match_guard 'def classify(n: i64) -> i64:\n    return match n:\n        0 if n > 1: 100\n        _: 42\n\ndef main() -> i64:\n    return classify(0)\n' 42
# A BINDING arm is INVALID Elisa in an integer match — stage0: "top-level integer match arm
# must use an integer literal or _". Treating it as a catch-all made stage1 emit code for a
# program the language rejects.
run_case match_binding_arm 'def classify(n: i64) -> i64:\n    return match n:\n        0: 100\n        other: other + 2\n\ndef main() -> i64:\n    return classify(40)\n' 42

if [ "$pass" -ne "$total" ]; then
    echo "backend_native_smoke FAILED: passed=$pass total=$total"
    exit 1
fi
if [ "$helper_missing" -ne 0 ]; then
    echo "backend_native_smoke FAILED: a check helper was undefined, so some checks never ran"
    exit 1
fi
echo "backend_native_smoke OK: $pass/$total native compile-and-run checks"
