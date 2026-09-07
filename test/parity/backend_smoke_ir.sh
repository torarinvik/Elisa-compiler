# Backend smoke — the IR-SHAPE assertions: what stage1's module must LOOK like, either
# matched against stage0's IR for the same source or asserted on its own.
#
# Sourced by backend_native_smoke.sh.

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
ir_case cstr_param_is_ptr 'def take(s: cstr) -> i64:\n    return 42\n\ndef main() -> i64:\n    return take("hi")\n' 'define (internal )?i64 @take\(ptr'
ir_case export_scalar_wrapper 'def internal(x: i64) -> i64:\n    return x + 1\n\nexport fn add(x: i64) -> i64 = internal\n\ndef main() -> i64:\n    return 42\n' 'define i64 @add\(i64'
ir_case export_global_alias 'global seed: i64 = 7\n\nexport global seed as ctx_seed\n\ndef main() -> i64:\n    return seed\n' '^@ctx_seed = alias i64, ptr @seed'
ir_case aggregate_global_refs 'struct Pair:\n    left: i32\n    right: i32\n\nstruct Holder:\n    pair: Pair\n\nglobal base: Pair = Pair{left: 1, right: 2}\nglobal table: Pair[2] = [base, Pair{left: 3, right: 4}]\nglobal picked: Pair = table[1]\nglobal wrapped: Holder = Holder{pair: table[0]}\nglobal first_left: i32 = table[0].left\n\ndef main() -> i64:\n    return picked.left.i64() + wrapped.pair.right.i64() + first_left.i64()\n' '^@picked = global %Pair { i32 3, i32 4 }'

# Typed non-call externs are C globals. Stage0 lowers the declaration to an external
# LLVM global and accesses it through ordinary loads/stores; keep all three shapes in
# the differential IR suite because these paths are not safely runnable without a C
# definition for the symbol.
ir_case extern_global_decl 'extern errno_value: i32\n\ndef main() -> i64:\n    return 42\n' '^@errno_value = external global i32'
ir_case extern_global_read 'extern errno_value: i32\n\ndef main() -> i64:\n    return errno_value + 42\n' 'load i32, ptr @errno_value'
ir_case extern_global_write 'extern errno_value: i32\n\ndef main() -> i64:\n    errno_value <- 7\n    return 42\n' 'store i32 7, ptr @errno_value'

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

stage1_ir_env_case() {
    local name="$1" env_name="$2" env_value="$3" src="$4" pattern="$5"
    total=$((total + 1))
    local ll="$BUILD/s1ir_${name}.ll"
    if ! env "$env_name=$env_value" printf '%b' "$src" | env "$env_name=$env_value" "$BUILD/emit_native" > "$ll" 2>/dev/null; then
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
# An optional POINTER is NICHE-OPTIMIZED to a bare pointer — null IS absent — which is
# what stage0 emits (`%p = alloca ptr`, presence via `icmp ne ptr %p1, null`). These two
# cases previously asserted the `{i1, ptr}` TAGGED shape, which stage0 never produced:
# they pinned a stage1 DIVERGENCE, and the difference is ABI-visible (a struct field after
# an optional ref sat at offset 16 instead of 8). Assert the SHAPE, not the SSA names,
# since those legitimately differ between the two compilers.
stage1_ir_case extern_optional_ptr_niche_alloca 'extern malloc(n: usize) -> mutable heap void&?\n\ndef main() -> i64:\n    p: mutable heap void&? = malloc(64)\n    if p is real:\n        return 7\n    return 3\n' '%p = alloca ptr'
stage1_ir_case extern_optional_ptr_null_tag 'extern malloc(n: usize) -> mutable heap void&?\n\ndef main() -> i64:\n    p: mutable heap void&? = malloc(64)\n    if p is real:\n        return 7\n    return 3\n' 'icmp ne ptr %[a-zA-Z0-9._]+, null'
# The REGRESSION guard: no tagged optional aggregate may reappear for a pointer payload.
stage1_ir_absent_case extern_optional_ptr_not_tagged 'extern malloc(n: usize) -> mutable heap void&?\n\ndef main() -> i64:\n    p: mutable heap void&? = malloc(64)\n    if p is real:\n        return 7\n    return 3\n' 'alloca \{ i1, ptr \}'
# An ordinary (never-null) ref keeps the CONSTANT tag -- the null test is for heap pointers
# only, and widening it to all refs would be a silent behavior change.
# A PLAIN `T&?` niches exactly like a heap one — stage0 gives `%r = alloca ptr` and a null
# test, with no `store i1 true` anywhere. The old assertion demanded that constant tag.
stage1_ir_case optional_plain_ref_niche_alloca 'def main() -> i64:\n    v: i64 = 5\n    r: i64&? = &v\n    if r is real:\n        return 7\n    return 3\n' '%r = alloca ptr'
stage1_ir_absent_case optional_plain_ref_not_tagged 'def main() -> i64:\n    v: i64 = 5\n    r: i64&? = &v\n    if r is real:\n        return 7\n    return 3\n' 'store i1 true'
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

# Function decorators are semantic declarations that stage0 lowers into LLVM function
# attributes. Keep these checks on stage1's IR because LLVM may renumber attribute groups
# between the two backend implementations; the source spellings and LLVM names are taken
# from stage0's llvm_inline_test.go.
stage1_ir_case function_attr_alwaysinline '@inline(always)\ndef helper(value: i64) -> i64:\n    return value + 1\n\ndef main() -> i64:\n    return helper(1)\n' 'alwaysinline'
stage1_ir_case function_attr_noinline '@inline(never)\ndef helper() -> i64:\n    return 1\n\ndef main() -> i64:\n    return helper()\n' 'noinline'
stage1_ir_case function_attr_hot '@hot\ndef helper(value: i64) -> i64:\n    return value + 1\n\ndef main() -> i64:\n    return helper(1)\n' 'hot'
stage1_ir_case function_attr_cold '@cold\ndef helper(value: i64) -> i64:\n    return value + 1\n\ndef main() -> i64:\n    return helper(1)\n' 'cold'
stage1_ir_case function_attr_norecurse '@norecurse\ndef helper(value: i64) -> i64:\n    return value + 1\n\ndef main() -> i64:\n    return helper(1)\n' 'norecurse'
stage1_ir_case function_fast_math '@fast_math\ndef helper(value: f64) -> f64:\n    return value * value + value\n\ndef main() -> i64:\n    return 42\n' 'fmul fast'
stage1_ir_case function_callconv_winapi '@callconv(winapi)\ndef helper(value: i64) -> i64:\n    return value + 1\n\ndef main() -> i64:\n    return 42\n' 'define (internal )?x86_stdcallcc i64 @helper'
stage1_ir_case function_segment_marker '@segment_agnostic\ndef helper(value: i64) -> i64:\n    return value + 1\n\ndef main() -> i64:\n    return 42\n' 'elisacore.segment_agnostic'
stage1_ir_case function_nounwind 'def helper(value: i64) -> i64:\n    return value + 1\n\ndef main() -> i64:\n    return helper(1)\n' 'attributes #[0-9]+ = \{ nounwind'
stage1_ir_case branch_weights_likely 'def helper(value: bool) -> i64:\n    if likely value:\n        return 1\n    return 0\n\ndef main() -> i64:\n    return helper(true)\n' 'branch_weights.*2000.*1'
stage1_ir_case branch_weights_unlikely 'def helper(value: bool) -> i64:\n    while unlikely value:\n        return 1\n    return 0\n\ndef main() -> i64:\n    return helper(true)\n' 'branch_weights.*1.*2000'
stage1_ir_case intrinsic_ctpop '@intrinsic(llvm.ctpop.i64)\nextern popcount(value: u64) -> u64\n\ndef main() -> i64:\n    return popcount(15).i64()\n' 'declare i64 @llvm.ctpop.i64\(i64\)'
stage1_ir_case darray_checked_growth 'def main() -> i64:\n    xs: mutable darray[i64] = []\n    xs.push(7)\n    return xs[0] can Unsafe.UncheckedIndex\n' 'umul.with.overflow.i64'
stage1_ir_case darray_checked_reserve_bound 'def main() -> i64:\n    xs: mutable darray[i64] = []\n    xs.reserve(2 * 3)\n    return xs.count.i64() + 42\n' 'umul.with.overflow.i64'
stage1_ir_case defer_function '@link_name(sink)\nextern sink(value: i64) -> void\n\ndef keep() -> i64:\n    value: i64 = 10\n    defer function:\n        sink(value)\n    return value\n\ndef main() -> i64:\n    return keep()\n' 'call void @sink\(i64.*\)'
stage1_ir_case defer_block_pool 'struct ThreadPool:\n    handle: void&?\n\ndef pool_new(threads: usize) -> ThreadPool:\n    return ThreadPool{handle: null}\n\ndef pool_shutdown(pool: ThreadPool&) -> void:\n    return\n\ndef observe(pool: ThreadPool&) -> void:\n    return\n\ndef keep() -> void:\n    pool workers(1):\n        defer block:\n            observe(&workers)\n\ndef main() -> i64:\n    keep()\n    return 42\n' 'call void @observe'
stage1_ir_case struct_align '@align(64)\nstruct Counter:\n    value: i64\n\nglobal counter: Counter = zeroed\n\ndef fold() -> i64:\n    local: Counter = zeroed\n    return local.value\n\ndef main() -> i64:\n    return fold()\n' '@counter = global %Counter zeroinitializer, align 64'
stage1_ir_env_case noalias_mutable_scalar ELISACORE_NOALIAS_MUTABLE_REFS 1 'def bump(x: mutable i32&) -> void:\n    x <- x + 1\n\ndef main() -> i64:\n    return 0\n' 'define (internal )?void @bump\(ptr noalias'
stage1_ir_absent_case noalias_default_off 'def bump(x: mutable i32&) -> void:\n    x <- x + 1\n\ndef main() -> i64:\n    return 0\n' 'define void @bump\(ptr noalias'
stage1_ir_env_case deref_guard_forced ELISACORE_FORCE_BOUNDS_CHECK 1 'struct P:\n    x: mutable i32\n\ndef read(p: P&) -> i32:\n    return p.x\n\ndef main() -> i64:\n    return 0\n' 'pg\.valid'
stage1_ir_absent_case deref_guard_default_off 'struct P:\n    x: mutable i32\n\ndef read(p: P&) -> i32:\n    return p.x\n\ndef main() -> i64:\n    return 0\n' 'pg\.valid'
stage1_ir_env_case index_guard_forced ELISACORE_FORCE_BOUNDS_CHECK 1 'def at(xs: mutable darray[i32]&, i: usize) -> i32:\n    return xs[i]\n\ndef main() -> i64:\n    return 0\n' 'wd\.in_bounds'
stage1_ir_env_case disjoint_darray_scopes ELISACORE_NOALIAS_MUTABLE_REFS 1 'def axpy(y: mutable darray[f64]&, x: mutable darray[f64]&) -> void:\n    y[0] <- x[0]\n\ndef main() -> i64:\n    a: mutable darray[f64] = []\n    b: mutable darray[f64] = []\n    axpy(&a, &b)\n    return 0\n' 'elisa\.disjoint\.axpy\.aa'
stage1_ir_absent_case disjoint_alias_call 'def axpy(y: mutable darray[f64]&, x: mutable darray[f64]&) -> void:\n    y[0] <- x[0]\n\ndef main() -> i64:\n    a: mutable darray[f64] = []\n    axpy(&a, &a)\n    return 0\n' 'elisa\.disjoint\.'
stage1_ir_env_case disjoint_clone_call ELISACORE_NOALIAS_MUTABLE_REFS 1 'def axpy(y: mutable darray[f64]&, x: mutable darray[f64]&) -> void:\n    y[0] <- x[0]\n\ndef main() -> i64:\n    a: mutable darray[f64] = []\n    b: mutable darray[f64] = clone[darray[f64]](a)\n    axpy(&a, &b)\n    return 0\n' 'elisa\.disjoint\.axpy\.aa'
stage1_ir_env_case disjoint_forwarded_call ELISACORE_NOALIAS_MUTABLE_REFS 1 'def axpy(y: mutable darray[f64]&, x: mutable darray[f64]&) -> void:\n    y[0] <- x[0]\n\ndef driver(y: mutable darray[f64]&, x: mutable darray[f64]&) -> void:\n    axpy(&y, &x)\n    y[0] <- x[0]\n\ndef main() -> i64:\n    a: mutable darray[f64] = []\n    b: mutable darray[f64] = []\n    driver(&a, &b)\n    return 0\n' 'elisa\.disjoint\.driver\.aa'
# A plain for-loop is NOT a comprehension build loop and must NOT be tagged: a marker there
# would make -Wperf demand vectorization of a loop the language never promised to vectorize.
stage1_ir_absent_case autovec_not_plain_loop 'def main() -> i64:\n    total: mutable i64 = 0\n    for i in 0..<10:\n        total <- total + i\n    return total - 3\n' 'elisa.autovec.expected'
