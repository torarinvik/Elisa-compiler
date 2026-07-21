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
    clang -o "$dir/prog" "$dir/stage1_out.o" "$RUNTIME_OBJ" 2>/dev/null \
      || { echo "  FAIL obj_$name: link"; return; }
    RUN "$dir/prog"; local got=$?
    if [ "$got" -ne "$want" ]; then echo "  FAIL obj_$name: got $got want $want"; return; fi
    pass=$((pass + 1))
}

obj_case scalar   'def add(a: i64, b: i64) -> i64:\n    return a + b\n\ndef main() -> i64:\n    return add(40, 2)\n' 42

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
dwarf_case names_the_function 'DW_AT_name.*"add"'
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
