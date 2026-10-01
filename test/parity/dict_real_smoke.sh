#!/usr/bin/env bash
# Stage1 REAL-STD dict smoke: compile the ACTUAL elisacore_std collections.elisa dict
# (open-addressing hash table, grow/rehash, tombstones) through the stage1 backend and
# assert the program's real BEHAVIOR (exit code). This is the end-to-end proof that dict
# — the last feature for stage0/stage1 backend parity — works, not just that it compiles.
#
# The fixture `include`s the REAL std collections.elisa (stage0's tree, $ELISA_CORE) and is
# compiled by BOTH compilers through their drivers, linked, and RUN. stage0 must produce the
# expected exit code before stage1's answer is counted.
#
# It used to CONCATENATE hand-listed std files (include lines stripped) and feed stdin to
# emit_native. That rotted silently twice: first arena.elisa went missing from the list, then
# arena.elisa began including elisacore_runtime_atomics.elisa (the
# __elisa_arena_cache_lock_acquire/_release definitions). Adding that file to the list is not
# enough either: its raw `load`/`store` are legal only in a std SOURCE file, and the
# concatenated program is not one, so stage0 rejected every case (0/18). Real includes keep
# the std's own include graph and file identity.
#
# Linked WITHOUT elisacore_runtime.o (the included runtime defines those symbols; linking
# both duplicates them), with no-op profiler hooks + ctx_streq from a C stub.
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/run_timeout.sh"
RUN() { elisa_run_timeout 15 "$@"; }
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISACORE_BIN="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN" || exit $?
STD="${ELISA_CORE:-$ROOT/../../Go projects/Elisa-core}/compiler/runtime/elisacore_std"

[ -x "$ELISACORE_BIN" ] || { echo "dict_real_smoke FAIL: no elisac" >&2; exit 1; }
[ -f "$STD/collections.elisa" ] || { echo "dict_real_smoke FAIL: no collections.elisa at $STD" >&2; exit 1; }

BIN="${ELISAC_STAGE1:-$ROOT/bin/elisac-stage1}"
[ -x "$BIN" ] || { echo "dict_real_smoke FAILED: no stage1 binary at $BIN"; exit 1; }
# Not under /private/tmp: stage0 writes an empty object for those paths.
TMP="$(mktemp -d "$HOME/.dict_real_smoke.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT
cat > "$TMP/stub.c" <<'C'
#include <stdint.h>
#include <string.h>
void elisa_profile_allocation_event_v1(uint32_t a, uintptr_t b, size_t c, uintptr_t d, size_t e, uintptr_t f, size_t g) {}
uint32_t elisa_profile_allocation_negotiate(uint32_t v) { return 0; }
uint32_t elisa_profile_region_layout_negotiate(uint32_t v) { return 0; }
void elisa_profile_region_layout_v1(void) {}
_Bool ctx_streq(const char *a, const char *b) { return strcmp(a, b) == 0; }
C
clang -c "$TMP/stub.c" -o "$TMP/stub.o" || { echo "dict_real_smoke FAILED: stub"; exit 1; }

# run_with <compiler> <src> <tag>: prints rc=N, or why there is no executable.
run_with() {
    local compiler="$1" src="$2" tag="$3"
    "$compiler" -emit obj "$src" -o "$TMP/$tag.o" >"$TMP/$tag.log" 2>&1 || { echo "compile-fail"; return; }
    [ -s "$TMP/$tag.o" ] || { echo "no-object"; return; }
    clang -Wl,-dead_strip -o "$TMP/$tag" "$TMP/$tag.o" "$TMP/stub.o" 2>"$TMP/$tag.link" || { echo "link-fail"; return; }
    RUN "$TMP/$tag" >/dev/null 2>&1; echo "rc=$?"
}

pass=0; total=0
# dict_case <name> <main-body> <want-exit>
dict_case() {
    local name="$1" body="$2" want="$3"; total=$((total + 1))
    local src="$TMP/$name.elisa"
    printf 'include "%s"\n\n%s\n' "$STD/collections.elisa" "$body" > "$src"
    local s0; s0="$(run_with "$ELISACORE_BIN" "$src" "s0_$name")"
    if [ "$s0" != "rc=$want" ]; then
        echo "  FAIL $name: FIXTURE INVALID -- stage0 gives $s0, want rc=$want"
        grep -v 'warning:' "$TMP/s0_$name.log" | head -3 | sed 's/^/      /'; return; fi
    local s1; s1="$(run_with "$BIN" "$src" "s1_$name")"
    if [ "$s1" != "rc=$want" ]; then
        echo "  FAIL $name: stage1 gives $s1, want rc=$want"
        grep -v 'warning:' "$TMP/s1_$name.log" | head -3 | sed 's/^/      /'; return; fi
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

# A dict whose VALUE is an AGGREGATE (a multi-word struct), not a scalar. Every case above
# uses integer values, so the aggregate-valued bucket path was untested — and that is the
# shape the compiler's own SymbolTable.name_primary (`dict[u64, sview]`, a {ptr,len} pair)
# uses. A wrong bucket STRIDE only corrupts the heap when the value is wider than a word.
dict_case aggregate_value_put_get 'struct Pair:
    a: i64
    b: i64

def main() -> i64:
    d: mutable dict[i64, Pair] = {}
    d.put(1, Pair{a: 20, b: 1})
    d.put(2, Pair{a: 20, b: 1})
    total: mutable i64 = 0
    if d.get(1) is p:
        total <- total + p.a + p.b
    if d.get(2) is q:
        total <- total + q.a + q.b
    return total' 42

# Same aggregate value, but enough entries to force GROW + REHASH: the rehash COPIES every
# bucket, so a stride error corrupts memory here even when a single put happens to survive.
dict_case aggregate_value_grow 'struct Pair:
    a: i64
    b: i64

def main() -> i64:
    d: mutable dict[i64, Pair] = {}
    for i in 0..<24 |d|:
        d.put(i, Pair{a: i, b: 1})
    total: mutable i64 = 0
    for i in 0..<24 |total, d|:
        if d.get(i) is p:
            total <- total + p.b
    return total + 18' 42

if [ "$pass" -eq "$total" ]; then
    echo "dict_real_smoke OK: $pass/$total real-std collections.elisa dict programs compile+run correctly"
else
    echo "dict_real_smoke FAILED: $pass/$total"; exit 1
fi
