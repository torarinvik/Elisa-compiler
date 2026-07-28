#!/usr/bin/env bash
# Stage1 REAL-STD Deque smoke: compile the ACTUAL elisacore_std Deque[T] ring buffer
# (elisacore_runtime_deque.elisa) through the stage1 backend and assert its real BEHAVIOR
# (exit code). Deque is the SECOND advanced std container to run end-to-end (after Slice),
# via slot-aware overload resolution + the ref-typed-FIELD index (Deque.items is `T&?`, an
# optional-ref buffer pointer, indexed by arena_deque_at / push_back_assume_capacity).
#
# Deque is in std source (no prelude). The std is concatenated (arena + deque + collections)
# with `include` lines stripped and the two ctx_hash_* definitions dropped (runtime provides
# them). Programs must run their allocating body under `can[Memory.Allocate, Abort.Panic]`.
RUN() { if command -v timeout >/dev/null 2>&1; then timeout 15 "$@"; else "$@"; fi; }
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISACORE_BIN="${ELISACORE_BIN:-$HOME/.elisac/elisac}"
LLVM_CONFIG="${LLVM_CONFIG:-/opt/homebrew/opt/llvm/bin/llvm-config}"
STD="${ELISA_CORE:-$ROOT/../../Go projects/Elisa-core}/compiler/runtime/elisacore_std"

[ -x "$ELISACORE_BIN" ] || { echo "deque_real_smoke SKIP: no elisac"; exit 0; }
[ -x "$LLVM_CONFIG" ] || { echo "deque_real_smoke SKIP: no llvm-config"; exit 0; }
[ -f "$STD/deque.elisa" ] || { echo "deque_real_smoke SKIP: no deque std at $STD"; exit 0; }
command -v python3 >/dev/null 2>&1 || { echo "deque_real_smoke SKIP: no python3"; exit 0; }

LIBDIR="$("$LLVM_CONFIG" --libdir)"
LLC="$(dirname "$LLVM_CONFIG")/llc"
BUILD="$ROOT/build"; mkdir -p "$BUILD"
EMIT="$BUILD/emit_native"

if [ ! -x "$EMIT" ]; then
    "$ELISACORE_BIN" -emit obj -O2 -o "$BUILD/emit_native.o" "$ROOT/test/breadth/emit_native.elisa" 2>/dev/null \
        && clang -o "$EMIT" "$BUILD/emit_native.o" -L"$LIBDIR" -lLLVM -Wl,-rpath,"$LIBDIR" 2>/dev/null
fi
[ -x "$EMIT" ] || { echo "deque_real_smoke FAILED: no emit_native"; exit 1; }
RUNTIME_OBJ="$BUILD/runtime/elisacore_runtime.o"
if [ ! -f "$RUNTIME_OBJ" ]; then
    mkdir -p "$BUILD/runtime"
    printf 'def main() -> i64:\n    d: mutable darray[u8] = []\n    d.push(1)\n    return 0\n' > "$BUILD/runtime/probe.elisa"
    ( cd "$BUILD/runtime" && "$ELISACORE_BIN" -emit c-archive -o probe.a probe.elisa 2>/dev/null && ar x probe.a elisacore_runtime.o 2>/dev/null )
fi
[ -f "$RUNTIME_OBJ" ] || { echo "deque_real_smoke FAILED: no elisacore_runtime.o"; exit 1; }

pass=0; total=0
deque_case() {
    local name="$1" body="$2" want="$3"; total=$((total + 1))
    local src="$BUILD/dequereal_$name.elisa" ll="$BUILD/dequereal_$name.ll" obj="$BUILD/dequereal_$name.o" exe="$BUILD/dequereal_$name"
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
    if ! "$ELISACORE_BIN" -emit llvm -o /dev/null "$src" 2>"$BUILD/dequereal_$name.s0log"; then
        echo "  FAIL $name: FIXTURE INVALID -- stage0 rejects the deque program:"
        grep -v warning "$BUILD/dequereal_$name.s0log" | head -3 | sed 's/^/      /'
        return; fi
    if ! "$EMIT" < "$src" > "$ll" 2>/dev/null || head -1 "$ll" | grep -q UNSUPPORTED; then
        echo "  FAIL $name: stage1 declined the real-std deque program"; return; fi
    if ! "$LLC" -filetype=obj "$ll" -o "$obj" 2>/dev/null; then
        echo "  FAIL $name: llc rejected the emitted IR"; return; fi
    if ! clang -Wl,-dead_strip -o "$exe" "$obj" "$RUNTIME_OBJ" 2>/dev/null; then
        echo "  FAIL $name: link failed (an instantiation body declined?)"; return; fi
    RUN "$exe"; local got=$?
    if [ "$got" -eq 124 ]; then echo "  FAIL $name: TIMED OUT"; return; fi
    if [ "$got" -ne "$want" ]; then echo "  FAIL $name: exit $got, want $want"; return; fi
    pass=$((pass + 1))
}

# push_back two items, then read them back via arena_deque_at (ref-field index): 40 + 2.
deque_case push_at 'def main() -> i64 can[Memory.Allocate, Abort.Panic]:
    arena: mutable Arena = zeroed
    d: mutable Deque[i64] = arena_deque_with_capacity[i64](&arena, 4.usize())
    _ = arena_deque_push_back(&arena, &d, 40)
    _ = arena_deque_push_back(&arena, &d, 2)
    a: i64& = arena_deque_at(&d, 0.usize())
    b: i64& = arena_deque_at(&d, 1.usize())
    return a + b' 42
# count reflects the pushes.
deque_case count 'def main() -> i64 can[Memory.Allocate, Abort.Panic]:
    arena: mutable Arena = zeroed
    d: mutable Deque[i64] = arena_deque_with_capacity[i64](&arena, 8.usize())
    _ = arena_deque_push_back(&arena, &d, 1)
    _ = arena_deque_push_back(&arena, &d, 2)
    _ = arena_deque_push_back(&arena, &d, 3)
    return d.count.i64() + 39' 42

if [ "$pass" -eq "$total" ]; then
    echo "deque_real_smoke OK: $pass/$total real-std Deque[T] programs compile+run correctly"
else
    echo "deque_real_smoke FAILED: $pass/$total"; exit 1
fi
