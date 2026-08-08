#!/usr/bin/env bash
# Stage1 THREADING beachhead smoke: compile programs that spawn REAL OS threads via the
# pthread externs through the stage1 backend and assert their real BEHAVIOR (exit code).
# This is the first proof that stage1 emits the core concurrency primitives correctly —
# a FUNCTION cast to `void&` as the thread entry point, `pthread_create`/`pthread_join`,
# the `uintptr` handle, and address-of + `void&?` casts to hand a shared cell across the
# thread boundary. A worker's write is observable in main ONLY if join truly waited, so a
# stable exit code across a spawn+join is itself the synchronization assertion.
#
# It is the sub-milestone under the full parallel-for effort (the 124-fn pool/barrier/
# nursery runtime on top of these primitives); the primitives themselves work TODAY.
RUN() { if command -v timeout >/dev/null 2>&1; then timeout 15 "$@"; else "$@"; fi; }
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISACORE_BIN="${ELISACORE_BIN:-$HOME/.elisac/elisac}"
LLVM_CONFIG="${LLVM_CONFIG:-/opt/homebrew/opt/llvm/bin/llvm-config}"

[ -x "$ELISACORE_BIN" ] || { echo "thread_real_smoke SKIP: no elisac"; exit 0; }
[ -x "$LLVM_CONFIG" ] || { echo "thread_real_smoke SKIP: no llvm-config"; exit 0; }

LIBDIR="$("$LLVM_CONFIG" --libdir)"
LLC="$(dirname "$LLVM_CONFIG")/llc"
BUILD="$ROOT/build"; mkdir -p "$BUILD"
EMIT="$BUILD/emit_native"

if [ ! -x "$EMIT" ]; then
    "$ELISACORE_BIN" -emit obj -O2 -o "$BUILD/emit_native.o" "$ROOT/test/breadth/emit_native.elisa" 2>/dev/null \
        && clang -o "$EMIT" "$BUILD/emit_native.o" -L"$LIBDIR" -lLLVM -Wl,-rpath,"$LIBDIR" 2>/dev/null
fi
[ -x "$EMIT" ] || { echo "thread_real_smoke FAILED: no emit_native"; exit 1; }
RUNTIME_OBJ="$BUILD/runtime/elisacore_runtime.o"
if [ ! -f "$RUNTIME_OBJ" ]; then
    mkdir -p "$BUILD/runtime"
    printf 'def main() -> i64:\n    d: mutable darray[u8] = []\n    d.push(1)\n    return 0\n' > "$BUILD/runtime/probe.elisa"
    ( cd "$BUILD/runtime" && "$ELISACORE_BIN" -emit c-archive -o probe.a probe.elisa 2>/dev/null && ar x probe.a elisacore_runtime.o 2>/dev/null )
fi
[ -f "$RUNTIME_OBJ" ] || { echo "thread_real_smoke FAILED: no elisacore_runtime.o"; exit 1; }

# The pthread extern prelude every case shares.
PRELUDE='extern pthread_create(thread: mutable uintptr&, attr: void&?, start_routine: void&, arg: void&?) -> int can[Thread.Spawn]
extern pthread_join(thread: uintptr, retval: mutable void&?) -> int can[Thread.Join]'

pass=0; total=0
# Runs the case body TIMES times and requires the SAME want each run (a race would vary).
thread_case() {
    local name="$1" body="$2" want="$3" times="${4:-5}"; total=$((total + 1))
    local src="$BUILD/threadreal_$name.elisa" ll="$BUILD/threadreal_$name.ll" obj="$BUILD/threadreal_$name.o" exe="$BUILD/threadreal_$name"
    printf '%s\n%s\n' "$PRELUDE" "$body" > "$src"
    if ! "$ELISACORE_BIN" -emit llvm -o /dev/null "$src" 2>"$BUILD/threadreal_$name.s0log"; then
        echo "  FAIL $name: FIXTURE INVALID -- stage0 rejects the thread program:"
        grep -v warning "$BUILD/threadreal_$name.s0log" | head -3 | sed 's/^/      /'
        return; fi
    if ! "$EMIT" < "$src" > "$ll" 2>/dev/null || grep -q UNSUPPORTED "$ll"; then
        echo "  FAIL $name: stage1 declined the thread program"; return; fi
    if ! "$LLC" -filetype=obj "$ll" -o "$obj" 2>/dev/null; then
        echo "  FAIL $name: llc rejected the emitted IR"; return; fi
    if ! clang -Wl,-dead_strip -o "$exe" "$obj" "$RUNTIME_OBJ" 2>/dev/null; then
        echo "  FAIL $name: link failed"; return; fi
    local r
    for r in $(seq 1 "$times"); do
        RUN "$exe"; local got=$?
        if [ "$got" -eq 124 ]; then echo "  FAIL $name: TIMED OUT (deadlock?)"; return; fi
        if [ "$got" -ne "$want" ]; then echo "  FAIL $name: run $r exit $got, want $want (race or no sync?)"; return; fi
    done
    pass=$((pass + 1))
}

# One worker writes 42 through the shared cell; join then main reads it.
thread_case single 'def worker(arg: void&?) -> void&? can[Unsafe.PointerCast]:
    if arg is present:
        cell: mutable i64& = present.cast[mutable i64&] can Unsafe.PointerCast
        cell[0] <- 42
    return null
def main() -> i64 can[Thread.Spawn, Thread.Join, Unsafe.PointerCast]:
    handle: mutable uintptr = 0.uintptr()
    result: mutable i64 = 0
    entry: void& = worker.cast[void&] can Unsafe.PointerCast
    _ = pthread_create(&handle, null, entry, (&result).cast[void&?] can Unsafe.PointerCast)
    _ = pthread_join(handle, null)
    return result' 42
# Two workers each add 20 to their own cell (init 1). Sum is 42 ONLY if BOTH joined; a
# missed join would leave a cell at 1 (=> 22) or race. Stable 42 across runs = real sync.
thread_case two_join 'def worker(arg: void&?) -> void&? can[Unsafe.PointerCast]:
    if arg is present:
        cell: mutable i64& = present.cast[mutable i64&] can Unsafe.PointerCast
        cell[0] <- cell[0] + 20
    return null
def main() -> i64 can[Thread.Spawn, Thread.Join, Unsafe.PointerCast]:
    h1: mutable uintptr = 0.uintptr()
    h2: mutable uintptr = 0.uintptr()
    a: mutable i64 = 1
    b: mutable i64 = 1
    entry: void& = worker.cast[void&] can Unsafe.PointerCast
    _ = pthread_create(&h1, null, entry, (&a).cast[void&?] can Unsafe.PointerCast)
    _ = pthread_create(&h2, null, entry, (&b).cast[void&?] can Unsafe.PointerCast)
    _ = pthread_join(h1, null)
    _ = pthread_join(h2, null)
    return a + b' 42

if [ "$pass" -eq "$total" ]; then
    echo "thread_real_smoke OK: $pass/$total real-thread spawn+join programs compile+run correctly"
else
    echo "thread_real_smoke FAILED: $pass/$total"; exit 1
fi
