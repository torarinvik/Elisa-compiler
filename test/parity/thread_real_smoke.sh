#!/usr/bin/env bash
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/platform.sh"  # host flags/paths: scripts/platform.sh
# Compile and run pthread programs through both compiler drivers.
# This is the first proof that stage1 emits the core concurrency primitives correctly —
# a FUNCTION cast to `void&` as the thread entry point, `pthread_create`/`pthread_join`,
# the `uintptr` handle, and address-of + `void&?` casts to hand a shared cell across the
# thread boundary. A worker's write is observable in main ONLY if join truly waited, so a
# stable exit code across a spawn+join is itself the synchronization assertion.
#
# It is the sub-milestone under the full parallel-for effort (the 124-fn pool/barrier/
# nursery runtime on top of these primitives); the primitives themselves work TODAY.
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/run_timeout.sh"
RUN() { elisa_run_timeout 15 "$@"; }
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISACORE_BIN="${ELISACORE_BIN:-$ROOT/../../Go projects/Elisa-core/compiler/bin/elisac}"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
bash "$ROOT/scripts/assert_stage0_fresh.sh" "$ELISACORE_BIN" || exit $?
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1" || exit $?
LLVM_CONFIG="${LLVM_CONFIG:-$ELISA_LLVM_BIN_DIR/llvm-config}"

[ -x "$ELISACORE_BIN" ] || { echo "thread_real_smoke FAIL: no elisac" >&2; exit 1; }
[ -x "$LLVM_CONFIG" ] || { echo "thread_real_smoke FAIL: no llvm-config" >&2; exit 1; }

LLC="$("$LLVM_CONFIG" --bindir)/llc"
BUILD="$(mktemp -d "${TMPDIR:-/tmp}/elisa-thread-real.XXXXXX")" || exit 1
trap 'rm -rf "$BUILD"' EXIT
RUNTIME_OBJ="${ELISA_RUNTIME_OBJ:-$ROOT/build/runtime/elisacore_runtime.o}"
[ -f "$RUNTIME_OBJ" ] || { echo "thread_real_smoke FAILED: no elisacore_runtime.o"; exit 1; }

# The pthread extern prelude every case shares.
PRELUDE='extern pthread_create(thread: mutable uintptr&, attr: void&?, start_routine: void&, arg: void&?) -> int can[Thread.Spawn]
extern pthread_join(thread: uintptr, retval: mutable void&?) -> int can[Thread.Join]'

pass=0; total=0
run_case() {
    local compiler="$1" name="$2" src="$3" want="$4" times="$5" csize="${6:-}"
    local ll="$BUILD/$name.ll" obj="$BUILD/$name.o" exe="$BUILD/$name"
    if ! "$compiler" -emit llvm -O0 -o "$ll" "$src" >"$BUILD/$name.log" 2>&1 ||
       grep -q '!elisa\.declined' "$ll"; then
        echo "  FAIL $name: compiler rejected or declined the thread program"
        head -5 "$BUILD/$name.log"
        return 1
    fi
    if [[ -n "$csize" ]] && ! awk -v bytes="$csize" '
        /alloca \[[0-9]+ x i[0-9]+\]/ {
            elements = $4
            width = $6
            gsub(/[^0-9]/, "", elements)
            gsub(/[^0-9]/, "", width)
            if (elements * width == 8 * bytes) found = 1
        }
        END { exit !found }
    ' "$ll"; then
        echo "  FAIL $name: expected inline storage matching C sizeof ($csize bytes)"
        return 1
    fi
    if ! "$LLC" -filetype=obj "$ll" -o "$obj"; then
        echo "  FAIL $name: llc rejected the emitted IR"
        return 1
    fi
    if ! clang $ELISA_LD_DEAD_STRIP $ELISA_LINK_EXE_FLAGS -o "$exe" "$obj" "$RUNTIME_OBJ"; then
        echo "  FAIL $name: link failed"
        return 1
    fi
    local r got
    for r in $(seq 1 "$times"); do
        RUN "$exe"; got=$?
        if [ "$got" -eq 124 ]; then echo "  FAIL $name: TIMED OUT (deadlock?)"; return 1; fi
        if [ "$got" -ne "$want" ]; then echo "  FAIL $name: run $r exit $got, want $want"; return 1; fi
    done
}

thread_case() {
    local name="$1" body="$2" want="$3" times="${4:-5}" csize="${5:-}"
    local src="$BUILD/$name.elisa"
    printf '%s\n%s\n' "$PRELUDE" "$body" > "$src"
    total=$((total + 2))
    if run_case "$ELISACORE_BIN" "stage0_$name" "$src" "$want" "$times" "$csize"; then pass=$((pass + 1)); fi
    if run_case "$STAGE1" "stage1_$name" "$src" "$want" "$times" "$csize"; then pass=$((pass + 1)); fi
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
    _ = pthread_create(&handle, null, entry, (&result).cast[void&?] can Unsafe.PointerCast) can Global.Read
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
    _ = pthread_create(&h1, null, entry, (&a).cast[void&?] can Unsafe.PointerCast) can Global.Read
    _ = pthread_create(&h2, null, entry, (&b).cast[void&?] can Unsafe.PointerCast) can Global.Read
    _ = pthread_join(h1, null)
    _ = pthread_join(h2, null)
    return a + b' 42

# An INLINE-storage `@c_opaque` type (pthread_mutex_t) must be sized as its real C `sizeof`, not
# an 8-byte handle — else pthread_mutex_init overruns the alloca and (embedded in a struct)
# silently races. This CROSS-CHECKS stage1's emitted `[N x i8]` blob against C's own sizeof (a
# passing lock/unlock alone can't prove the size — clobbered bytes may be padding), AND runs it.
mutex_case() {
    local name="$1" ctype="$2" body="$3" want="$4" csize
    printf '#include <pthread.h>\n#include <stdio.h>\nint main(void){printf("%%zu", sizeof(%s));return 0;}\n' "$ctype" > "$BUILD/sz_$name.c"
    if ! clang -o "$BUILD/sz_$name" "$BUILD/sz_$name.c" || ! csize="$("$BUILD/sz_$name")"; then
        echo "  FAIL $name: C sizeof probe failed"
        total=$((total + 2))
        return
    fi
    thread_case "$name" "$body" "$want" 5 "$csize"
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
    m: mutable PthreadMutexT = zeroed can Unsafe.PointerCast
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
    s: mutable Shared = zeroed can Unsafe.PointerCast
    _ = pthread_mutex_init(&s.lock, null)
    handles: mutable uintptr[4] = zeroed
    entry: void& = worker.cast[void&] can Unsafe.PointerCast
    for t in 0..<4:
        _ = pthread_create(&handles[t], null, entry, (&s).cast[void&?] can Unsafe.PointerCast) can Global.Read
    for t in 0..<4:
        _ = pthread_join(handles[t], null)
    return s.counter + 42 - 4000' 42 8

# A pthread_cond_t (48 bytes) wait/signal HANDSHAKE, both opaques struct-embedded: main locks,
# waits on the cond until the worker sets `ready` under the lock and signals. Returns 42 only if
# the full protocol works; a mis-sized cond corrupts cond_wait into a deadlock (124) or crash,
# and a lost wakeup would hang — 8 stable 42s prove pthread_cond_t is sized and driven correctly.
thread_case cond_handshake 'extern pthread_mutex_init(mutex: mutable PthreadMutexT&, attr: void&?) -> int can[Memory.Allocate]
extern pthread_mutex_lock(mutex: void&) -> int can[Sync.Lock]
extern pthread_mutex_unlock(mutex: void&) -> int can[Sync.Unlock]
extern pthread_cond_init(cond: mutable PthreadCondT&, attr: void&?) -> int can[Memory.Allocate]
extern pthread_cond_wait(cond: void&, mutex: void&) -> int can[Sync.Wait]
extern pthread_cond_signal(cond: void&) -> int can[Sync.Notify]
@c_opaque(pthread.h, pthread_mutex_t)
extern PthreadMutexT
@c_opaque(pthread.h, pthread_cond_t)
extern PthreadCondT
struct Sync:
    lock: mutable PthreadMutexT
    cond: mutable PthreadCondT
    ready: mutable i64
    result: mutable i64
def worker(arg: void&?) -> void&? can[Sync.Lock, Sync.Unlock, Sync.Notify, Unsafe.PointerCast]:
    if arg is present:
        s: mutable Sync& = present.cast[mutable Sync&] can Unsafe.PointerCast
        lk: void& = (&s.lock).cast[void&] can Unsafe.PointerCast
        cv: void& = (&s.cond).cast[void&] can Unsafe.PointerCast
        _ = pthread_mutex_lock(lk)
        s.result <- 42
        s.ready <- 1
        _ = pthread_cond_signal(cv)
        _ = pthread_mutex_unlock(lk)
    return null
def main() -> i64 can[Memory.Allocate, Thread.Spawn, Thread.Join, Sync.Lock, Sync.Unlock, Sync.Wait, Unsafe.PointerCast]:
    s: mutable Sync = zeroed can Unsafe.PointerCast
    _ = pthread_mutex_init(&s.lock, null)
    _ = pthread_cond_init(&s.cond, null)
    handle: mutable uintptr = 0.uintptr()
    entry: void& = worker.cast[void&] can Unsafe.PointerCast
    _ = pthread_create(&handle, null, entry, (&s).cast[void&?] can Unsafe.PointerCast) can Global.Read
    lk: void& = (&s.lock).cast[void&] can Unsafe.PointerCast
    cv: void& = (&s.cond).cast[void&] can Unsafe.PointerCast
    _ = pthread_mutex_lock(lk)
    while s.ready == 0:
        _ = pthread_cond_wait(cv, lk)
    r: i64 = s.result
    _ = pthread_mutex_unlock(lk)
    _ = pthread_join(handle, null)
    return r' 42 8

if [ "$pass" -eq "$total" ]; then
    echo "thread_real_smoke OK: $pass/$total real-thread spawn+join cases compile and run correctly"
else
    echo "thread_real_smoke FAILED: $pass/$total"; exit 1
fi
