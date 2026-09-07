# Backend smoke — the BEHAVIOURAL cases: compile one source, run it, and assert its exit
# code. `run_case` is defined here and used by every later part.
#
# Sourced by backend_native_smoke.sh, which owns the toolchain paths and the pass/total
# counters these cases increment.

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
    # Keep the linker's FIRST line: a "link failed" with the reason discarded was undiagnosable
    # when this check went red only inside a loaded gate (2026-09-06, twice).
    # One retry: this check went red only inside loaded gates (passed=400/511 twice, 511/511
    # alone), and a host linker that fails under memory pressure is not a compiler verdict.
    if ! clang -o "$exe" "$obj" "$RUNTIME_OBJ" 2>"$exe.linkerr"; then
        sleep 1
        if ! clang -o "$exe" "$obj" "$RUNTIME_OBJ" 2>"$exe.linkerr"; then
            echo "  FAIL $name: link failed: $(head -3 "$exe.linkerr" 2>/dev/null | tr '\n' ' ' | cut -c1-240)"; return
        fi
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
run_case intrinsic_ctpop  '@intrinsic(llvm.ctpop.i64)\nextern popcount(value: u64) -> u64\n\ndef main() -> i64:\n    return popcount(15).i64()\n' 4

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
run_case named_call       'def subtract(left: i64, right: i64) -> i64:\n    return left - right\n\ndef main() -> i64:\n    return subtract(right: 2, left: 40)\n'  38
run_case named_generic    'def first[A, B](left: A, right: B) -> A:\n    return left\n\ndef main() -> i64:\n    return first(right: 2, left: 40)\n'  40
# Forward reference: `main` calls a function declared LATER. Passes only because
# emit_module declares every function before emitting any body.
run_case call_forward     'def main() -> i64:\n    return helper(42)\n\ndef helper(n: i64) -> i64:\n    return n\n'      42
run_case export_scalar    'def internal(x: i64) -> i64:\n    return x + 1\n\nexport fn add(x: i64) -> i64 = internal\n\ndef main() -> i64:\n    return 42\n' 42
run_case export_global    'global seed: i64 = 7\n\nexport global seed as ctx_seed\n\ndef main() -> i64:\n    return seed\n' 7
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
run_case clone_optional_value 'def main() -> i64:\n    source: i64? = 7\n    copy: i64? = clone[i64?](source)\n    if copy is found:\n        return found + 35\n    return 0\n' 42
run_case clone_nested_darray 'def main() -> i64:\n    inner: mutable darray[i64] = []\n    inner.push(42)\n    source: mutable darray[darray[i64]] = []\n    source.push(inner)\n    copy: mutable darray[darray[i64]] = clone[darray[darray[i64]]](source)\n    return copy[0][0]\n' 42
run_case clone_struct_darray 'struct Box:\n    items: darray[i64]\n\ndef main() -> i64:\n    items: mutable darray[i64] = []\n    items.push(42)\n    source: Box = Box{items: items}\n    copy: Box = clone[Box](source)\n    return copy.items[0]\n' 42
run_case clone_sview_bytes 'def main() -> i64:\n    text: sview = "AB"\n    bytes: darray[u8] = clone[darray[u8]](text)\n    return bytes[0].i64() + bytes[1].i64() - 65 - 66 + 42\n' 42
run_case clone_view_darray 'def main() -> i64:\n    source: mutable darray[i64] = []\n    source.push(42)\n    window: view[i64] = source[0:1]\n    copy: darray[i64] = clone[darray[i64]](window)\n    return copy[0]\n' 42
run_case clone_array_darray 'def main() -> i64:\n    source: i64[2] = [7, 35]\n    copy: darray[i64] = clone[darray[i64]](source)\n    return copy[0] + copy[1]\n' 42
run_case clone_error_union_success 'error E:\n    X\n\ndef make() -> i64 error[E]:\n    return 7\n\ndef main() -> i64:\n    source: i64 error[E] = make()\n    copy: i64 error[E] = clone[i64 error[E]](source)\n    return 42\n' 42
run_case clone_error_union_failure 'error E:\n    X\n\ndef fail() -> i64 error[E]:\n    raise E.X\n\ndef main() -> i64:\n    source: i64 error[E] = fail()\n    copy: i64 error[E] = clone[i64 error[E]](source)\n    return 42\n' 42
run_case clone_error_union_struct_field 'error E:\n    X\n\nstruct Box:\n    value: i64 error[E]\n\ndef make() -> i64 error[E]:\n    return 7\n\ndef main() -> i64:\n    source: Box = Box{value: make()}\n    copy: Box = clone[Box](source)\n    return 42\n' 42
run_case error_union_parameter 'error E:\n    X\n\ndef make() -> i64 error[E]:\n    return 7\n\ndef take(value: i64 error[E]) -> i64:\n    return 42\n\ndef main() -> i64:\n    source: i64 error[E] = make()\n    return take(source)\n' 42
# Forwarding a first-class error-union value from an error-returning function must split the
# descriptor back into its status and payload. A plain `return value` used to store the whole
# `{code, payload_ptr}` descriptor through the i64 out-slot and return success, losing the 7.
run_case error_union_return_forward 'error E:\n    X\n\ndef make() -> i64 error[E]:\n    return 7\n\ndef relay(value: i64 error[E]) -> i64 error[E]:\n    return value\n\ndef main() -> i64:\n    source: i64 error[E] = make()\n    return try relay(source) else 5\n' 7
run_case error_union_return_forward_failure 'error E:\n    X\n\ndef fail() -> i64 error[E]:\n    raise E.X\n\ndef relay(value: i64 error[E]) -> i64 error[E]:\n    return value\n\ndef main() -> i64:\n    source: i64 error[E] = fail()\n    return try relay(source) else 42\n' 42
# An errorset-only generic must specialize on the callback's concrete error family, and a
# fallible function value must keep the hidden payload-out ABI through both raw and closure
# dispatch. The old stage1 path emitted an unspecialized i64() callback and returned 2.
run_case errorset_generic_fn_value 'error IoErr:\n    Bad\n\ndef ioOk() -> i64 error[IoErr]:\n    return 7\n\ndef ioFail() -> i64 error[IoErr]:\n    raise IoErr.Bad\n\ndef applyDouble[errorset R](f: fn() -> i64 error[R]) -> i64 error[R]:\n    value: i64 = try f()\n    return value * 2\n\ndef main() -> i64:\n    ok: i64 = try applyDouble(ioOk) else 5\n    bad: i64 = try applyDouble(ioFail) else 9\n    return ok + bad\n' 23
# The inline lambda spelling erases its error suffix from the compact AST, so its source-line
# metadata must recover the concrete family before closure lifting. This exercises the tagged
# closure ABI in addition to the raw named-function callback above.
run_case errorset_generic_lambda 'error E:\n    X\n\ndef apply[errorset R](f: fn() -> i64 error[R]) -> i64 error[R]:\n    value: i64 = try f()\n    return value * 2\n\ndef main() -> i64:\n    value: i64 = try apply(fn() -> i64 error[E] => 7) else 5\n    return value\n' 14
# Payload-bearing error sets use a struct status ABI. The first-class callable adapter must
# keep that struct at the raw/closure call boundary, then normalize field 0 into the ordinary
# `{code, payload_ptr}` error-union descriptor used by `try`. This covers a named raw callback,
# a tagged closure, and both success/failure propagation through the errorset generic.
run_case errorset_payload_fn_value 'error Payload:\n    Bad(code: i64)\n\ndef ok(value: i64) -> i64 error[Payload]:\n    return value\n\ndef bad(value: i64) -> i64 error[Payload]:\n    raise Payload.Bad(value)\n\ndef apply[errorset R](f: fn(i64) -> i64 error[R], value: i64) -> i64 error[R]:\n    result: i64 = try f(value)\n    return result + 1\n\ndef main() -> i64:\n    good: i64 = try apply(ok, 6) else 40\n    failed: i64 = try apply(bad, 6) else 20\n    closed: i64 = try apply(fn(value: i64) -> i64 error[Payload] => value + 2, 6) else 30\n    return good + failed + closed\n' 36
# A direct payload error call assigned as a first-class union must extract the struct tag before
# constructing the compact descriptor; inserting the whole `%ErrSet` into its i32 code field is
# invalid IR and used to be an untested decline.
run_case errorset_payload_union_value 'error Payload:\n    Bad(code: i64)\n\ndef ok(value: i64) -> i64 error[Payload]:\n    return value\n\ndef main() -> i64:\n    source: i64 error[Payload] = ok(7)\n    return try source else 42\n' 7
run_case errorset_payload_union_catch 'error Payload:\n    Bad(code: i64)\n\ndef bad() -> i64 error[Payload]:\n    raise Payload.Bad(9)\n\ndef main() -> i64:\n    source: i64 error[Payload] = bad()\n    return catch source:\n        ok:\n            ok\n        Payload.Bad:\n            42\n' 42
run_case errorset_payload_call_catch 'error Payload:\n    Bad(code: i64)\n\ndef bad() -> i64 error[Payload]:\n    raise Payload.Bad(9)\n\ndef main() -> i64:\n    return catch bad():\n        ok:\n            ok\n        Payload.Bad(code):\n            code\n' 9
run_case errorset_payload_stmt_catch 'error Payload:\n    Bad(code: i64)\n\ndef bad() -> i64 error[Payload]:\n    raise Payload.Bad(9)\n\ndef main() -> i64:\n    catch bad():\n        ok:\n            return ok\n        Payload.Bad(code):\n            return code\n' 9
run_case errorset_payload_multi_catch 'error Payload:\n    Bad(left: i64, right: i64)\n\ndef bad() -> i64 error[Payload]:\n    raise Payload.Bad(7, 5)\n\ndef main() -> i64:\n    return catch bad():\n        ok:\n            ok\n        Payload.Bad(left, right):\n            left + right\n' 12
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
