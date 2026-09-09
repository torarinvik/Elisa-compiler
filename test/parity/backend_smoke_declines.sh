# Backend smoke — what stage1 must REFUSE, and the packed-store cases where stage0 and stage1
# deliberately disagree. An unsupported input has to be declined by name; being mis-emitted
# silently is the failure these guard against.
#
# Sourced by backend_native_smoke.sh.

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
# Mutable Elisa globals are addressable module storage, not folded constants.
run_case global_mutable_scalar 'global mutable seed: i64 = 0\n\ndef main() -> i64:\n    seed <- 42\n    return seed\n' 42
run_case global_mutable_array 'global mutable xs: i64[3] = [10, 20, 30]\n\ndef main() -> i64:\n    xs[1] <- 42\n    return xs[1]\n' 42
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
# Low-level runtime string helpers return borrowed byte pointers (`u8&`), not only cstr.
# A literal in that context must still lower to the same LLVM global pointer.
run_case byte_ref_literal 'def choose(flag: bool) -> u8&:\n    return "True" if flag else "False"\n\ndef main() -> i64:\n    _ = choose(true)\n    return 42\n' 42
# `isize` is the signed pointer-width scalar used by portable runtime callbacks.
run_case isize_scalar 'def main() -> i64:\n    value: isize = 40\n    return value.i64() + 2\n' 42
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
# BOTH of these were `decline_case`s asserting the BACKEND refuses a store-less packed
# constructor. They stopped declining, and the reason is worth stating because it is not a
# regression in either compiler: fixing a stage0 scoping bug (Elisa-core a7655160) changed
# how stage1's own source compiles, and these two shapes now reach codegen.
#
# The backend-only decline was never the guarantee that mattered. `emit_native` has no
# semantic layer, so it was measuring a path no user can reach — every program below is
# REJECTED by the CLI before codegen. The CLI decision is what is checked now.
#
# Both agree now. The recursive one was an open permissive gap when these cases were
# written and was closed by narrowing stage1's store-clause exemption: it had exempted
# every AUTO-PROMOTED enum, where stage0 exempts AST REFINEMENTS specifically. A plain
# recursive enum still owes a store at the constructor unless it is written `new X.V(...)`,
# which is region-backed by design; a DECLARED `packed enum` owes one even then.
packed_accept_case() {
    local name="$1" src="$2" want_gap="$3"
    total=$((total + 1))
    printf '%b' "$src" > "$BUILD/pack_$name.elisa"
    "$ELISACORE_BIN" -emit llvm -o /dev/null "$BUILD/pack_$name.elisa" </dev/null >/dev/null 2>&1
    local rc0=$?
    bash "$ROOT/scripts/elisac_stage1.sh" -emit llvm -o /dev/null "$BUILD/pack_$name.elisa" >/dev/null 2>&1
    local rc1=$?
    local agree=0
    [ "$rc0" -eq 0 ] && [ "$rc1" -eq 0 ] && agree=1
    [ "$rc0" -ne 0 ] && [ "$rc1" -ne 0 ] && agree=1
    if [ "$agree" -eq 1 ] && [ "$want_gap" -eq 0 ]; then pass=$((pass + 1)); return; fi
    if [ "$agree" -eq 0 ] && [ "$want_gap" -eq 1 ]; then pass=$((pass + 1)); return; fi
    if [ "$want_gap" -eq 1 ]; then
        echo "  FAIL packed_$name: the ratcheted gap CLOSED (stage0 rc=$rc0, stage1 rc=$rc1) -- drop the ratchet"
    else
        echo "  FAIL packed_$name: acceptance diverged (stage0 rc=$rc0, stage1 rc=$rc1)"
    fi
}
packed_accept_case enum_needs_store 'packed enum Node:\n    Leaf(v: i64)\n    Tag(t: i64)\n\ndef read(n: Node) -> i64:\n    return match n:\n        Node.Leaf(v): v\n        Node.Tag(t): t\n\ndef main() -> i64:\n    return read(Node.Leaf(42))\n' 0
packed_accept_case recursive_enum_is_packed 'enum Node:\n    Leaf(v: i64)\n    Pair(a: Node, b: Node)\n\ndef main() -> i64:\n    n: Node = Node.Leaf(42)\n    return match n:\n        Node.Leaf(v): v\n        Node.Pair(a, b): 0\n' 0
# `new X.V(...)` is the spelling that satisfies it for an auto-promoted enum: both accept.
packed_accept_case recursive_new_is_accepted 'enum Node:\n    Leaf(v: i64)\n    Pair(a: Node, b: Node)\n\ndef build() -> i64:\n    region r(1024):\n        n: Node = new Node.Leaf(42)\n        return match n:\n            Node.Leaf(v): v\n            Node.Pair(a, b): 0\n    return 0\n\ndef main() -> i64:\n    return build()\n' 0
# C variadic externs use the fixed parameter ABI plus C default argument promotions for the
# unnamed tail. The call is observable through printf and stage0 accepts the same program.
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
# List comprehension over an existing DARRAY source (not a range): built by push, one
# element per source item that passes the optional `if` filter.
run_case list_comp_over_darray 'def main() -> i64:\n    xs: darray[i64] = [10, 20, 12]\n    ys: darray[i64] = [x + 1 for x in xs]\n    return ys[0] + ys[1] + ys[2] - 3\n' 42
run_case list_comp_darray_filter 'def main() -> i64:\n    xs: darray[i64] = [1, 2, 3, 4, 5, 6]\n    ys: darray[i64] = [x for x in xs if x > 3]\n    return ys[0] + ys[1] + ys[2] + 27\n' 42
# `xs.extend(ys)` — append every element of the source darray, lowered as a push loop.
run_case darray_extend_count 'def main() -> i64:\n    xs: mutable darray[i64] = [1, 2, 3]\n    ys: darray[i64] = [10, 20]\n    xs.extend(ys)\n    return xs.count.i64() * 8 + 2\n' 42
run_case darray_extend_values 'def main() -> i64:\n    xs: mutable darray[i64] = [1, 2]\n    ys: darray[i64] = [40, 8]\n    xs.extend(ys)\n    return xs[2] + xs[3] - 6\n' 42
run_case darray_extend_empty 'def main() -> i64:\n    xs: mutable darray[i64] = [42]\n    ys: darray[i64] = []\n    xs.extend(ys)\n    return xs[0]\n' 42
# `for i, x in xs.enumerate()` — index+value iteration over a darray (two binders: the
# running index i64 and the element).
run_case darray_enumerate_value 'def main() -> i64:\n    xs: darray[i64] = [10, 20, 30]\n    s: mutable i64 = 0\n    for i, x in xs.enumerate():\n        s <- s + x\n    return s - 18\n' 42
run_case darray_enumerate_index 'def main() -> i64:\n    xs: darray[i64] = [5, 5, 5, 5]\n    s: mutable i64 = 0\n    for i, x in xs.enumerate():\n        s <- s + i\n    return s + 36\n' 42
# `xs.clear()` — logically empty the darray (count -> 0, backing retained).
run_case darray_clear_count 'def main() -> i64:\n    xs: mutable darray[i64] = [1, 2, 3]\n    xs.clear()\n    return xs.count.i64() + 42\n' 42
run_case darray_clear_then_push 'def main() -> i64:\n    xs: mutable darray[i64] = [1, 2, 3]\n    xs.clear()\n    xs.push(42)\n    return xs[0]\n' 42
# `xs.truncate(n)` — shrink to at most n elements (count -> min(count, n)); a no-op when
# n >= count; the retained prefix is unchanged.
run_case darray_truncate_shrink 'def main() -> i64:\n    xs: mutable darray[i64] = [1, 2, 3, 4, 5]\n    xs.truncate(2.usize())\n    return xs.count.i64() + 40\n' 42
run_case darray_truncate_noop 'def main() -> i64:\n    xs: mutable darray[i64] = [10, 20, 30]\n    xs.truncate(10.usize())\n    return xs.count.i64() + 39\n' 42
# `xs.resize(n)` — set length to exactly n: zero-fill new tail when growing, drop tail when
# shrinking. Grow (count 3->5, new elements read as 0) and shrink (5->2, prefix kept).
run_case darray_resize_grow 'def main() -> i64:\n    xs: mutable darray[i64] = [7, 8, 9]\n    xs.resize(5.usize())\n    return xs.count.i64() + xs[3] + xs[4] + 37\n' 42
run_case darray_resize_shrink 'def main() -> i64:\n    xs: mutable darray[i64] = [40, 8, 9, 10, 11]\n    xs.resize(2.usize())\n    return xs[0] + xs[1] + xs.count.i64() - 8\n' 42
# The REASSIGNMENT spelling of the same three. `push`/`truncate` had in-place assign paths;
# `resize` and `clear` did not, so `xs <- xs.resize(n)` fell to emit_expression, which models
# neither, and DECLINED — taking every other function in the unit down with it (see the
# emitted_count guard in elisac.elisa) with no diagnostic at all. stage0 compiles the form,
# and `lmut` container code is written this way throughout, so the gap was reachable: one
# such line in src/driver/project.elisa silently killed the whole driver.
#
# Each case pairs with its bare-statement twin above and must agree with it.
run_case darray_resize_assign_grow 'def main() -> i64:\n    xs: mutable darray[i64] = [7, 8, 9]\n    xs <- xs.resize(5.usize())\n    return xs.count.i64() + xs[3] + xs[4] + 37\n' 42
run_case darray_resize_assign_shrink 'def main() -> i64:\n    xs: mutable darray[i64] = [40, 8, 9, 10, 11]\n    xs <- xs.resize(2.usize())\n    return xs[0] + xs[1] + xs.count.i64() - 8\n' 42
run_case darray_clear_assign 'def main() -> i64:\n    xs: mutable darray[i64] = [1, 2, 3]\n    xs <- xs.clear()\n    return xs.count.i64() + 42\n' 42
# Resize-assign into a STRUCT FIELD — the shape the project system actually uses, and the one
# that reaches darray_address_of_expr through a field chain rather than a bare local.
run_case darray_resize_assign_field 'struct Bag:\n    items: mutable darray[i64]\n\ndef main() -> i64:\n    b: mutable Bag = Bag{items: [1, 2, 3]}\n    b.items <- b.items.resize(6.usize())\n    return b.items.count.i64() + b.items[5] + 36\n' 42
# INDEXING DIRECTLY INTO A CAST, with no local in between. `.cast[T]` parses as
# Index(Field(x, "cast"), T), so `(p.cast[T&])[i]` is an Index whose BASE is an Index — and
# every index path resolved a base that was an Ident or an array literal, so the whole
# enclosing function declined. stage0 compiles it.
#
# Not hypothetical: `subcommand_compiles_project((argv.cast[mutable cstr&&])[1.usize()].cast[cstr])`
# in the driver made stage1 unable to compile its own source, and the only symptom was the
# whole-unit decline. The read and the write resolve through the same lvalue chain, so the
# pair below pins both directions.
run_case index_into_cast_read 'def main() -> i64 can[Abort.Panic, Memory.Allocate, Unsafe.PointerCast]:\n    xs: mutable darray[i64] = [40, 2]\n    base: void& = (&xs[0.usize()]).cast[void&] can Unsafe.PointerCast\n    return (base.cast[mutable i64&])[0.usize()] + (base.cast[mutable i64&])[1.usize()]\n' 42
run_case index_into_cast_write 'def main() -> i64 can[Abort.Panic, Memory.Allocate, Unsafe.PointerCast]:\n    xs: mutable darray[i64] = [1, 2]\n    base: void& = (&xs[0.usize()]).cast[void&] can Unsafe.PointerCast\n    (base.cast[mutable i64&])[0.usize()] <- 40\n    return xs[0.usize()] + xs[1.usize()]\n' 42
# OVERLOAD RESOLUTION onto a REFERENCE parameter. `pick(n)` with an i64 local must select
# `pick(value: i64&)`, not the same-arity `pick(label: cstr)`.
#
# overload_index_for_args compared the DECLARED `i64&` against the ACTUAL `i64` and rejected
# it, even though the call emitter borrows the place implicitly — so the candidate set came
# back empty and resolution fell back to "first overload with this arity". That was a SILENT
# WRONG ANSWER, not a decline: stage0 answers 42 here and stage1 answered 7.
#
# It also had a second, louder face. elisacore_std's test.elisa declares `def fail(message:
# cstr)` and the prelude pulls it into every program, so any user function named `fail` taking
# one reference argument lost resolution to it and then DECLINED emitting its argument at
# `cstr` — killing every function in the unit with no diagnostic. That is what made routing
# errors through a shared `fail(detail)` helper "uncompilable" in the project system.
#
# Both declaration orders, because the bug was order-sensitive by construction.
run_case overload_ref_param_second 'def pick(label: cstr) -> i64:\n    return 7\n\ndef pick(value: i64&) -> i64:\n    return value + 37\n\ndef main() -> i64:\n    n: mutable i64 = 5\n    return pick(n)\n' 42
run_case overload_ref_param_first 'def pick(value: i64&) -> i64:\n    return value + 37\n\ndef pick(label: cstr) -> i64:\n    return 7\n\ndef main() -> i64:\n    n: mutable i64 = 5\n    return pick(n)\n' 42
# The container spelling, which is the one the project system actually used.
#
# Do not name the helper `size_of`: it lexes as the reserved `sizeof` and stage0 rejects the
# fixture outright, which in this harness is indistinguishable from a stage1 decline. That
# cost a wrong diagnosis — a bad fixture read as a second backend gap in container types.
# When a case here fails, compile it under stage0 first.
run_case overload_ref_param_darray 'def byte_count(label: cstr) -> i64:\n    return 7\n\ndef byte_count(items: darray[u8]&) -> i64:\n    return items.count.i64() + 39\n\ndef main() -> i64:\n    xs: mutable darray[u8] = [1, 2, 3]\n    return byte_count(xs)\n' 42
# An explicit `&` argument must still resolve to the same overload — this spelling always
# worked, and is the control proving the fix did not simply move the failure.
run_case overload_ref_param_explicit 'def pick(label: cstr) -> i64:\n    return 7\n\ndef pick(value: i64&) -> i64:\n    return value + 37\n\ndef main() -> i64:\n    n: mutable i64 = 5\n    return pick(&n)\n' 42
# OVERLOADED generic UFCS: two `pick[T]` templates distinguished by receiver type. The right
# BODY must be selected by the receiver (not by declaration order), and two instantiations of
# the same name+args must not alias in the cache. Slot-aware generic overload resolution.
run_case overload_ufcs_by_receiver 'struct Holder[T]:\n    v: T\nstruct Keeper[T]:\n    v: T\ndef pick[T](x: Holder[T]) -> i64:\n    return 7\ndef pick[T](x: Keeper[T]) -> i64:\n    return 42\ndef main() -> i64:\n    b: Keeper[i64] = Keeper[i64] { v: 1 }\n    return b.pick()\n' 42
run_case overload_ufcs_both 'struct Holder[T]:\n    v: T\nstruct Keeper[T]:\n    v: T\ndef pick[T](x: Holder[T]) -> i64:\n    return 40\ndef pick[T](x: Keeper[T]) -> i64:\n    return 2\ndef main() -> i64:\n    a: Holder[i64] = Holder[i64] { v: 1 }\n    b: Keeper[i64] = Keeper[i64] { v: 1 }\n    return a.pick() + b.pick()\n' 42
# A generic function over a DARRAY PARAMETER: `cnt[T](da: darray[T]&)`. T must be inferred
# from the darray argument's element (unify_annotation recurses into darray[T] like view[T]).
run_case generic_darray_param 'def cnt[T](da: mutable darray[T]&) -> i64:\n    return da.count.i64()\ndef main() -> i64:\n    xs: mutable darray[i64] = [1, 2, 3]\n    return cnt(&xs) + 39\n' 42
# Indexing a ref-to-NUMERIC-scalar as a C-style pointer base (`p: T& = base.cast[T&]; p[i]`),
# how Slice[T] reads its backing. Round-trips a value through a uintptr and reads it back by index.
run_case scalar_ref_index_read 'def main() -> i64:\n    x: mutable i64 = 42\n    u: uintptr = (&x).cast[uintptr] can Unsafe.PointerCast\n    p: mutable i64& = u.cast[mutable i64&] can Unsafe.PointerCast\n    return p[0.usize()]\n' 42
# Address of a BORROWED darray-ref param's element (`&da[i]`), as in Slice's
# `slice(&da)` -> `(&da[0]).cast[uintptr]`. Round-trips the address back to a ref and reads it.
run_case addr_of_darray_ref_elem 'def head_addr(da: mutable darray[i64]&) -> uintptr:\n    return (&da[0.usize()]).cast[uintptr] can Unsafe.PointerCast\ndef main() -> i64:\n    xs: mutable darray[i64] = [42, 8, 9]\n    u: uintptr = head_addr(&xs)\n    p: i64& = u.cast[i64&] can Unsafe.PointerCast\n    return p\n' 42
# Indexing a ref-typed FIELD as a buffer pointer: `&b.items[i]` / `b.items[i] <- v` where
# `items` is a ref field (Deque's `items: T&?` is this, optional-wrapped). Write then read back.
run_case field_ref_index 'struct Buf:\n    items: mutable i64&\n    n: usize\ndef wr(b: Buf&, i: usize, v: i64) -> void:\n    b.items[i] <- v\ndef main() -> i64:\n    x: mutable i64 = 0\n    b: Buf = Buf { items: &x, n: 1.usize() }\n    wr(&b, 0.usize(), 42)\n    return x\n' 42
# `in owner:` region block where owner is a BORROWED arena (`owner: mutable Arena&`) — the std
# container ctors activate their arena this way. Allocations inside target the borrowed arena.
run_case in_borrowed_arena 'def build(a: mutable Arena&) -> i64 can[Memory.Allocate]:\n    xs: mutable darray[i64] = []\n    in a:\n        xs.push(42)\n    return xs[0]\ndef main() -> i64 can[Memory.Allocate]:\n    arena: mutable Arena = zeroed\n    return build(&arena)\n' 42
# `match OPT: null: … v: …` — a match whose scrutinee is an OPTIONAL value: the binding arm
# binds the payload on present, the null arm runs on absent (like `if OPT is v:` as a match).
run_case match_optional_present 'def f(x: i64) -> i64?:\n    return x if x > 0 else null\ndef main() -> i64:\n    match f(42):\n        null:\n            return 7\n        v:\n            return v\n    return 0\n' 42
run_case match_optional_absent 'def f(x: i64) -> i64?:\n    return x if x > 0 else null\ndef main() -> i64:\n    match f(-1):\n        null:\n            return 42\n        v:\n            return v\n    return 0\n' 42
# `x: T = get OPT else BODY` — monadic unwrap with an explicit recovery: present binds the
# payload, absent runs BODY (which exits). Present path and absent path both exercised.
run_case get_else_present 'def find(x: i64) -> i64?:\n    return x if x > 0 else null\ndef main() -> i64:\n    v: i64 = get find(40) else return 7\n    return v + 2\n' 42
# BARE `get OPT` (no `else`): the parser erases it to `v: T = OPT` (OPT: T?) plus a
# `__checked_get` annotation; the backend recognizes the unnarrowed Optional->non-optional
# VarDecl (which stage0 accepts ONLY for a get-unwrap) and lowers it to bind-payload on
# PRESENT / propagate-None on ABSENT out of THIS optional-returning fn. index_map_get uses it.
run_case get_bare_present 'def find(x: i64) -> i64?:\n    return x if x > 0 else null\ndef pick(x: i64) -> i64?:\n    v: i64 = get find(x)\n    return v + 2\ndef main() -> i64:\n    return get pick(40) else 7\n' 42
run_case get_bare_absent 'def find(x: i64) -> i64?:\n    return x if x > 0 else null\ndef pick(x: i64) -> i64?:\n    v: i64 = get find(x)\n    return v + 2\ndef main() -> i64:\n    return get pick(-1) else 42\n' 42
# A struct FIELD passed to a `mutable T&` param WITHOUT an explicit `&` must be auto-
# addressed (stage0 does): the callee mutates the ORIGINAL field, not a by-value copy. Without
# it the struct is passed by value and the mutation is lost (or its bytes read as a pointer →
# crash). This is what the real-std IndexMap's `arena_dict_put(a, map.by_key, …)` relies on.
run_case field_arg_autoref 'struct Inner:\n    v: mutable i64\nstruct Outer:\n    inner: mutable Inner\ndef bump(p: mutable Inner&) -> void:\n    p.v <- p.v + 42\ndef main() -> i64:\n    o: mutable Outer = zeroed\n    bump(o.inner)\n    return o.inner.v\n' 42
diff_case variadic_extern 'extern printf(fmt: cstr, ...) -> i32\n\ndef main() -> i64:\n    _ = printf("%d %f\\n", 7, 1.5)\n    return 42\n' 42
# A label that is NOT the payload field's declared name must decline rather than be emitted
# as this constructor -- it names a different program.
decline_case penum_wrong_label 'enum Shape:\n    Circle(r: i64)\n\ndef main() -> i64:\n    s: Shape = Shape.Circle(bogus: 42)\n    return match s:\n        Shape.Circle(r): r\n'
# An explicit `new[NAME]` selector must resolve to an arena/region owner or a packed store.
# The backend used to treat an unknown selector as transparent and emit the operand value,
# silently changing a reference-producing allocation into a scalar expression. Keep this
# backend-only gate because it protects callers that invoke the emitter without the CLI's
# semantic diagnostics.
decline_case new_unknown_region_selector 'def main() -> i64:\n    return new[missing] 7\n'
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
# WAS a decline case. stage1 has since gained real `dict` support and stage0 compiles
# this too, so demanding a decline demanded a DIVERGENCE from the reference. Now pins the
# behaviour instead: an empty dict declaration compiles, links and runs.
run_case dict_empty_declaration 'def main() -> i64:\n    d: mutable dict[i64, i64] = {}\n    return 42\n' 42
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
# WAS `decline_eq_is_not_assign`, asserting the emitter refuses `i = i + 1` in an inner
# scope. It does not refuse it any more, and it should not: `=` DECLARES, so an inner
# `i = i + 1` is a new local one greater than the enclosing `i`, which is a legal program
# both compilers accept.
#
# Auditing that expiry found a real stage0 bug (Elisa-core a7655160): stage0 brought the
# new binding into scope BEFORE emitting its initializer, so `i` inside the initializer
# resolved to the slot being declared — its native binary returned uninitialized stack
# memory (221) where its interpreter returned 6. stage1 already read the outer slot.
# This case pins the agreed answer.
run_case shadowing_decl_reads_outer 'def main() -> i64:\n    i: mutable i64 = 5\n    if true:\n        i = i + 1\n        return i\n    return 0\n' 6

# NOT covered here, deliberately: the LOOP form
#     i: mutable i64 = 0
#     while i < 3:
#         i = i + 1
# where the inner declaration means the outer `i` never advances, so the backend loops
# forever while stage0's INTERPRETER answers 3. Whether a declaration may shadow a mutable
# outer local at all is a language question, not a compiler repair, so no expectation is
# asserted until it is settled.
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
