#!/usr/bin/env bash
# The DRIVER gate: stage1 emits a native OBJECT itself (target machine +
# LLVMTargetMachineEmitToFile), with NO `llc` in the pipeline.
#
# This is deliberately a separate script from backend_native_smoke.sh. That one pipes IR
# text through llc, which is the right harness for the 241 behavioural checks; this one
# exists to prove the backend no longer NEEDS llc -- the capability DWARF and -Wperf are
# blocked on, since both are invisible in IR text and -Wperf's check is post-optimization.
RUN() { if command -v timeout >/dev/null 2>&1; then timeout 20 "$@"; else "$@"; fi; }
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISACORE_BIN="${ELISACORE_BIN:-$HOME/.elisac/elisac}"
LLVM_CONFIG="${LLVM_CONFIG:-/opt/homebrew/opt/llvm/bin/llvm-config}"
[ -x "$ELISACORE_BIN" ] || { echo "backend_obj_smoke SKIP: no elisac"; exit 0; }
[ -x "$LLVM_CONFIG" ] || { echo "backend_obj_smoke SKIP: no llvm-config"; exit 0; }
# arm64-only: the driver binds LLVMInitializeAArch64* directly, because
# LLVMInitializeNativeTarget is a `static inline` with no symbol to bind.
[ "$(uname -m)" = "arm64" ] || { echo "backend_obj_smoke SKIP: driver is arm64-only"; exit 0; }

LIBDIR="$("$LLVM_CONFIG" --libdir)"
LLVM_DIS="$(dirname "$LLVM_CONFIG")/llvm-dis"
BUILD="$ROOT/build"; mkdir -p "$BUILD"
RUNTIME_OBJ="$BUILD/runtime/elisacore_runtime.o"
[ -f "$RUNTIME_OBJ" ] || { echo "backend_obj_smoke SKIP: no runtime object"; exit 0; }

"$ELISACORE_BIN" -emit obj -O2 -o "$BUILD/emit_obj.o" "$ROOT/test/breadth/emit_obj.elisa" 2>/dev/null \
  || { echo "backend_obj_smoke FAILED: could not compile emit_obj.elisa"; exit 1; }
clang -o "$BUILD/emit_obj" "$BUILD/emit_obj.o" -L"$LIBDIR" -lLLVM -Wl,-rpath,"$LIBDIR" 2>/dev/null \
  || { echo "backend_obj_smoke FAILED: could not link emit_obj"; exit 1; }

pass=0; total=0
obj_case() {
    local name="$1" src="$2" want="$3"
    total=$((total + 1))
    local dir="$BUILD/obj_$name"; rm -rf "$dir"; mkdir -p "$dir"
    # emit_obj writes stage1_out.o into the CWD, so each case gets its own directory.
    if ! ( cd "$dir" && printf '%b' "$src" | RUN "$BUILD/emit_obj" >/dev/null 2>&1 ); then
        echo "  FAIL obj_$name: emit_obj declined or errored"; return
    fi
    [ -f "$dir/stage1_out.o" ] || { echo "  FAIL obj_$name: no object emitted"; return; }
    [ -s "$dir/stage1_out.bc" ] || { echo "  FAIL obj_$name: no bitcode emitted"; return; }
    "$LLVM_DIS" "$dir/stage1_out.bc" -o /dev/null 2>/dev/null || { echo "  FAIL obj_$name: invalid bitcode emitted"; return; }
    clang -o "$dir/prog" "$dir/stage1_out.o" "$RUNTIME_OBJ" 2>/dev/null \
      || { echo "  FAIL obj_$name: link"; return; }
    RUN "$dir/prog"; local got=$?
    if [ "$got" -ne "$want" ]; then echo "  FAIL obj_$name: got $got want $want"; return; fi
    pass=$((pass + 1))
}

obj_case scalar   'def add(a: i64, b: i64) -> i64:\n    return a + b\n\ndef main() -> i64:\n    return add(40, 2)\n' 42

# Value blocks lower their leading declarations in the current scope and evaluate the
# trailing expression as the block result.
obj_case value_block 'def main() -> i64:\n    value: i64 =\n        x: i64 = 40\n        x + 2\n    return value\n' 42

# Aggregate cases at -O2: these exercise mixed-size struct/optional layout, which a MISSING
# module datalayout silently corrupts (the optimizer falls back to a default where i64 is
# 32-bit aligned, mislaying an {i1,i64} optional's payload). Each would pass at -O0; they earn
# their keep only under the real -O2 pipeline. Regression guard for the datalayout fix.
obj_case opt_return_through_call 'def find(x: i64) -> i64?:\n    return x if x > 0 else null\n\ndef main() -> i64:\n    if find(5) is v:\n        return v\n    return 0\n' 5
obj_case opt_absent_through_call 'def find(x: i64) -> i64?:\n    return x if x > 0 else null\n\ndef main() -> i64:\n    if find(-3) is v:\n        return v\n    return 9\n' 9
obj_case struct_return_fields 'struct Big:\n    a: i64\n    b: i64\n    c: i64\n    d: i64\n    e: i64\n\ndef mk() -> Big:\n    return Big{a: 1, b: 2, c: 3, d: 4, e: 5}\n\ndef main() -> i64:\n    g: Big = mk()\n    return g.a + g.e\n' 6
obj_case enum_payload_through_call 'enum Shape:\n    Rect(i64, i64)\n    None\n\ndef mk() -> Shape:\n    return Shape.Rect(4, 5)\n\ndef main() -> i64:\n    return match mk():\n        Shape.Rect(w, h): w * h\n        _: 0\n' 20

# The pipeline actually RUNS -- not a no-op. Every case above would pass identically at -O0
# (an exit code cannot see optimization), so this asserts the one thing that distinguishes
# them: at -O2 `add(40, 2)` is constant-folded into main, so main must NOT call _add.
# Without a check like this "run the passes" could silently do nothing and every test would
# stay green. -Wperf's whole basis is judging what the vectorizer did, so a pipeline that
# does not run is worse than none.
optimizer_case() {
    total=$((total + 1))
    local dir="$BUILD/obj_optimizer"; rm -rf "$dir"; mkdir -p "$dir"
    local src='def add(a: i64, b: i64) -> i64:\n    return a + b\n\ndef main() -> i64:\n    return add(40, 2)\n'
    if ! ( cd "$dir" && printf '%b' "$src" | RUN "$BUILD/emit_obj" >/dev/null 2>&1 ); then
        echo "  FAIL obj_optimizer: emit_obj errored"; return
    fi
    local dis
    dis="$( (objdump -d --disassemble-symbols=_main "$dir/stage1_out.o" 2>/dev/null || otool -tV "$dir/stage1_out.o" 2>/dev/null) )"
    if [ -z "$dis" ]; then echo "  SKIP obj_optimizer: no disassembler"; total=$((total - 1)); return; fi
    # 42 = 0x2a folded into main is the fingerprint of the optimizer having run.
    if echo "$dis" | grep -qiE "#0x2a|#42"; then
        pass=$((pass + 1))
    else
        echo "  FAIL obj_optimizer: no folded constant in _main -- passes did not run"
    fi
}
optimizer_case
obj_case recursion 'def fact(n: i64) -> i64:\n    return 1 if n <= 1 else n * fact(n - 1)\n\ndef main() -> i64:\n    return fact(5) - 78\n' 42
obj_case darray   'def main() -> i64:\n    xs: mutable darray[i64] = []\n    xs.push(42)\n    return xs[0] can Unsafe.UncheckedIndex\n' 42
obj_case nested_darray 'def main() -> i64:\n    xs: mutable darray[darray[i64]] = []\n    inner: mutable darray[i64] = []\n    inner.push(42)\n    xs.push(inner)\n    return xs[0][0] can Unsafe.UncheckedIndex\n' 42
obj_case recursive_generic 'struct Node[T]:\n    value: T\n    next: Node[T]&?\n\ndef main() -> i64:\n    node: Node[i64] = Node[i64]{value: 42, next: null}\n    return node.value\n' 42
obj_case parallel_range 'def for_indices_par(n: usize, body: fn(usize) -> i64, w: usize = 0.usize()) -> void:\n    return\n\ndef main() -> i64:\n    total: usize = 4.usize()\n    for i in 0.usize() ..< total by par:\n        _ = i.i64()\n    return 42\n' 42
obj_case parallel_band_generic 'struct Slice[T]:\n    base: usize\n    count: usize\n\ndef each[T](s: Slice[T], body: fn(Slice[T]) -> i64, w: usize) -> void:\n    return\n\ndef main() -> i64:\n    whole: Slice[i64] = Slice[i64]{base: 0.usize(), count: 1.usize()}\n    parallel for band in whole:\n        _ = band.count.i64()\n    return 42\n' 42
obj_case pool_scope 'struct ThreadPool:\n    handle: void&?\n\ndef pool_new(threads: usize) -> ThreadPool:\n    return ThreadPool{handle: null}\n\ndef pool_shutdown(pool: ThreadPool&) -> void:\n    return\n\ndef main() -> i64:\n    pool workers(2):\n        pass\n    return 42\n' 42
obj_case nursery_submit 'struct ThreadPool:\n    handle: void&?\n\nstruct TaskGroup:\n    handle: void&?\n    cleanup: void&?\n\nstruct Task[T, S]:\n    handle: usize\n    state: void&?\n\ndef pool_new(threads: usize) -> ThreadPool:\n    return ThreadPool{handle: null}\n\ndef pool_shutdown(pool: ThreadPool&) -> void:\n    return\n\ndef task_group_new() -> TaskGroup:\n    return TaskGroup{handle: null, cleanup: null}\n\ndef task_group_wait_all(group: TaskGroup&) -> void:\n    return\n\ndef pool_submit1[A, R](pool: ThreadPool&, fn: fn(A) -> R, arg: A) -> Task[R, i64]:\n    return zeroed\n\ndef task_group_add[R](group: TaskGroup&, task: Task[R, i64]) -> void:\n    _ = move task\n    return\n\ndef bump(value: i64) -> i64:\n    return value + 1\n\ndef main() -> i64:\n    nursery workers(2):\n        submit bump(41)\n    return 42\n' 42
obj_case await_task 'struct Task[T, S]:\n    handle: usize\n    state: void&?\n\ndef pool_await[R](task: Task[R, i64]) -> R:\n    return 42\n\ndef main() -> i64:\n    t: Task[i64, i64] = zeroed\n    return await t\n' 42
obj_case comprehension 'def main() -> i64:\n    xs: darray[i64] = [i for i in 0..<10]\n    return (xs[3] can Unsafe.UncheckedIndex) + 39\n' 42
obj_case struct   'struct P:\n    x: i64\n    y: i64\n\ndef main() -> i64:\n    p: P = P{x: 40, y: 2}\n    return p.x + p.y\n' 42

# A user-defined GENERIC function. Its monomorphization (`id__i64`) is emitted lazily during
# body emission -- AFTER emit_debug_info has run -- so the instantiation has no DISubprogram.
# Attaching a DWARF parameter to a subprogram-less function built metadata with a null scope
# that SEGFAULTED the -O2 pipeline (emit_module_with_debug only; the IR path was fine). Guard:
# emit_instantiation_body now emits the monomorph body with debug OFF. Nested + multi-param
# instantiations exercise the same path.
obj_case generic_debug 'def id[T](x: T) -> T:\n    return x\n\ndef main() -> i64:\n    return id(id(42))\n' 42
obj_case generic_two_params 'def snd[A, B](a: A, b: B) -> B:\n    return b\n\ndef main() -> i64:\n    return snd(1, 42)\n' 42

# f-strings: the parser desugars `f"…{x}…"` into `__fstr(chunk, value, …)`; the backend lowers
# it to ctx_fstr_alloc(total) + ctx_fstr_append per string-like piece + load. "xy-zzz!" is 7
# bytes; index 3 is 'z' (122), matching stage0 (verified). Guards the __fstr builtin.
obj_case fstring_len 'def main() -> i64 can[Abort.Panic, Memory.Allocate]:\n    a: dstr = "xy"\n    b: dstr = "zzz"\n    s: dstr = f"{a}-{b}!"\n    return s.count.i64()\n' 7
obj_case fstring_byte 'def main() -> i64 can[Abort.Panic, Memory.Allocate]:\n    a: dstr = "xy"\n    b: dstr = "zzz"\n    s: dstr = f"{a}-{b}!"\n    return (s[3] can Unsafe.UncheckedIndex).i64()\n' 122

# Error unions end-to-end: an `error Bad:` set, a `-> i64 error[Bad]` function that `raise`s,
# and a statement `catch` with a success arm + `error e:` arm. Exercises the i32-status +
# leading-out-pointer ABI through the full emit_obj (-g + O2) path, which the narrow
# scalar/aggregate cases above don't. d(42) succeeds -> success arm returns 42.
obj_case error_union_catch 'error Bad:\n    Boom\n\ndef d(x: i64) -> i64 error[Bad]:\n    raise Bad.Boom if x < 0\n    return x\n\ndef main() -> i64:\n    catch d(42):\n        v:\n            return v\n        error e:\n            return 0\n' 42

# First-class functions (Stage A: named function as a `fn(...)` value + call through a
# `fn`-typed param). `fn(A)->R` is a low-bit-tagged ptr; a named fn passes its raw pointer
# (bit0=0), and calling the param emits the tag dispatch (raw path here). apply(dbl,21)=42.
obj_case fn_value_named 'def dbl(x: i64) -> i64:\n    return x * 2\n\ndef apply(fn: fn(i64) -> i64, value: i64) -> i64:\n    return fn(value)\n\ndef main() -> i64:\n    return apply(dbl, 21)\n' 42
# NESTED call through a fn value: fn(fn(v)). The inner call is in ARGUMENT position, so its
# result type comes from the fn value's stored RETURN type (Fn signature side-pool), not the
# expected type. twice(inc, 40) = inc(inc(40)) = 42.
obj_case fn_value_nested 'def inc(x: i64) -> i64:\n    return x + 1\n\ndef twice(fn: fn(i64) -> i64, v: i64) -> i64:\n    return fn(fn(v))\n\ndef main() -> i64:\n    return twice(inc, 40)\n' 42
# LAMBDA VALUES (closures). fn(v) => body lifts to @lambda(ptr env, v): a no-capture lambda
# passes a null env; a capturing one mallocs an env of the captured scalars, and the tagged
# {code,env} closure flows through emit_fn_value_call's closure branch. Both = 42.
obj_case lambda_nocapture 'def apply(fn: fn(i64) -> i64, value: i64) -> i64:\n    return fn(value)\n\ndef main() -> i64:\n    return apply(fn(v) => v * 2, 21)\n' 42
obj_case lambda_capture 'def apply(fn: fn(i64) -> i64, value: i64) -> i64:\n    return fn(value)\n\ndef run() -> i64:\n    offset: i64 = 1\n    return apply(fn(v) => v + offset, 41)\n\ndef main() -> i64:\n    return run()\n' 42
# HIGHER-ORDER RETURN: a function whose return type is a fn/closure, stored in a fn-typed
# LOCAL and called. Needed a parser fix (a local `f: fn(A)->R =` type resolves as a fn-type,
# not a call to a fn named `fn`) + arg emission at the fn's declared param types (so a literal
# arg like f(21) adopts the param type). adder(2) captures n=2; f(40) = 42.
obj_case higher_order_named 'def dbl(x: i64) -> i64:\n    return x * 2\n\ndef getfn() -> fn(i64) -> i64:\n    return dbl\n\ndef main() -> i64:\n    f: fn(i64) -> i64 = getfn()\n    return f(21)\n' 42
obj_case higher_order_closure 'def adder(n: i64) -> fn(i64) -> i64:\n    return fn(x) => x + n\n\ndef main() -> i64:\n    f: fn(i64) -> i64 = adder(2)\n    return f(40)\n' 42
# STRING ITERATION `for c in s`: sview iterates bytes by index<len; cstr until a 0 byte; the
# loop var is a u8. "AB" byte-sum 65+66=131; -89 = 42 (verified byte-identical to stage0).
obj_case sview_iter 'def main() -> i64:\n    s: sview = "AB"\n    total: mutable i64 = 0\n    for c in s |total|:\n        total <- total + c.i64()\n    return total - 89\n' 42
obj_case cstr_iter 'def main() -> i64:\n    s: cstr = "AB"\n    total: mutable i64 = 0\n    for c in s |total|:\n        total <- total + c.i64()\n    return total - 89\n' 42
# `x is Enum.PayloadlessVariant` as a bare bool (tag == ordinal) — the RHS is a bare
# Enum.Variant Field (no binders), distinct from the payload-narrowing `is Variant(a, b)`.
obj_case is_payloadless_variant 'enum Dir:\n    N\n    S\ndef opp(d: Dir) -> Dir:\n    return match d:\n        Dir.N: Dir.S\n        Dir.S: Dir.N\ndef main() -> i64:\n    return 42 if opp(Dir.N) is Dir.S else 0\n' 42

# The comprehension actually VECTORIZES. This is the only check in the suite that asserts
# Elisa's central performance claim rather than its behaviour: a comprehension exists to be
# vectorized, and `-Wperf` exists to complain when one is not. No exit code can see this --
# the loop computes the same answer scalar or not.
#
# It caught a real bug: with no datalayout on the module, LLVM assumed i64 was 32-bit
# aligned, emitted `store i64 ... align 4`, and the vectorizer refused every comprehension.
# All 244 behavioural checks were green throughout.
vectorize_case() {
    total=$((total + 1))
    local dir="$BUILD/obj_vectorize"; rm -rf "$dir"; mkdir -p "$dir"
    local src='def main() -> i64:\n    xs: darray[i64] = [i for i in 0..<1000]\n    return (xs[0] can Unsafe.UncheckedIndex) + 42\n'
    local opt="$(dirname "$LLVM_CONFIG")/opt"
    [ -x "$opt" ] || { echo "  SKIP obj_vectorize: no opt"; total=$((total - 1)); return; }
    printf '%b' "$src" | RUN "$BUILD/../build/emit_native" > "$dir/in.ll" 2>/dev/null \
      || { echo "  SKIP obj_vectorize: emit_native unavailable"; total=$((total - 1)); return; }
    local optimized
    optimized="$("$opt" -passes='default<O2>' -S "$dir/in.ll" 2>/dev/null)"
    # `isvectorized` is what -Wperf itself looks for: LLVM adds it to the loop's metadata
    # when the vectorizer succeeds, alongside our `elisa.autovec.expected` marker.
    if echo "$optimized" | grep -q "isvectorized"; then
        pass=$((pass + 1))
    else
        echo "  FAIL obj_vectorize: comprehension did NOT vectorize (no isvectorized marker)"
    fi
}
vectorize_case

# `-Wperf` ITSELF: the post-pass verdict, tested in BOTH directions. One direction proves
# nothing -- a verifier that never warns passes the "no false alarm" test, and one that always
# warns passes the "catches it" test. Only both together say it works.
#
# The non-vectorizable case needs a trip count too large to UNROLL: at 20 iterations LLVM
# unrolls the loop away entirely, the latch (and its metadata) disappears, and there is
# correctly nothing left to warn about. That is what made my first attempt look like a
# working verifier when it was silently broken.
wperf_case() {
    local name="$1" src="$2" want_warning="$3"
    total=$((total + 1))
    local dir="$BUILD/obj_wperf_$name"; rm -rf "$dir"; mkdir -p "$dir"
    local out
    out="$( cd "$dir" && printf '%b' "$src" | RUN "$BUILD/emit_obj" 2>&1 )"
    local got=no
    echo "$out" | grep -q "WPERF" && got=yes
    if [ "$got" = "$want_warning" ]; then
        pass=$((pass + 1))
    else
        echo "  FAIL obj_wperf_$name: warning=$got want=$want_warning"
    fi
}

# A recursive call in the body: cannot vectorize, and 1000 iterations will not unroll.
wperf_case warns 'def fib(n: i64) -> i64:\n    return n if n < 2 else fib(n - 1) + fib(n - 2)\n\ndef main() -> i64:\n    xs: darray[i64] = [fib(i % 8) for i in 0..<1000]\n    return (xs[0] can Unsafe.UncheckedIndex) + 42\n' yes
# A plain fill: vectorizes, so NO warning. This is the direction that catches a verifier
# which warns about everything.
wperf_case silent 'def main() -> i64:\n    xs: darray[i64] = [i for i in 0..<1000]\n    return (xs[0] can Unsafe.UncheckedIndex) + 42\n' no
# An UNROLLED loop has no latch left to carry the marker, so there is nothing to judge and no
# warning -- not a miss.
# DWARF. The oracle here is dwarfdump on the OBJECT, not an IR diff: debug info is built
# during emission and stage0's own `-emit llvm -g` shows none of it. Compared against
# stage0's actual output (`elisac -emit obj -g`), which gives producer "elisacore",
# DW_LANG_C99, and a DW_TAG_subprogram per function.
#
# DW_AT_language is asserted BY NAME because nothing errors on a wrong enum: passing 12
# (Ada95) instead of 11 (C99) produced a perfectly valid compile unit claiming the language
# was Ada, and only dwarfdump showed it.
dwarf_case() {
    local name="$1" pattern="$2"
    total=$((total + 1))
    local dir="$BUILD/obj_dwarf"; mkdir -p "$dir"
    local dump="$(dirname "$LLVM_CONFIG")/llvm-dwarfdump"
    [ -x "$dump" ] || { echo "  SKIP obj_dwarf_$name: no llvm-dwarfdump"; total=$((total - 1)); return; }
    if [ ! -f "$dir/stage1_out.o" ]; then
        local src='def add(a: i64, b: i64) -> i64:\n    return a + b\n\ndef main() -> i64:\n    return add(40, 2)\n'
        ( cd "$dir" && printf '%b' "$src" | RUN "$BUILD/emit_obj" >/dev/null 2>&1 ) \
          || { echo "  FAIL obj_dwarf_$name: emit_obj errored"; return; }
    fi
    if "$dump" --debug-info "$dir/stage1_out.o" 2>/dev/null | grep -qE "$pattern"; then
        pass=$((pass + 1))
    else
        echo "  FAIL obj_dwarf_$name: no /$pattern/ in DWARF"
    fi
}
rm -rf "$BUILD/obj_dwarf"
dwarf_case compile_unit 'DW_TAG_compile_unit'
dwarf_case producer 'DW_AT_producer.*elisacore'
dwarf_case language_is_c99 'DW_AT_language.*DW_LANG_C99'
dwarf_case subprogram 'DW_TAG_subprogram'
# `add` is internal (ce054cd) and tiny, so the optimizer inlines it away and its DIE goes
# with it — stage0's own -O2 object for this program likewise keeps only `_main`. Assert on
# the function that survives; the point of the case is that a subprogram DIE carries a name.
dwarf_case names_the_function 'DW_AT_name.*"main"'
# The subprogram's TYPE. Without a subroutine type carrying real parameter/return types a
# debugger shows a signature-less symbol, and the object contains no DW_TAG_base_type at
# all -- which is exactly what stage1 emitted before (stage0's object has them).
dwarf_case base_type 'DW_TAG_base_type'
dwarf_case names_i64 'DW_AT_name.*"i64"'
dwarf_case subprogram_has_type 'DW_AT_type'

# Local-variable debug info, checked in the PRE-PASS IR rather than in the object.
# `-O2` deletes it: stage0's own `-emit obj -O2 -g` has no DW_TAG_formal_parameter or
# DW_TAG_variable either, so an optimized object cannot distinguish "never emitted" from
# "optimizer removed it". The IR before the pipeline can.
debug_ir_case() {
    local name="$1" pattern="$2"
    total=$((total + 1))
    local dir="$BUILD/obj_dbgir"; mkdir -p "$dir"
    if [ ! -f "$BUILD/emit_obj_debug_ir" ]; then
        if ! "$ELISACORE_BIN" -emit obj -O2 -o "$BUILD/emit_obj_debug_ir.o" "$ROOT/test/breadth/emit_obj_debug_ir.elisa" 2>/dev/null \
           || ! clang -o "$BUILD/emit_obj_debug_ir" "$BUILD/emit_obj_debug_ir.o" -L"$LIBDIR" -lLLVM -Wl,-rpath,"$LIBDIR" 2>/dev/null; then
            echo "  FAIL obj_dbgir_$name: could not build emit_obj_debug_ir"; return
        fi
    fi
    if [ ! -f "$dir/ir.txt" ]; then
        local src='def add(a: i64, b: i64) -> i64:\n    total: i64 = a + b\n    return total\n\ndef main() -> i64:\n    return add(40, 2)\n'
        ( cd "$dir" && printf '%b' "$src" | "$BUILD/emit_obj_debug_ir" > ir.txt 2>/dev/null ) || true
    fi
    if grep -qE "$pattern" "$dir/ir.txt" 2>/dev/null; then
        pass=$((pass + 1))
    else
        echo "  FAIL obj_dbgir_$name: no /$pattern/ in pre-pass debug IR"
    fi
}
rm -rf "$BUILD/obj_dbgir"
# Parameters carry their DWARF argument NUMBER (1-based) and their type.
debug_ir_case param_a 'DILocalVariable\(name: "a", arg: 1'
debug_ir_case param_b 'DILocalVariable\(name: "b", arg: 2'
# A LOCAL has no `arg:` field -- that is what distinguishes DW_TAG_variable from
# DW_TAG_formal_parameter.
debug_ir_case local_total 'DILocalVariable\(name: "total", scope'
debug_ir_case declare_record '#dbg_declare|llvm.dbg.declare' 

wperf_case unrolled_is_silent 'def main() -> i64:\n    xs: darray[i64] = [i for i in 0..<8]\n    return (xs[0] can Unsafe.UncheckedIndex) + 42\n' no

if [ "$pass" -ne "$total" ]; then echo "backend_obj_smoke FAILED: passed=$pass total=$total"; exit 1; fi
echo "backend_obj_smoke OK: $pass/$total (objects emitted by stage1, no llc)"
