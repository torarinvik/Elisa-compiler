#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE1="${ELISA_STAGE1_BIN:-$ROOT/bin/elisac-stage1}"
bash "$ROOT/scripts/assert_stage1_fresh.sh" "$STAGE1"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/elisa-nursery-on-pool.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

cat >"$WORK/shared-pool.elisa" <<'ELISA'
struct ThreadPool:
    handle: void&?

struct TaskGroup:
    handle: void&?
    cleanup: void&?

struct Task[T, S]:
    handle: usize
    state: void&?

def pool_new(threads: usize) -> ThreadPool:
    return ThreadPool{handle: null}

def pool_shutdown(pool: ThreadPool&) -> void:
    return

def task_group_new() -> TaskGroup:
    return TaskGroup{handle: null, cleanup: null}

def task_group_wait_all(group: TaskGroup&) -> void:
    return

def pool_submit1[A, R](pool: ThreadPool&, fn: fn(A) -> R, arg: A) -> Task[R, i64]:
    return zeroed

def task_group_add[R](group: TaskGroup&, task: Task[R, i64]) -> void:
    _ = move task
    return

def bump(value: i64) -> i64:
    return value + 1

def early_exit() -> i64:
    workers: mutable ThreadPool = pool_new(1)
    nursery on(workers):
        submit bump(41)
        return 17
    return 0

def main() -> i64:
    workers: mutable ThreadPool = pool_new(2)
    nursery on(workers):
        workers: i64 = 1
        submit bump(41)
    return 42
ELISA

if ! env -u ELISA_STAGE1_RUNTIME_STD "$STAGE1" -emit fmt -o "$WORK/shared-pool.fmt" "$WORK/shared-pool.elisa" >"$WORK/fmt.log" 2>&1; then
    cat "$WORK/fmt.log" >&2
    exit 1
fi
grep -Fq 'nursery on(workers):' "$WORK/shared-pool.fmt" || {
    echo "nursery on(pool) formatter did not preserve the borrowed-pool header" >&2
    cat "$WORK/shared-pool.fmt" >&2
    exit 1
}

if ! env -u ELISA_STAGE1_RUNTIME_STD "$STAGE1" -emit llvm -O0 -o "$WORK/shared-pool.ll" "$WORK/shared-pool.elisa" >"$WORK/valid.log" 2>&1; then
    cat "$WORK/valid.log" >&2
    exit 1
fi
awk '/^define .*@main\(/,/^}/' "$WORK/shared-pool.ll" >"$WORK/main.ll"
grep -Eq 'call .*@pool_submit1[^;]*ptr %workers[, )]' "$WORK/main.ll" || {
    echo "implicit submit did not use the caller-owned pool slot after a body-local shadow" >&2
    grep -n 'pool_submit1\|pool_new\|task_group_wait_all\|pool_shutdown' "$WORK/main.ll" >&2 || true
    exit 1
}
grep -Eq 'call .*@task_group_wait_all' "$WORK/main.ll" || {
    echo "shared-pool nursery did not join its implicit TaskGroup" >&2
    cat "$WORK/main.ll" >&2
    exit 1
}
if grep -Eq 'call .*@pool_shutdown' "$WORK/main.ll"; then
    echo "shared-pool nursery shut down a caller-owned pool" >&2
    cat "$WORK/main.ll" >&2
    exit 1
fi
pool_creations="$(grep -Ec 'call .*@pool_new' "$WORK/main.ll" || true)"
if [[ "$pool_creations" -ne 1 ]]; then
    echo "shared-pool nursery created $pool_creations pools in main; expected only the caller-owned pool" >&2
    grep -n 'pool_new\|pool_shutdown' "$WORK/main.ll" >&2 || true
    exit 1
fi

awk '/^define .*@early_exit\(/,/^}/' "$WORK/shared-pool.ll" >"$WORK/early-exit.ll"
join_line="$(grep -n 'call .*@task_group_wait_all' "$WORK/early-exit.ll" | head -n 1 | cut -d: -f1 || true)"
return_line="$(grep -n 'ret i64 17' "$WORK/early-exit.ll" | head -n 1 | cut -d: -f1 || true)"
if [[ -z "$join_line" || -z "$return_line" || "$join_line" -ge "$return_line" ]]; then
    echo "early return bypassed the shared-pool nursery TaskGroup join" >&2
    cat "$WORK/early-exit.ll" >&2
    exit 1
fi
if grep -Eq 'call .*@pool_shutdown' "$WORK/early-exit.ll"; then
    echo "early return shut down a caller-owned pool" >&2
    cat "$WORK/early-exit.ll" >&2
    exit 1
fi

cat >"$WORK/wrong-type.elisa" <<'ELISA'
def main() -> i64:
    value: i64 = 1
    nursery on(value):
        pass
    return 0
ELISA
if env -u ELISA_STAGE1_RUNTIME_STD "$STAGE1" -emit llvm -O0 -o "$WORK/wrong-type.ll" "$WORK/wrong-type.elisa" >"$WORK/wrong-type.log" 2>&1; then
    echo "nursery on(pool) accepted a non-ThreadPool value" >&2
    exit 1
fi
grep -Fq 'ThreadPool' "$WORK/wrong-type.log" || {
    echo "wrong-pool diagnostic did not identify ThreadPool" >&2
    cat "$WORK/wrong-type.log" >&2
    exit 1
}

cat >"$WORK/immutable-pool.elisa" <<'ELISA'
struct ThreadPool:
    handle: void&?

def pool_new(threads: usize) -> ThreadPool:
    return ThreadPool{handle: null}

def main() -> i64:
    workers: ThreadPool = pool_new(2)
    nursery on(workers):
        pass
    return 0
ELISA
if env -u ELISA_STAGE1_RUNTIME_STD "$STAGE1" -emit llvm -O0 -o "$WORK/immutable-pool.ll" "$WORK/immutable-pool.elisa" >"$WORK/immutable-pool.log" 2>&1; then
    echo "nursery on(pool) accepted an immutable pool binding" >&2
    exit 1
fi
grep -Fq 'mutable ThreadPool' "$WORK/immutable-pool.log" || {
    echo "immutable-pool diagnostic did not explain the mutability requirement" >&2
    cat "$WORK/immutable-pool.log" >&2
    exit 1
}

cat >"$WORK/malformed.elisa" <<'ELISA'
def main() -> i64:
    workers: i64 = 1
    nursery on(workers + 1):
        pass
    return 0
ELISA
if env -u ELISA_STAGE1_RUNTIME_STD "$STAGE1" -emit fmt -o "$WORK/malformed.fmt" "$WORK/malformed.elisa" >"$WORK/malformed.log" 2>&1; then
    echo "parser accepted an expression where nursery on(...) requires one pool identifier" >&2
    exit 1
fi

echo "nursery on(pool) smoke OK: formatter, pool type and mutability checks, implicit submit target, and caller-owned pool lifetime"
