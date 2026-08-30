#!/usr/bin/env bash
# Stage1 REAL-STD InlineVec smoke: compile the ACTUAL elisacore_std InlineVec[T, N: usize]
# (small-buffer vector: N inline slots + a darray overflow that it spills into) through the
# stage1 backend and assert its real BEHAVIOR (exit code). InlineVec is the FOURTH advanced
# std container to run end-to-end (after Slice, Deque, IndexMap) and the one that needed
# CONST-GENERICS: `N: usize` is a VALUE type parameter, threaded via a phantom ConstUsize —
# annotation_value_type(IntLit)→ConstUsize, fold_const_atom reads the binding to size `T[N]`,
# the ident emitter folds `N` used as a value (`vec.len < N`), and the mangler spells it (`n4`).
RUN() { if command -v timeout >/dev/null 2>&1; then timeout 15 "$@"; else "$@"; fi; }
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISACORE_BIN="${ELISACORE_BIN:-$ROOT/../../Go projects/structpy-tree/compiler/bin/elisac}"
LLVM_CONFIG="${LLVM_CONFIG:-/opt/homebrew/opt/llvm/bin/llvm-config}"
STD="${ELISA_CORE:-$ROOT/../../Go projects/structpy-tree}/compiler/runtime/elisacore_std"

[ -x "$ELISACORE_BIN" ] || { echo "inlinevec_real_smoke SKIP: no elisac"; exit 0; }
[ -x "$LLVM_CONFIG" ] || { echo "inlinevec_real_smoke SKIP: no llvm-config"; exit 0; }
[ -f "$STD/collections.elisa" ] || { echo "inlinevec_real_smoke SKIP: no collections.elisa at $STD"; exit 0; }
command -v python3 >/dev/null 2>&1 || { echo "inlinevec_real_smoke SKIP: no python3"; exit 0; }

LIBDIR="$("$LLVM_CONFIG" --libdir)"
LLC="$(dirname "$LLVM_CONFIG")/llc"
BUILD="$ROOT/build"; mkdir -p "$BUILD"
EMIT="$BUILD/emit_native"

if [ ! -x "$EMIT" ]; then
    "$ELISACORE_BIN" -emit obj -O2 -o "$BUILD/emit_native.o" "$ROOT/test/breadth/emit_native.elisa" 2>/dev/null \
        && clang -o "$EMIT" "$BUILD/emit_native.o" -L"$LIBDIR" -lLLVM -Wl,-rpath,"$LIBDIR" 2>/dev/null
fi
[ -x "$EMIT" ] || { echo "inlinevec_real_smoke FAILED: no emit_native"; exit 1; }
RUNTIME_OBJ="$BUILD/runtime/elisacore_runtime.o"
if [ ! -f "$RUNTIME_OBJ" ]; then
    mkdir -p "$BUILD/runtime"
    printf 'def main() -> i64:\n    d: mutable darray[u8] = []\n    d.push(1)\n    return 0\n' > "$BUILD/runtime/probe.elisa"
    ( cd "$BUILD/runtime" && "$ELISACORE_BIN" -emit c-archive -o probe.a probe.elisa 2>/dev/null && ar x probe.a elisacore_runtime.o 2>/dev/null )
fi
[ -f "$RUNTIME_OBJ" ] || { echo "inlinevec_real_smoke FAILED: no elisacore_runtime.o"; exit 1; }

pass=0; total=0
iv_case() {
    local name="$1" body="$2" want="$3"; total=$((total + 1))
    local src="$BUILD/ivreal_$name.elisa" ll="$BUILD/ivreal_$name.ll" obj="$BUILD/ivreal_$name.o" exe="$BUILD/ivreal_$name"
    python3 - "$STD/arena.elisa" "$STD/deque.elisa" "$STD/collections.elisa" > "$src" <<PY
import sys, re
out = []
for path in sys.argv[1:]:
    for line in open(path):
        if not line.startswith('include'): out.append(line)
lines = ''.join(out).split('\n'); res = []; skip = False
for ln in lines:
    if re.match(r'def (ctx_hash_u64|ctx_hash_cstr)\b', ln): skip = True; continue
    if skip:
        if ln and not ln[0].isspace(): skip = False
        else: continue
    res.append(ln)
print('extern ctx_hash_cstr(s: cstr) -> u64')
print('extern ctx_hash_u64(value: u64) -> u64')
print('\n'.join(res))
print('''$body''')
PY
    if ! "$ELISACORE_BIN" -emit llvm -o /dev/null "$src" 2>"$BUILD/ivreal_$name.s0log"; then
        echo "  FAIL $name: FIXTURE INVALID -- stage0 rejects the InlineVec program:"
        grep -v warning "$BUILD/ivreal_$name.s0log" | head -3 | sed 's/^/      /'
        return; fi
    if ! "$EMIT" < "$src" > "$ll" 2>/dev/null || grep -q UNSUPPORTED "$ll"; then
        echo "  FAIL $name: stage1 declined the real-std InlineVec program"; return; fi
    if ! "$LLC" -filetype=obj "$ll" -o "$obj" 2>/dev/null; then
        echo "  FAIL $name: llc rejected the emitted IR"; return; fi
    if ! clang -Wl,-dead_strip -o "$exe" "$obj" "$RUNTIME_OBJ" 2>/dev/null; then
        echo "  FAIL $name: link failed (an instantiation body declined?)"; return; fi
    RUN "$exe"; local got=$?
    if [ "$got" -eq 124 ]; then echo "  FAIL $name: TIMED OUT"; return; fi
    if [ "$got" -ne "$want" ]; then echo "  FAIL $name: exit $got, want $want"; return; fi
    pass=$((pass + 1))
}

# stays INLINE (2 < N=4): push two, read both back through the fixed T[N] buffer. 40 + 2.
iv_case inline 'def main() -> i64 can[Memory.Allocate, Abort.Panic]:
    arena: mutable Arena = zeroed
    v: mutable InlineVec[i64, 4] = inline_vec[i64, 4](&arena)
    inline_vec_push[i64, 4](&v, 40)
    inline_vec_push[i64, 4](&v, 2)
    return inline_vec_get[i64, 4](&v, 0) + inline_vec_get[i64, 4](&v, 1)' 42
# SPILLS (6 > N=4): pushes past the inline capacity into the darray overflow; reads across
# the inline/overflow boundary (index 0 is inline, index 5 is spilled). 0 + 50 - 8 = 42.
iv_case spill 'def main() -> i64 can[Memory.Allocate, Abort.Panic]:
    arena: mutable Arena = zeroed
    v: mutable InlineVec[i64, 4] = inline_vec[i64, 4](&arena)
    for i in 0..<6:
        inline_vec_push[i64, 4](&v, i * 10)
    return inline_vec_get[i64, 4](&v, 0) + inline_vec_get[i64, 4](&v, 5) - 8' 42
# count reflects every push, inline AND spilled (6 + 36 = 42).
iv_case count 'def main() -> i64 can[Memory.Allocate, Abort.Panic]:
    arena: mutable Arena = zeroed
    v: mutable InlineVec[i64, 4] = inline_vec[i64, 4](&arena)
    for i in 0..<6:
        inline_vec_push[i64, 4](&v, i)
    return inline_vec_count[i64, 4](&v).i64() + 36' 42
# a DIFFERENT N (8) must mangle distinctly (n8 vs n4) and size its own T[N] — both live in
# one program, proving the const value is part of the instantiation identity. 40 + 2 = 42.
iv_case two_caps 'def main() -> i64 can[Memory.Allocate, Abort.Panic]:
    arena: mutable Arena = zeroed
    a: mutable InlineVec[i64, 4] = inline_vec[i64, 4](&arena)
    b: mutable InlineVec[i64, 8] = inline_vec[i64, 8](&arena)
    inline_vec_push[i64, 4](&a, 40)
    inline_vec_push[i64, 8](&b, 2)
    return inline_vec_get[i64, 4](&a, 0) + inline_vec_get[i64, 8](&b, 0)' 42

if [ "$pass" -eq "$total" ]; then
    echo "inlinevec_real_smoke OK: $pass/$total real-std InlineVec[T, N] programs compile+run correctly"
else
    echo "inlinevec_real_smoke FAILED: $pass/$total"; exit 1
fi
