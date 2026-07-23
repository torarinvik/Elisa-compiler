#!/usr/bin/env bash
# Stage1 darray `.reserve(n)` smoke: `reserve` ensures capacity >= n without changing count
# or storing an element (emit_darray_reserve), so unlike `resize` (scalar-only, push-fills
# zeros) it works for ANY element type — including a darray of structs. reserve returns
# `mutable darray&` for chaining, so it is DISCARDED via `_ =` rather than a bare statement,
# and needs an explicit `in <arena>:` scope (stage0-enforced). This gate exercises it on a
# plain scalar darray, a struct-field darray, and a darray-of-structs (the IndexMap ctor
# shape: `map.entries.reserve(cap)`), asserting the reserved buffer round-trips real values.
RUN() { if command -v timeout >/dev/null 2>&1; then timeout 15 "$@"; else "$@"; fi; }
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISACORE_BIN="${ELISACORE_BIN:-$HOME/.elisac/elisac}"
LLVM_CONFIG="${LLVM_CONFIG:-/opt/homebrew/opt/llvm/bin/llvm-config}"
STD="${ELISA_CORE:-$ROOT/../../Go projects/Elisa-core}/compiler/runtime/elisacore_std"

[ -x "$ELISACORE_BIN" ] || { echo "reserve_real_smoke SKIP: no elisac"; exit 0; }
[ -x "$LLVM_CONFIG" ] || { echo "reserve_real_smoke SKIP: no llvm-config"; exit 0; }
[ -f "$STD/arena.elisa" ] || { echo "reserve_real_smoke SKIP: no arena std at $STD"; exit 0; }
command -v python3 >/dev/null 2>&1 || { echo "reserve_real_smoke SKIP: no python3"; exit 0; }

LIBDIR="$("$LLVM_CONFIG" --libdir)"
LLC="$(dirname "$LLVM_CONFIG")/llc"
BUILD="$ROOT/build"; mkdir -p "$BUILD"
EMIT="$BUILD/emit_native"

if [ ! -x "$EMIT" ]; then
    "$ELISACORE_BIN" -emit obj -O2 -o "$BUILD/emit_native.o" "$ROOT/test/breadth/emit_native.elisa" 2>/dev/null \
        && clang -o "$EMIT" "$BUILD/emit_native.o" -L"$LIBDIR" -lLLVM -Wl,-rpath,"$LIBDIR" 2>/dev/null
fi
[ -x "$EMIT" ] || { echo "reserve_real_smoke FAILED: no emit_native"; exit 1; }
RUNTIME_OBJ="$BUILD/runtime/elisacore_runtime.o"
if [ ! -f "$RUNTIME_OBJ" ]; then
    mkdir -p "$BUILD/runtime"
    printf 'def main() -> i64:\n    d: mutable darray[u8] = []\n    d.push(1)\n    return 0\n' > "$BUILD/runtime/probe.elisa"
    ( cd "$BUILD/runtime" && "$ELISACORE_BIN" -emit c-archive -o probe.a probe.elisa 2>/dev/null && ar x probe.a elisacore_runtime.o 2>/dev/null )
fi
[ -f "$RUNTIME_OBJ" ] || { echo "reserve_real_smoke FAILED: no elisacore_runtime.o"; exit 1; }

pass=0; total=0
reserve_case() {
    local name="$1" body="$2" want="$3"; total=$((total + 1))
    local src="$BUILD/reservereal_$name.elisa" ll="$BUILD/reservereal_$name.ll" obj="$BUILD/reservereal_$name.o" exe="$BUILD/reservereal_$name"
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
    if ! "$ELISACORE_BIN" -emit llvm -o /dev/null "$src" 2>"$BUILD/reservereal_$name.s0log"; then
        echo "  FAIL $name: FIXTURE INVALID -- stage0 rejects the reserve program:"
        grep -v warning "$BUILD/reservereal_$name.s0log" | head -3 | sed 's/^/      /'
        return; fi
    if ! "$EMIT" < "$src" > "$ll" 2>/dev/null || head -1 "$ll" | grep -q UNSUPPORTED; then
        echo "  FAIL $name: stage1 declined the reserve program"; return; fi
    if ! "$LLC" -filetype=obj "$ll" -o "$obj" 2>/dev/null; then
        echo "  FAIL $name: llc rejected the emitted IR"; return; fi
    if ! clang -o "$exe" "$obj" "$RUNTIME_OBJ" 2>/dev/null; then
        echo "  FAIL $name: link failed (an instantiation body declined?)"; return; fi
    RUN "$exe"; local got=$?
    if [ "$got" -eq 124 ]; then echo "  FAIL $name: TIMED OUT"; return; fi
    if [ "$got" -ne "$want" ]; then echo "  FAIL $name: exit $got, want $want"; return; fi
    pass=$((pass + 1))
}

# reserve on a plain scalar darray: reserve ahead, then push+read through the reserved buffer.
reserve_case scalar 'def main() -> i64 can[Memory.Allocate, Abort.Panic]:
    arena: mutable Arena = zeroed
    xs: mutable darray[i64] = []
    in arena:
        _ = xs.reserve(64.usize())
        xs.push(40)
        xs.push(2)
    return xs[0] + xs[1]' 42
# reserve on a struct-FIELD darray (the `b.items.reserve(n)` shape).
reserve_case field 'struct Bag:
    items: mutable darray[i64]
def main() -> i64 can[Memory.Allocate, Abort.Panic]:
    arena: mutable Arena = zeroed
    b: mutable Bag = zeroed
    in arena:
        _ = b.items.reserve(32.usize())
        b.items.push(21)
        b.items.push(21)
    return b.items[0] + b.items[1]' 42
# reserve on a darray of STRUCTS (resize cannot do this; the IndexMap ctor needs exactly this).
reserve_case structs 'struct Pair:
    a: mutable i64
    b: mutable i64
def main() -> i64 can[Memory.Allocate, Abort.Panic]:
    arena: mutable Arena = zeroed
    ps: mutable darray[Pair] = []
    in arena:
        _ = ps.reserve(16.usize())
        ps.push(Pair{a: 40, b: 100})
        ps.push(Pair{a: 2, b: 200})
    return ps[0].a + ps[1].a' 42
# reserve is idempotent-safe: a smaller reserve after a larger one must not shrink/corrupt.
reserve_case noshrink 'def main() -> i64 can[Memory.Allocate, Abort.Panic]:
    arena: mutable Arena = zeroed
    xs: mutable darray[i64] = []
    in arena:
        _ = xs.reserve(128.usize())
        xs.push(40)
        xs.push(2)
        _ = xs.reserve(4.usize())
    return xs[0] + xs[1]' 42

if [ "$pass" -eq "$total" ]; then
    echo "reserve_real_smoke OK: $pass/$total darray reserve programs compile+run correctly"
else
    echo "reserve_real_smoke FAILED: $pass/$total"; exit 1
fi
