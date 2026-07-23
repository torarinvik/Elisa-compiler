#!/usr/bin/env bash
# Stage1 REAL-STD set smoke: compile the ACTUAL elisacore_std set path (open-addressing
# hash set, arena_set_add_or_panic / arena_set_contains) through the stage1 backend and
# assert the program's real BEHAVIOR (exit code). End-to-end proof that `set` — literal
# construction `{a, b, …}` and membership `x in s` — works, not just that it compiles.
#
# Like dict_real_smoke, the std source is CONCATENATED (arena + deque + collections) with
# `include` lines stripped and the two ctx_hash_* DEFINITIONS dropped (elisacore_runtime.o
# already provides them) + re-declared extern.
#
# ASYMMETRY vs dict: `DynSet`/`SetBucket` are stage0 BACKEND BUILTINS (not declared in std
# source), whereas `DynDict`/`DictBucket` ARE in collections.elisa. So stage1's backend has
# no layout for them from the std alone. The fixture therefore prepends a source struct
# PRELUDE declaring DynSet/SetBucket — but ONLY for stage1: stage0 already has them builtin,
# so feeding stage0 the prelude would redeclare them. stage0 validates the un-preluded
# source; stage1's emitter gets the preluded one.
RUN() { if command -v timeout >/dev/null 2>&1; then timeout 15 "$@"; else "$@"; fi; }
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISACORE_BIN="${ELISACORE_BIN:-$HOME/.elisac/elisac}"
LLVM_CONFIG="${LLVM_CONFIG:-/opt/homebrew/opt/llvm/bin/llvm-config}"
STD="${ELISA_CORE:-$ROOT/../../Go projects/Elisa-core}/compiler/runtime/elisacore_std"

[ -x "$ELISACORE_BIN" ] || { echo "set_real_smoke SKIP: no elisac"; exit 0; }
[ -x "$LLVM_CONFIG" ] || { echo "set_real_smoke SKIP: no llvm-config"; exit 0; }
[ -f "$STD/collections.elisa" ] || { echo "set_real_smoke SKIP: no collections.elisa at $STD"; exit 0; }
command -v python3 >/dev/null 2>&1 || { echo "set_real_smoke SKIP: no python3"; exit 0; }

LIBDIR="$("$LLVM_CONFIG" --libdir)"
LLC="$(dirname "$LLVM_CONFIG")/llc"
BUILD="$ROOT/build"; mkdir -p "$BUILD"
EMIT="$BUILD/emit_native"

if [ ! -x "$EMIT" ]; then
    "$ELISACORE_BIN" -emit obj -O2 -o "$BUILD/emit_native.o" "$ROOT/test/breadth/emit_native.elisa" 2>/dev/null \
        && clang -o "$EMIT" "$BUILD/emit_native.o" -L"$LIBDIR" -lLLVM -Wl,-rpath,"$LIBDIR" 2>/dev/null
fi
[ -x "$EMIT" ] || { echo "set_real_smoke FAILED: no emit_native"; exit 1; }
RUNTIME_OBJ="$BUILD/runtime/elisacore_runtime.o"
if [ ! -f "$RUNTIME_OBJ" ]; then
    mkdir -p "$BUILD/runtime"
    printf 'def main() -> i64:\n    d: mutable darray[u8] = []\n    d.push(1)\n    return 0\n' > "$BUILD/runtime/probe.elisa"
    ( cd "$BUILD/runtime" && "$ELISACORE_BIN" -emit c-archive -o probe.a probe.elisa 2>/dev/null && ar x probe.a elisacore_runtime.o 2>/dev/null )
fi
[ -f "$RUNTIME_OBJ" ] || { echo "set_real_smoke FAILED: no elisacore_runtime.o"; exit 1; }

# The stage1-only DynSet/SetBucket layout prelude (matches the stage0 builtin layout).
PRELUDE='struct SetBucket[T]:
    key: mutable T
    state: mutable u8

struct DynSet[T]:
    items: mutable SetBucket[T]&?
    count: mutable usize
    used: mutable usize
    capacity: mutable usize
    arena: mutable Arena&?
'

pass=0; total=0
# set_case <name> <main-body> <want-exit>
set_case() {
    local name="$1" body="$2" want="$3"; total=$((total + 1))
    local src="$BUILD/setreal_$name.elisa" s1="$BUILD/setreal_${name}_s1.elisa"
    local ll="$BUILD/setreal_$name.ll" obj="$BUILD/setreal_$name.o" exe="$BUILD/setreal_$name"
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
    # stage0 validates the un-preluded source (DynSet/SetBucket are its builtins).
    if ! "$ELISACORE_BIN" -emit llvm -o /dev/null "$src" 2>"$BUILD/setreal_$name.s0log"; then
        echo "  FAIL $name: FIXTURE INVALID -- stage0 rejects the set program:"
        grep -v warning "$BUILD/setreal_$name.s0log" | head -3 | sed 's/^/      /'
        return; fi
    # stage1 gets the DynSet/SetBucket layout prelude prepended (backend has no builtin).
    printf '%s\n' "$PRELUDE" > "$s1"; cat "$src" >> "$s1"
    if ! "$EMIT" < "$s1" > "$ll" 2>/dev/null || head -1 "$ll" | grep -q UNSUPPORTED; then
        echo "  FAIL $name: stage1 declined the real-std set program"; return; fi
    if ! "$LLC" -filetype=obj "$ll" -o "$obj" 2>/dev/null; then
        echo "  FAIL $name: llc rejected the emitted IR"; return; fi
    if ! clang -o "$exe" "$obj" "$RUNTIME_OBJ" 2>/dev/null; then
        echo "  FAIL $name: link failed"; return; fi
    RUN "$exe"; local got=$?
    if [ "$got" -eq 124 ]; then echo "  FAIL $name: TIMED OUT"; return; fi
    if [ "$got" -ne "$want" ]; then echo "  FAIL $name: exit $got, want $want"; return; fi
    pass=$((pass + 1))
}

# Literal build + membership hit: {1,2,3}, probe for 2 -> present.
set_case member_hit 'def main() -> i64:
    s: mutable set[i64] = {1, 2, 3}
    return 42 if 2 in s else 7' 42
# Membership miss: 9 not inserted.
set_case member_miss 'def main() -> i64:
    s: mutable set[i64] = {1, 2, 3}
    return 42 if 9 in s else 7' 7
# Empty set: nothing is a member.
set_case empty_miss 'def main() -> i64:
    s: mutable set[i64] = {}
    return 42 if 9 in s else 7' 7
# All three literal elements are individually present (distinct hash probes).
set_case all_present 'def main() -> i64:
    s: mutable set[i64] = {10, 20, 30}
    hit: mutable i64 = 0
    if 10 in s:
        hit <- hit + 1
    if 20 in s:
        hit <- hit + 1
    if 30 in s:
        hit <- hit + 1
    return hit' 3

if [ "$pass" -eq "$total" ]; then
    echo "set_real_smoke OK: $pass/$total real-std collections.elisa set programs compile+run correctly"
else
    echo "set_real_smoke FAILED: $pass/$total"; exit 1
fi
