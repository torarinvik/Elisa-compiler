#!/usr/bin/env bash
# Stage1 REAL-STD dict smoke: compile the ACTUAL elisacore_std collections.elisa dict
# (open-addressing hash table, grow/rehash, tombstones) through the stage1 backend and
# assert the program's real BEHAVIOR (exit code). This is the end-to-end proof that dict
# — the last feature for stage0/stage1 backend parity — works, not just that it compiles.
#
# The std source is CONCATENATED (deque.elisa + collections.elisa) with `include` lines
# stripped, because the driver reads a single program on stdin. The two `ctx_hash_u64`/
# `ctx_hash_cstr` DEFINITIONS are dropped: elisacore_runtime.o already provides them, so
# keeping the std copies would duplicate-symbol at link. (In a real stage1 pipeline the
# driver's include resolution + a runtime that omits these would handle it; this harness
# just links the extracted runtime object.)
RUN() { if command -v timeout >/dev/null 2>&1; then timeout 15 "$@"; else "$@"; fi; }
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISACORE_BIN="${ELISACORE_BIN:-$HOME/.elisac/elisac}"
LLVM_CONFIG="${LLVM_CONFIG:-/opt/homebrew/opt/llvm/bin/llvm-config}"
STD="${ELISA_CORE:-$ROOT/../../Go projects/Elisa-core}/compiler/runtime/elisacore_std"

[ -x "$ELISACORE_BIN" ] || { echo "dict_real_smoke SKIP: no elisac"; exit 0; }
[ -x "$LLVM_CONFIG" ] || { echo "dict_real_smoke SKIP: no llvm-config"; exit 0; }
[ -f "$STD/collections.elisa" ] || { echo "dict_real_smoke SKIP: no collections.elisa at $STD"; exit 0; }
command -v python3 >/dev/null 2>&1 || { echo "dict_real_smoke SKIP: no python3"; exit 0; }

LIBDIR="$("$LLVM_CONFIG" --libdir)"
LLC="$(dirname "$LLVM_CONFIG")/llc"
BUILD="$ROOT/build"; mkdir -p "$BUILD"
EMIT="$BUILD/emit_native"

# Reuse the emitter + runtime object the backend smoke builds; build them if absent.
if [ ! -x "$EMIT" ]; then
    "$ELISACORE_BIN" -emit obj -O2 -o "$BUILD/emit_native.o" "$ROOT/test/breadth/emit_native.elisa" 2>/dev/null \
        && clang -o "$EMIT" "$BUILD/emit_native.o" -L"$LIBDIR" -lLLVM -Wl,-rpath,"$LIBDIR" 2>/dev/null
fi
[ -x "$EMIT" ] || { echo "dict_real_smoke FAILED: no emit_native"; exit 1; }
RUNTIME_OBJ="$BUILD/runtime/elisacore_runtime.o"
if [ ! -f "$RUNTIME_OBJ" ]; then
    mkdir -p "$BUILD/runtime"
    printf 'def main() -> i64:\n    d: mutable darray[u8] = []\n    d.push(1)\n    return 0\n' > "$BUILD/runtime/probe.elisa"
    ( cd "$BUILD/runtime" && "$ELISACORE_BIN" -emit c-archive -o probe.a probe.elisa 2>/dev/null && ar x probe.a elisacore_runtime.o 2>/dev/null )
fi
[ -f "$RUNTIME_OBJ" ] || { echo "dict_real_smoke FAILED: no elisacore_runtime.o"; exit 1; }

pass=0; total=0
# dict_case <name> <main-body> <want-exit>
dict_case() {
    local name="$1" body="$2" want="$3"; total=$((total + 1))
    local src="$BUILD/dictreal_$name.elisa" ll="$BUILD/dictreal_$name.ll" obj="$BUILD/dictreal_$name.o" exe="$BUILD/dictreal_$name"
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
# The two hash DEFINITIONS are stripped above (elisacore_runtime.o already provides them,
# so keeping the std copies duplicate-symbol at link). Stripping alone is not enough:
# stage0 then reports 'missing runtime function "ctx_hash_cstr"'. Re-declare them as
# EXTERNs so both compilers see a signature and neither emits a body.
print('extern ctx_hash_cstr(s: cstr) -> u64')
print('extern ctx_hash_u64(value: u64) -> u64')
print('\n'.join(res))
print('''$body''')
PY
    # The fixture must be a program stage0 ACCEPTS before stage1's output means anything.
    # Without this the concat silently dropped arena.elisa (which defines RuntimeError),
    # so every case fed stage1 a program stage0 rejects outright -- and the gate reported
    # backend failures ("llc rejected the IR") for a broken FIXTURE, pointing at the wrong
    # compiler for as long as it was red.
    if ! "$ELISACORE_BIN" -emit llvm -o /dev/null "$src" 2>"$BUILD/dictreal_$name.s0log"; then
        echo "  FAIL $name: FIXTURE INVALID -- stage0 rejects the concatenated std:"
        grep -v warning "$BUILD/dictreal_$name.s0log" | head -3 | sed 's/^/      /'
        return; fi
    if ! "$EMIT" < "$src" > "$ll" 2>/dev/null || head -1 "$ll" | grep -q UNSUPPORTED; then
        echo "  FAIL $name: stage1 declined the real-std dict program"; return; fi
    if ! "$LLC" -filetype=obj "$ll" -o "$obj" 2>/dev/null; then
        echo "  FAIL $name: llc rejected the emitted IR"; return; fi
    if ! clang -Wl,-dead_strip -o "$exe" "$obj" "$RUNTIME_OBJ" 2>/dev/null; then
        echo "  FAIL $name: link failed"; return; fi
    RUN "$exe"; local got=$?
    if [ "$got" -eq 124 ]; then echo "  FAIL $name: TIMED OUT"; return; fi
    if [ "$got" -ne "$want" ]; then echo "  FAIL $name: exit $got, want $want"; return; fi
    pass=$((pass + 1))
}

# put + get round-trip (grows an empty dict, hashes, probes, reads back).
dict_case put_get 'def main() -> i64:
    d: mutable dict[i64, i64] = {}
    d.put(1, 40)
    d.put(2, 2)
    total: mutable i64 = 0
    if d.get(1) is a:
        total <- total + a
    if d.get(2) is b:
        total <- total + b
    return total' 42
# Many entries: forces repeated grow + REHASH. sum(2*i, i=1..19) = 380; -338 = 42.
dict_case grow_rehash 'def main() -> i64:
    d: mutable dict[i64, i64] = {}
    for i in 1..<20:
        d.put(i, i * 2)
    total: mutable i64 = 0
    for k in 1..<20:
        if d.get(k) is v:
            total <- total + v
    return total - 338' 42
# Overwrite an existing key: the second put replaces, count stays 1.
dict_case overwrite 'def main() -> i64:
    d: mutable dict[i64, i64] = {}
    d.put(5, 10)
    d.put(5, 42)
    if d.get(5) is v:
        return v
    return 0' 42
# Missing key: get returns the empty optional.
dict_case missing 'def main() -> i64:
    d: mutable dict[i64, i64] = {}
    d.put(1, 7)
    return 42 if d.get(99) == null else 0' 42

# `for k, v in d` iteration: a raw bucket-array walk over occupied slots (state==1),
# binding key + value. Sum of values, and entry count, asserted by exit code.
dict_case iter_sum_values 'def main() -> i64:
    d: mutable dict[i64, i64] = {}
    d.put(1, 40)
    d.put(2, 2)
    s: mutable i64 = 0
    for k, v in d:
        s <- s + v
    return s' 42
dict_case iter_count 'def main() -> i64:
    d: mutable dict[i64, i64] = {}
    d.put(10, 5)
    d.put(20, 5)
    d.put(30, 5)
    n: mutable i64 = 0
    for k, v in d:
        n <- n + 1
    return n' 3
dict_case iter_empty 'def main() -> i64:
    d: mutable dict[i64, i64] = {}
    n: mutable i64 = 0
    for k, v in d:
        n <- n + 1
    return n' 0

# Non-empty dict LITERAL `{k: v, …}`: a zeroed DynDict + one arena_dict_put_or_panic per
# entry (the frictionless insert), then read back. The analogue of the set literal.
dict_case literal_entries 'def main() -> i64:
    d: mutable dict[i64, i64] = {1: 40, 2: 2}
    total: mutable i64 = 0
    if d.get(1) is a:
        total <- total + a
    if d.get(2) is b:
        total <- total + b
    return total' 42
# A literal entry then an explicit put overwrites (count stays 1, value replaced).
dict_case literal_then_put 'def main() -> i64:
    d: mutable dict[i64, i64] = {5: 100}
    d.put(5, 42)
    if d.get(5) is v:
        return v
    return 0' 42
# Dict COMPREHENSION `{k: v for k in LOW..<HIGH}`: a zeroed DynDict + one
# arena_dict_put_or_panic per iteration. Values 2+4+6 = 12 (+30 = 42).
dict_case comprehension 'def main() -> i64:
    d: mutable dict[i64, i64] = {k: k * 2 for k in 1..<4}
    t: mutable i64 = 0
    if d.get(1) is a:
        t <- t + a
    if d.get(2) is b:
        t <- t + b
    if d.get(3) is c:
        t <- t + c
    return t + 30' 42
# Filtered comprehension `{… for … if COND}`: only k in {7,8,9} pass, 3 entries.
dict_case comprehension_filter 'def main() -> i64:
    d: mutable dict[i64, i64] = {k: k for k in 0..<10 if k > 6}
    n: mutable i64 = 0
    for k, v in d:
        n <- n + 1
    return n + 39' 42
# Comprehension over an existing DARRAY source (not a range).
dict_case comprehension_over_darray 'def main() -> i64:
    xs: darray[i64] = [1, 2, 3]
    d: mutable dict[i64, i64] = {k: k * 10 for k in xs}
    if d.get(2) is v:
        return v + 22
    return 0' 42
# `d.clear()` empties the dict (a subsequent get misses; a subsequent put still works).
dict_case clear 'def main() -> i64:
    d: mutable dict[i64, i64] = {}
    d.put(1, 5)
    d.clear()
    return 42 if d.get(1) == null else 7' 42
# `arena_dict_get` returns `usize&?` (an optional REF); deref it via `found[0]` after a
# `found == null` narrowing — the index_map_find_index shape. Exercises optional-ref indexing.
dict_case optional_ref_deref 'def find_idx(d: dict[i64, usize]&, key: i64) -> usize:
    found: usize&? = arena_dict_get[i64, usize](d, key)
    return 999.usize() if found == null else found[0]
def main() -> i64 can[Memory.Allocate, Abort.Panic]:
    arena: mutable Arena = zeroed
    d: mutable dict[i64, usize] = zeroed
    d <- arena_dict_new[i64, usize](&arena, 8.usize())
    arena_dict_put_or_panic[i64, usize](&arena, &d, 7, 40.usize())
    return find_idx(&d, 7).i64() + 2' 42
# `d.contains(k)` / `d.remove(k)` round-trip.
dict_case contains_remove 'def main() -> i64:
    d: mutable dict[i64, i64] = {}
    d.put(1, 5)
    d.put(2, 9)
    hit: mutable i64 = 0
    if d.contains(1):
        hit <- hit + 40
    _ = d.remove(1)
    if not d.contains(1):
        hit <- hit + 2
    return hit' 42

if [ "$pass" -eq "$total" ]; then
    echo "dict_real_smoke OK: $pass/$total real-std collections.elisa dict programs compile+run correctly"
else
    echo "dict_real_smoke FAILED: $pass/$total"; exit 1
fi
