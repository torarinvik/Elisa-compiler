#!/usr/bin/env bash
# Stage1 REAL-STD Slice smoke: compile the ACTUAL elisacore_std Slice[T] API (the
# borrowed, disjoint-partitionable view — elisacore_runtime_slice.elisa) through the stage1
# backend and assert its real BEHAVIOR (exit code). Slice is the first advanced container to
# run end-to-end via UFCS-to-generic (`s.len()`, `s.get(i)`, `s.split(n, k)`) after
# slot-aware generic overload resolution + darray-param inference + ref-to-scalar indexing +
# address-of a darray-ref element all landed.
#
# Slice is declared in std source (no builtin asymmetry), so no prelude is needed — unlike
# set. The std is concatenated (arena + deque + collections + slice) with `include` lines
# stripped and the two ctx_hash_* definitions dropped (the runtime object provides them).
RUN() { if command -v timeout >/dev/null 2>&1; then timeout 15 "$@"; else "$@"; fi; }
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISACORE_BIN="${ELISACORE_BIN:-$ROOT/../../Go projects/structpy-tree/compiler/bin/elisac}"
LLVM_CONFIG="${LLVM_CONFIG:-/opt/homebrew/opt/llvm/bin/llvm-config}"
STD="${ELISA_CORE:-$ROOT/../../Go projects/structpy-tree}/compiler/runtime/elisacore_std"

[ -x "$ELISACORE_BIN" ] || { echo "slice_real_smoke SKIP: no elisac"; exit 0; }
[ -x "$LLVM_CONFIG" ] || { echo "slice_real_smoke SKIP: no llvm-config"; exit 0; }
[ -f "$STD/elisacore_runtime_slice.elisa" ] || { echo "slice_real_smoke SKIP: no slice std at $STD"; exit 0; }
command -v python3 >/dev/null 2>&1 || { echo "slice_real_smoke SKIP: no python3"; exit 0; }

LIBDIR="$("$LLVM_CONFIG" --libdir)"
LLC="$(dirname "$LLVM_CONFIG")/llc"
BUILD="$ROOT/build"; mkdir -p "$BUILD"
EMIT="$BUILD/emit_native"

if [ ! -x "$EMIT" ]; then
    "$ELISACORE_BIN" -emit obj -O2 -o "$BUILD/emit_native.o" "$ROOT/test/breadth/emit_native.elisa" 2>/dev/null \
        && clang -o "$EMIT" "$BUILD/emit_native.o" -L"$LIBDIR" -lLLVM -Wl,-rpath,"$LIBDIR" 2>/dev/null
fi
[ -x "$EMIT" ] || { echo "slice_real_smoke FAILED: no emit_native"; exit 1; }
RUNTIME_OBJ="$BUILD/runtime/elisacore_runtime.o"
if [ ! -f "$RUNTIME_OBJ" ]; then
    mkdir -p "$BUILD/runtime"
    printf 'def main() -> i64:\n    d: mutable darray[u8] = []\n    d.push(1)\n    return 0\n' > "$BUILD/runtime/probe.elisa"
    ( cd "$BUILD/runtime" && "$ELISACORE_BIN" -emit c-archive -o probe.a probe.elisa 2>/dev/null && ar x probe.a elisacore_runtime.o 2>/dev/null )
fi
[ -f "$RUNTIME_OBJ" ] || { echo "slice_real_smoke FAILED: no elisacore_runtime.o"; exit 1; }

pass=0; total=0
slice_case() {
    local name="$1" body="$2" want="$3"; total=$((total + 1))
    local src="$BUILD/slicereal_$name.elisa" ll="$BUILD/slicereal_$name.ll" obj="$BUILD/slicereal_$name.o" exe="$BUILD/slicereal_$name"
    python3 - "$STD/arena.elisa" "$STD/deque.elisa" "$STD/collections.elisa" "$STD/elisacore_runtime_slice.elisa" > "$src" <<PY
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
    if ! "$ELISACORE_BIN" -emit llvm -o /dev/null "$src" 2>"$BUILD/slicereal_$name.s0log"; then
        echo "  FAIL $name: FIXTURE INVALID -- stage0 rejects the slice program:"
        grep -v warning "$BUILD/slicereal_$name.s0log" | head -3 | sed 's/^/      /'
        return; fi
    if ! "$EMIT" < "$src" > "$ll" 2>/dev/null || head -1 "$ll" | grep -q UNSUPPORTED; then
        echo "  FAIL $name: stage1 declined the real-std slice program"; return; fi
    if ! "$LLC" -filetype=obj "$ll" -o "$obj" 2>/dev/null; then
        echo "  FAIL $name: llc rejected the emitted IR"; return; fi
    if ! clang -Wl,-dead_strip -o "$exe" "$obj" "$RUNTIME_OBJ" 2>/dev/null; then
        echo "  FAIL $name: link failed (an instantiation body declined?)"; return; fi
    RUN "$exe"; local got=$?
    if [ "$got" -eq 124 ]; then echo "  FAIL $name: TIMED OUT"; return; fi
    if [ "$got" -ne "$want" ]; then echo "  FAIL $name: exit $got, want $want"; return; fi
    pass=$((pass + 1))
}

# slice(&da) borrows the darray; len() reports the count via a UFCS generic method.
slice_case len 'def main() -> i64:
    xs: mutable darray[i64] = [10, 20, 12]
    s: Slice[i64] = slice(&xs)
    return s.len().i64() + 39' 42
# get(i) reads element i through the borrowed backing (ref-to-scalar indexing).
slice_case get 'def main() -> i64:
    xs: mutable darray[i64] = [10, 20, 12]
    s: Slice[i64] = slice(&xs)
    return s.get(0.usize()) + s.get(1.usize()) + s.get(2.usize())' 42
# get_unchecked(i) is the unchecked read variant (no bounds branch).
slice_case get_unchecked 'def main() -> i64:
    xs: mutable darray[i64] = [40, 2, 9]
    s: Slice[i64] = slice(&xs)
    return s.get_unchecked(0.usize()) + s.get_unchecked(1.usize())' 42

# split(n, k) returns the k-th of n disjoint bands; its len is the band size.
slice_case split 'def main() -> i64:
    xs: mutable darray[i64] = [1, 2, 3, 4, 5, 6]
    s: Slice[i64] = slice(&xs)
    b: Slice[i64] = s.split(2.usize(), 1.usize())
    return b.len().i64() + 39' 42
# set_unchecked(i, v) WRITES element i through the borrowed backing (ref-to-scalar store);
# the write is observed by a subsequent get and through the source darray.
slice_case set_unchecked 'def main() -> i64:
    xs: mutable darray[i64] = [1, 2, 3, 4]
    s: Slice[i64] = slice(&xs)
    s.set_unchecked(2.usize(), 42)
    return s.get(2.usize())' 42

if [ "$pass" -eq "$total" ]; then
    echo "slice_real_smoke OK: $pass/$total real-std Slice[T] programs compile+run correctly"
else
    echo "slice_real_smoke FAILED: $pass/$total"; exit 1
fi
