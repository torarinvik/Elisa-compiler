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

# An INLINE-storage `@c_opaque` type (pthread_mutex_t) must be sized as its real C `sizeof`, not
# an 8-byte handle — else pthread_mutex_init overruns the alloca and (embedded in a struct)
# silently races. This CROSS-CHECKS stage1's emitted `[N x i8]` blob against C's own sizeof (a
# passing lock/unlock alone can't prove the size — clobbered bytes may be padding), AND runs it.
mutex_case() {
    local name="$1" ctype="$2" body="$3" want="$4"; total=$((total + 1))
    local src="$BUILD/threadreal_$name.elisa" ll="$BUILD/threadreal_$name.ll" obj="$BUILD/threadreal_$name.o" exe="$BUILD/threadreal_$name"
    printf '%s\n%s\n' "$PRELUDE" "$body" > "$src"
    if ! "$ELISACORE_BIN" -emit llvm -o /dev/null "$src" 2>/dev/null; then echo "  FAIL $name: stage0 rejects"; return; fi
    if ! "$EMIT" < "$src" > "$ll" 2>/dev/null || grep -q UNSUPPORTED "$ll"; then echo "  FAIL $name: stage1 declined"; return; fi
    printf '#include <pthread.h>\n#include <stdio.h>\nint main(void){printf("%%zu", sizeof(%s));return 0;}\n' "$ctype" > "$BUILD/sz_$name.c"
    if ! clang -o "$BUILD/sz_$name" "$BUILD/sz_$name.c" 2>/dev/null; then echo "  FAIL $name: C sizeof probe won't build"; return; fi
    local csize; csize="$("$BUILD/sz_$name")"
    local emitted; emitted="$(grep -oE 'alloca \[[0-9]+ x i8\]' "$ll" | grep -oE '[0-9]+' | head -1)"
    if [ -z "$emitted" ]; then echo "  FAIL $name: no [N x i8] opaque blob emitted (still a ptr handle?)"; return; fi
    if [ "$emitted" != "$csize" ]; then echo "  FAIL $name: stage1 sized $ctype as $emitted bytes, C sizeof is $csize (would corrupt)"; return; fi
    if ! "$LLC" -filetype=obj "$ll" -o "$obj" 2>/dev/null; then echo "  FAIL $name: llc rejected the IR"; return; fi
    if ! clang -Wl,-dead_strip -o "$exe" "$obj" "$RUNTIME_OBJ" 2>/dev/null; then echo "  FAIL $name: link failed"; return; fi
    local r
    for r in 1 2 3 4 5; do
        RUN "$exe"; local got=$?
        if [ "$got" -eq 124 ]; then echo "  FAIL $name: TIMED OUT (deadlock?)"; return; fi
        if [ "$got" -ne "$want" ]; then echo "  FAIL $name: run $r exit $got, want $want"; return; fi
    done
    pass=$((pass + 1))
}

# A local pthread_mutex_t: init, 42x lock/increment/unlock, destroy — with the C-sizeof
# cross-check that stage1 sized the opaque as 64 bytes (macOS-arm64), not an 8-byte handle.
mutex_case mutex_count pthread_mutex_t 'extern pthread_mutex_init(mutex: mutable PthreadMutexT&, attr: void&?) -> int can[Memory.Allocate]
extern pthread_mutex_lock(mutex: void&) -> int can[Sync.Lock]
extern pthread_mutex_unlock(mutex: void&) -> int can[Sync.Unlock]
extern pthread_mutex_destroy(mutex: mutable PthreadMutexT&) -> int can[Memory.Release]
@c_opaque(pthread.h, pthread_mutex_t)
extern PthreadMutexT
def main() -> i64 can[Memory.Allocate, Memory.Release, Sync.Lock, Sync.Unlock, Unsafe.PointerCast]:
    m: mutable PthreadMutexT = zeroed
    _ = pthread_mutex_init(&m, null)
    counter: mutable i64 = 0
    for i in 0..<42:
        _ = pthread_mutex_lock((&m).cast[void&] can Unsafe.PointerCast)
        counter <- counter + 1
        _ = pthread_mutex_unlock((&m).cast[void&] can Unsafe.PointerCast)
    _ = pthread_mutex_destroy(&m)
    return counter' 42
# The REAL pattern: a STRUCT-EMBEDDED mutex (as the std wraps it). 4 threads each do 1000
# mutex-protected increments of ONE shared counter → 4000 ONLY if the mutex actually serializes
# the racing increments; a struct-embedded mutex sized as 8 bytes (the pre-fix bug) LOSES updates
# and varies run-to-run. Run 8x, all must be 42 — determinism IS the mutual-exclusion proof.
thread_case mutex_shared 'extern pthread_mutex_init(mutex: mutable PthreadMutexT&, attr: void&?) -> int can[Memory.Allocate]
extern pthread_mutex_lock(mutex: void&) -> int can[Sync.Lock]
extern pthread_mutex_unlock(mutex: void&) -> int can[Sync.Unlock]
@c_opaque(pthread.h, pthread_mutex_t)
extern PthreadMutexT
struct Shared:
    lock: mutable PthreadMutexT
    counter: mutable i64
def worker(arg: void&?) -> void&? can[Sync.Lock, Sync.Unlock, Unsafe.PointerCast]:
    if arg is present:
        s: mutable Shared& = present.cast[mutable Shared&] can Unsafe.PointerCast
        for i in 0..<1000:
            _ = pthread_mutex_lock((&s.lock).cast[void&] can Unsafe.PointerCast)
            s.counter <- s.counter + 1
            _ = pthread_mutex_unlock((&s.lock).cast[void&] can Unsafe.PointerCast)
    return null
def main() -> i64 can[Memory.Allocate, Thread.Spawn, Thread.Join, Sync.Lock, Sync.Unlock, Unsafe.PointerCast]:
    s: mutable Shared = zeroed
    _ = pthread_mutex_init(&s.lock, null)
    handles: mutable uintptr[4] = zeroed
    entry: void& = worker.cast[void&] can Unsafe.PointerCast
    for t in 0..<4:
        _ = pthread_create(&handles[t], null, entry, (&s).cast[void&?] can Unsafe.PointerCast)
    for t in 0..<4:
        _ = pthread_join(handles[t], null)
    return s.counter + 42 - 4000' 42 8

if [ "$pass" -eq "$total" ]; then
    echo "thread_real_smoke OK: $pass/$total real-thread spawn+join programs compile+run correctly"
else
    echo "thread_real_smoke FAILED: $pass/$total"; exit 1
fi
