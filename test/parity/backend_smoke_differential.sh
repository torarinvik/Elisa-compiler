# Backend smoke — the DIFFERENTIAL cases: run the same source through stage0 and stage1 and
# require the same answer. These are the cases where 'it compiled' proves nothing and only a
# second implementation can say what the right result is.
#
# Sourced by backend_native_smoke.sh.

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
diff_case errorset_generic_fn_value 'error IoErr:\n    Bad\n\ndef ioOk() -> i64 error[IoErr]:\n    return 7\n\ndef ioFail() -> i64 error[IoErr]:\n    raise IoErr.Bad\n\ndef applyDouble[errorset R](f: fn() -> i64 error[R]) -> i64 error[R]:\n    value: i64 = try f()\n    return value * 2\n\ndef main() -> i64:\n    ok: i64 = try applyDouble(ioOk) else 5\n    bad: i64 = try applyDouble(ioFail) else 9\n    return ok + bad\n'
diff_case errorset_generic_lambda 'error E:\n    X\n\ndef apply[errorset R](f: fn() -> i64 error[R]) -> i64 error[R]:\n    value: i64 = try f()\n    return value * 2\n\ndef main() -> i64:\n    value: i64 = try apply(fn() -> i64 error[E] => 7) else 5\n    return value\n'
diff_case errorset_payload_fn_value 'error Payload:\n    Bad(code: i64)\n\ndef ok(value: i64) -> i64 error[Payload]:\n    return value\n\ndef bad(value: i64) -> i64 error[Payload]:\n    raise Payload.Bad(value)\n\ndef apply[errorset R](f: fn(i64) -> i64 error[R], value: i64) -> i64 error[R]:\n    result: i64 = try f(value)\n    return result + 1\n\ndef main() -> i64:\n    good: i64 = try apply(ok, 6) else 40\n    failed: i64 = try apply(bad, 6) else 20\n    closed: i64 = try apply(fn(value: i64) -> i64 error[Payload] => value + 2, 6) else 30\n    return good + failed + closed\n'
diff_case errorset_payload_union_value 'error Payload:\n    Bad(code: i64)\n\ndef ok(value: i64) -> i64 error[Payload]:\n    return value\n\ndef main() -> i64:\n    source: i64 error[Payload] = ok(7)\n    return try source else 42\n'
diff_case errorset_payload_union_catch 'error Payload:\n    Bad(code: i64)\n\ndef bad() -> i64 error[Payload]:\n    raise Payload.Bad(9)\n\ndef main() -> i64:\n    source: i64 error[Payload] = bad()\n    return catch source:\n        ok:\n            ok\n        Payload.Bad:\n            42\n'
diff_case errorset_payload_call_catch 'error Payload:\n    Bad(code: i64)\n\ndef bad() -> i64 error[Payload]:\n    raise Payload.Bad(9)\n\ndef main() -> i64:\n    return catch bad():\n        ok:\n            ok\n        Payload.Bad(code):\n            code\n'
diff_case errorset_payload_stmt_catch 'error Payload:\n    Bad(code: i64)\n\ndef bad() -> i64 error[Payload]:\n    raise Payload.Bad(9)\n\ndef main() -> i64:\n    catch bad():\n        ok:\n            return ok\n        Payload.Bad(code):\n            return code\n'
diff_case errorset_payload_multi_catch 'error Payload:\n    Bad(left: i64, right: i64)\n\ndef bad() -> i64 error[Payload]:\n    raise Payload.Bad(7, 5)\n\ndef main() -> i64:\n    return catch bad():\n        ok:\n            ok\n        Payload.Bad(left, right):\n            left + right\n'
diff_case darray_push  'def main() -> i64:\n    xs: mutable darray[i64] = []\n    xs.push(40)\n    xs.push(2)\n    return xs[0] + xs[1]\n'
diff_case darray_grow  'def main() -> i64:\n    xs: mutable darray[i64] = []\n    for i in 0..<500:\n        xs.push(1)\n    total: mutable i64 = 0\n    for j in 0..<500:\n        total <- total + xs[j]\n    return total - 458\n'
diff_case darray_u8    'def main() -> i64:\n    xs: mutable darray[u8] = []\n    xs.push(200)\n    xs.push(100)\n    return xs[0].i64() - xs[1].i64() - 58\n'
diff_case array_literal 'def main() -> i64:\n    xs: i64[3] = [10, 30, 2]\n    return xs[0] + xs[1] + xs[2]\n'
diff_case array_u8      'def main() -> i64:\n    xs: u8[3] = [200, 100, 50]\n    return xs[0].i64() - xs[1].i64() - xs[2].i64() - 8\n'
diff_case array_rw      'def main() -> i64:\n    xs: mutable i64[5] = [0, 0, 0, 0, 0]\n    for i in 0..<5:\n        xs[i] <- i * 2\n    total: mutable i64 = 0\n    for j in 0..<5:\n        total <- total + xs[j]\n    return total + 22\n'
diff_case nested_array  'def main() -> i64:\n    m: i64[2][2] = [[10, 20], [3, 9]]\n    return m[0][1] + m[1][0] + 12\n'
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
diff_case aggregate_global_refs 'struct Pair:\n    left: i32\n    right: i32\n\nstruct Holder:\n    pair: Pair\n\nglobal base: Pair = Pair{left: 1, right: 2}\nglobal table: Pair[2] = [base, Pair{left: 3, right: 4}]\nglobal picked: Pair = table[1]\nglobal wrapped: Holder = Holder{pair: table[0]}\nglobal first_left: i32 = table[0].left\n\ndef main() -> i64:\n    return picked.left.i64() + wrapped.pair.right.i64() + first_left.i64()\n'
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
# `@link_name` changes only the emitted symbol spelling; source calls still use `c_strlen`.
diff_case extern_link_name '@link_name(strlen)\nextern c_strlen(s: cstr) -> usize\n\ndef main() -> i64:\n    return c_strlen("hello").i64()\n'
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
# A threaded callee may construct an aggregate temporary before adopting it into the
# caller-owned container. Both the outer header AND the nested row backing must use the
# caller region; a callee scratch arena leaves `rows[0]` valid-looking but dangling.
# 500 elements force several reallocations before the aggregate escapes.
diff_case region_ref_adopts_nested_temporary 'def build_row[@r](out: mutable darray[darray[i64]]& @r) -> void:\n    row: mutable darray[i64] @r = []\n    for i in 0..<500:\n        row.push(i)\n    out.push(row)\n\ndef main() -> i64:\n    rows: mutable darray[darray[i64]] = []\n    build_row(rows)\n    row: darray[i64] = rows[0] can Unsafe.UncheckedIndex\n    return (row[499] can Unsafe.UncheckedIndex) - 457\n'
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
# Mutable globals must be real writable storage in both backends, while plain `global`
# declarations used by the runtime remain folded/linked according to stage0's existing ABI.
diff_case global_mutable_scalar 'global mutable seed: i64 = 0\n\ndef main() -> i64:\n    seed <- 42\n    return seed\n'
diff_case global_mutable_array 'global mutable xs: i64[3] = [10, 20, 30]\n\ndef main() -> i64:\n    xs[1] <- 42\n    return xs[1]\n'
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
# A first-class union parameter can be forwarded as an error-return value. This exercises the
# split ABI in the error path as well as the existing `try` value extraction in the caller.
diff_case error_union_return_forward 'error E:\n    X\n\ndef make() -> i64 error[E]:\n    return 7\n\ndef relay(value: i64 error[E]) -> i64 error[E]:\n    return value\n\ndef main() -> i64:\n    source: i64 error[E] = make()\n    return try relay(source) else 5\n'
diff_case error_union_return_forward_failure 'error E:\n    X\n\ndef fail() -> i64 error[E]:\n    raise E.X\n\ndef relay(value: i64 error[E]) -> i64 error[E]:\n    return value\n\ndef main() -> i64:\n    source: i64 error[E] = fail()\n    return try relay(source) else 42\n'
# First-class error-union operands, not just direct calls. Stage0 permits `try` and
# expression `catch` over locals/parameters carrying the descriptor representation.
run_case error_union_try_local 'error E:\n    X\n\ndef make() -> i64 error[E]:\n    return 7\n\ndef use(value: i64 error[E]) -> i64:\n    return try value else 42\n\ndef main() -> i64:\n    return use(make())\n' 7
run_case error_union_catch_local 'error E:\n    X\n\ndef make() -> i64 error[E]:\n    raise E.X\n\ndef use(value: i64 error[E]) -> i64:\n    return catch value:\n        ok:\n            ok\n        E.X:\n            42\n\ndef main() -> i64:\n    return use(make())\n' 42
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
# A reference parameter is already the pointee pointer at the call boundary. Forwarding
# it as `relay(c)` must preserve that pointer; spelling `&c` would pass the address of the
# parameter's pointer slot (a different value). This is the exact shape used by the
# self-hosted ChordBrain output list, so keep it in both the stage1 behavior lane and the
# stage0 differential lane.
run_case ref_forwarded_param 'struct Counter:\n    value: mutable i64\n\ndef bump(c: mutable Counter&) -> void:\n    c.value <- c.value + 1\n\ndef relay(c: mutable Counter&) -> void:\n    bump(c)\n\ndef main() -> i64:\n    c: mutable Counter = Counter{value: 41}\n    relay(c)\n    return c.value\n' 42
diff_case ref_forwarded_param 'struct Counter:\n    value: mutable i64\n\ndef bump(c: mutable Counter&) -> void:\n    c.value <- c.value + 1\n\ndef relay(c: mutable Counter&) -> void:\n    bump(c)\n\ndef main() -> i64:\n    c: mutable Counter = Counter{value: 41}\n    relay(c)\n    return c.value\n'
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
