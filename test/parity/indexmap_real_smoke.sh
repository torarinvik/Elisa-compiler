#!/usr/bin/env bash
# Stage1 REAL-STD IndexMap smoke: compile the ACTUAL elisacore_std IndexMap[K,T] (insertion-
# ordered map = darray of entries + a dict[K,usize] index) through the stage1 backend and
# assert its real BEHAVIOR (exit code). IndexMap is the THIRD advanced std container to run
# end-to-end (after Slice and Deque) and by far the most construct-heavy: its methods needed
# match-on-optional, `in owner:` over a borrowed arena, darray `.reserve()`, bare `get`
# (index_map_get), optional-ref indexing (index_map_find_index's `found[0]`), explicit-generic
# error-fn try-else (`try arena_dict_put[K,V](...) else null`), and auto-addressing a struct
# FIELD passed to a `mutable T&` param (`arena_dict_put(a, map.by_key, …)`).
RUN() { if command -v timeout >/dev/null 2>&1; then timeout 15 "$@"; else "$@"; fi; }
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISACORE_BIN="${ELISACORE_BIN:-$ROOT/../../Go projects/structpy-tree/compiler/bin/elisac}"
LLVM_CONFIG="${LLVM_CONFIG:-/opt/homebrew/opt/llvm/bin/llvm-config}"
STD="${ELISA_CORE:-$ROOT/../../Go projects/structpy-tree}/compiler/runtime/elisacore_std"

[ -x "$ELISACORE_BIN" ] || { echo "indexmap_real_smoke SKIP: no elisac"; exit 0; }
[ -x "$LLVM_CONFIG" ] || { echo "indexmap_real_smoke SKIP: no llvm-config"; exit 0; }
[ -f "$STD/collections.elisa" ] || { echo "indexmap_real_smoke SKIP: no collections.elisa at $STD"; exit 0; }
command -v python3 >/dev/null 2>&1 || { echo "indexmap_real_smoke SKIP: no python3"; exit 0; }

LIBDIR="$("$LLVM_CONFIG" --libdir)"
LLC="$(dirname "$LLVM_CONFIG")/llc"
BUILD="$ROOT/build"; mkdir -p "$BUILD"
EMIT="$BUILD/emit_native"

if [ ! -x "$EMIT" ]; then
    "$ELISACORE_BIN" -emit obj -O2 -o "$BUILD/emit_native.o" "$ROOT/test/breadth/emit_native.elisa" 2>/dev/null \
        && clang -o "$EMIT" "$BUILD/emit_native.o" -L"$LIBDIR" -lLLVM -Wl,-rpath,"$LIBDIR" 2>/dev/null
fi
[ -x "$EMIT" ] || { echo "indexmap_real_smoke FAILED: no emit_native"; exit 1; }
RUNTIME_OBJ="$BUILD/runtime/elisacore_runtime.o"
if [ ! -f "$RUNTIME_OBJ" ]; then
    mkdir -p "$BUILD/runtime"
    printf 'def main() -> i64:\n    d: mutable darray[u8] = []\n    d.push(1)\n    return 0\n' > "$BUILD/runtime/probe.elisa"
    ( cd "$BUILD/runtime" && "$ELISACORE_BIN" -emit c-archive -o probe.a probe.elisa 2>/dev/null && ar x probe.a elisacore_runtime.o 2>/dev/null )
fi
[ -f "$RUNTIME_OBJ" ] || { echo "indexmap_real_smoke FAILED: no elisacore_runtime.o"; exit 1; }

pass=0; total=0
imap_case() {
    local name="$1" body="$2" want="$3"; total=$((total + 1))
    local src="$BUILD/imapreal_$name.elisa" ll="$BUILD/imapreal_$name.ll" obj="$BUILD/imapreal_$name.o" exe="$BUILD/imapreal_$name"
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
    if ! "$ELISACORE_BIN" -emit llvm -o /dev/null "$src" 2>"$BUILD/imapreal_$name.s0log"; then
        echo "  FAIL $name: FIXTURE INVALID -- stage0 rejects the IndexMap program:"
        grep -v warning "$BUILD/imapreal_$name.s0log" | head -3 | sed 's/^/      /'
        return; fi
    if ! "$EMIT" < "$src" > "$ll" 2>/dev/null || head -1 "$ll" | grep -q UNSUPPORTED; then
        echo "  FAIL $name: stage1 declined the real-std IndexMap program"; return; fi
    if ! "$LLC" -filetype=obj "$ll" -o "$obj" 2>/dev/null; then
        echo "  FAIL $name: llc rejected the emitted IR"; return; fi
    if ! clang -Wl,-dead_strip -o "$exe" "$obj" "$RUNTIME_OBJ" 2>/dev/null; then
        echo "  FAIL $name: link failed (an instantiation body declined?)"; return; fi
    RUN "$exe"; local got=$?
    if [ "$got" -eq 124 ]; then echo "  FAIL $name: TIMED OUT"; return; fi
    if [ "$got" -ne "$want" ]; then echo "  FAIL $name: exit $got, want $want"; return; fi
    pass=$((pass + 1))
}

# put two keys then get them back: 40 + 2 = 42. Exercises the full ctor+put+get path.
imap_case put_get 'def main() -> i64 can[Memory.Allocate, Abort.Panic]:
    arena: mutable Arena = zeroed
    m: mutable IndexMap[i64, i64] = index_map_new[i64, i64](&arena)
    _ = index_map_put[i64, i64](&m, 1, 40)
    _ = index_map_put[i64, i64](&m, 2, 2)
    total: mutable i64 = 0
    if index_map_get[i64, i64](&m, 1) is a:
        total <- total + a
    if index_map_get[i64, i64](&m, 2) is b:
        total <- total + b
    return total' 42
# overwrite an existing key: the second put replaces the value; count stays 1.
imap_case overwrite 'def main() -> i64 can[Memory.Allocate, Abort.Panic]:
    arena: mutable Arena = zeroed
    m: mutable IndexMap[i64, i64] = index_map_new[i64, i64](&arena)
    _ = index_map_put[i64, i64](&m, 5, 10)
    _ = index_map_put[i64, i64](&m, 5, 42)
    if index_map_get[i64, i64](&m, 5) is v:
        return v
    return 0' 42
# missing key -> get is null.
imap_case missing 'def main() -> i64 can[Memory.Allocate, Abort.Panic]:
    arena: mutable Arena = zeroed
    m: mutable IndexMap[i64, i64] = index_map_new[i64, i64](&arena)
    _ = index_map_put[i64, i64](&m, 1, 7)
    return 42 if index_map_get[i64, i64](&m, 99) == null else 0' 42
# count reflects distinct inserts (a re-put of an existing key does not grow it).
imap_case count 'def main() -> i64 can[Memory.Allocate, Abort.Panic]:
    arena: mutable Arena = zeroed
    m: mutable IndexMap[i64, i64] = index_map_new[i64, i64](&arena)
    _ = index_map_put[i64, i64](&m, 1, 1)
    _ = index_map_put[i64, i64](&m, 2, 2)
    _ = index_map_put[i64, i64](&m, 3, 3)
    _ = index_map_put[i64, i64](&m, 1, 9)
    return index_map_count[i64, i64](&m).i64() + 39' 42
# many inserts force the backing dict to grow/rehash; every key still reads back.
imap_case grow 'def main() -> i64 can[Memory.Allocate, Abort.Panic]:
    arena: mutable Arena = zeroed
    m: mutable IndexMap[i64, i64] = index_map_new[i64, i64](&arena)
    for i in 1..<20:
        _ = index_map_put[i64, i64](&m, i, i * 2)
    total: mutable i64 = 0
    for k in 1..<20:
        if index_map_get[i64, i64](&m, k) is v:
            total <- total + v
    return total - 338' 42

if [ "$pass" -eq "$total" ]; then
    echo "indexmap_real_smoke OK: $pass/$total real-std IndexMap[K,T] programs compile+run correctly"
else
    echo "indexmap_real_smoke FAILED: $pass/$total"; exit 1
fi
