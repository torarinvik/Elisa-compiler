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
    python3 - "$STD/deque.elisa" "$STD/collections.elisa" > "$src" <<PY
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
print('\n'.join(res))
print('''$body''')
PY
    if ! "$EMIT" < "$src" > "$ll" 2>/dev/null || head -1 "$ll" | grep -q UNSUPPORTED; then
        echo "  FAIL $name: stage1 declined the real-std dict program"; return; fi
    if ! "$LLC" -filetype=obj "$ll" -o "$obj" 2>/dev/null; then
        echo "  FAIL $name: llc rejected the emitted IR"; return; fi
    if ! clang -o "$exe" "$obj" "$RUNTIME_OBJ" 2>/dev/null; then
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

if [ "$pass" -eq "$total" ]; then
    echo "dict_real_smoke OK: $pass/$total real-std collections.elisa dict programs compile+run correctly"
else
    echo "dict_real_smoke FAILED: $pass/$total"; exit 1
fi
