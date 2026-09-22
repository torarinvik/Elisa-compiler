#!/usr/bin/env bash
# `&name` WHERE `name` IS ALREADY A REFERENCE — a `T&&`, never a silent `T&`.
#
# stage1 used to accept `&counter` (counter: `T&` / `mutable T&`) wherever a `T&` was expected
# inside a `catch` guard, a `raise ... if` condition, a module-qualified call, or an immutable
# `T&` parameter, and lowered it to the address of the parameter's own SLOT. The callee then
# read and wrote the wrong memory: elisa-engine hit it as a nondeterministic SIGTRAP in
# World.world_spawn, a wrong audio-recovery target, and a maze client whose input never
# advanced. Only the unqualified plain-statement call was rejected, by a rule that knew one
# destination kind.
#
# stage0's rule (measured): `&ref` is `T&&`, rejected wherever the destination is not `T&&` —
# arguments (positional and named, direct, qualified, UFCS, extern), returns, annotated locals,
# struct-literal fields, typed `with`, and an unannotated local that carries the `T&&` onward.
# stage1 now enforces it with ONE check (check_reference_reborrow) and a backend backstop that
# declines rather than lowers a `T&&` into a `T&`/`T` slot.
#
#   1. every fixture in test/repro/reference_reborrow/rejected/ is rejected by BOTH compilers, and the
#      reported error lines are exactly its `# expect-error-lines:` (no line missed, no
#      unrelated cascade); stage1 names the reference in its sentence;
#   2. test/repro/reference_reborrow/accepted.elisa — the same contexts forwarded bare, plus the
#      `&ref` shapes whose destination really is `T&&`, plus the REBORROW cast `(&ref).cast[U&]`
#      — is accepted by both and RUNS to 0 under stage1 (each check returns its own number on a
#      wrong answer). A bare `&ref` is the reference's SLOT; a cast of it reinterprets the
#      REFERENT, as stage0 always has (`grow((&self).cast[mutable Mod&])` with
#      `self: mutable Mod&` must grow the caller's Mod);
#   3. `lock mu as g:` with `mu: mutable Mutex&` and `submit[p]` with `p: mutable ThreadPool&`
#      — the backend's own synthesized `&mu` / `&p` — use the real mutex and pool.
#
# stage0 is not run in (2): it types `&ref` as `T&&` but lowers a bare one to the reference
# itself, so its `takes_rr(&counter)` dereferences `values[0]` and segfaults.
set -uo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
FIXTURES="$ROOT/test/repro/reference_reborrow/rejected"
OK_FIXTURE="$ROOT/test/repro/reference_reborrow/accepted.elisa"
ELISA_CORE="${ELISA_CORE:-$ROOT/../../Go projects/Elisa-core}"

stage0="${ELISACORE_BIN:-$ELISA_CORE/compiler/bin/elisac}"
if [[ -z "${ELISACORE_BIN:-}" ]]; then
    mkdir -p "$(dirname "$stage0")"
    ( cd "$ELISA_CORE/compiler" && go build -o "$stage0" ./src ) || { echo "reference-reborrow FAIL: cannot build stage0" >&2; exit 2; }
fi
[[ -x "$stage0" ]] || { echo "reference-reborrow FAIL: missing stage0 at $stage0" >&2; exit 2; }
stage1=(bash "$ROOT/scripts/elisac_stage1.sh")

# stage0 writes a ZERO-BYTE object for a source under /private/tmp; mktemp's default can be one.
work="$(mktemp -d /tmp/reference_reborrow.XXXXXX)"
trap 'rm -rf "$work"' EXIT INT TERM HUP
failed=0
fail() { echo "  FAIL $1"; failed=$((failed + 1)); }

# The distinct lines a compiler blamed in FILE (basename), space-separated and sorted.
error_lines() {   # log basename
    grep -oE "$2:[0-9]+" "$1" | cut -d: -f2 | sort -un | tr '\n' ' ' | sed 's/ $//'
}

count=0
for fixture in "$FIXTURES"/*.elisa; do
    name="$(basename "$fixture")"
    want="$(sed -n 's/^# expect-error-lines: //p' "$fixture" | tr ' ' '\n' | sort -un | tr '\n' ' ' | sed 's/ $//')"
    [[ -n "$want" ]] || { fail "$name has no '# expect-error-lines:' header"; continue; }
    cp "$fixture" "$work/$name"
    count=$((count + 1))

    "$stage0" -emit obj -o "$work/$name.s0.o" "$work/$name" >/dev/null 2>"$work/$name.s0.err"
    rc=$?
    got="$(error_lines "$work/$name.s0.err" "$name")"
    if [[ "$rc" -eq 0 ]]; then
        fail "stage0 accepts $name (the oracle changed? want errors on lines $want)"
    elif [[ "$got" != "$want" ]]; then
        fail "stage0 blames lines [$got] in $name, want [$want]"
    fi

    "${stage1[@]}" -emit obj -o "$work/$name.s1.o" "$work/$name" >/dev/null 2>"$work/$name.s1.err"
    rc=$?
    got="$(error_lines "$work/$name.s1.err" "$name")"
    if [[ "$rc" -eq 0 ]]; then
        fail "stage1 accepts $name — the re-borrow is miscompiled again (want errors on lines $want)"
    elif [[ "$got" != "$want" ]]; then
        fail "stage1 blames lines [$got] in $name, want [$want]"
        sed 's/^/      /' "$work/$name.s1.err" | head -6
    elif ! grep -Eq 'already a reference|is a reference to the reference' "$work/$name.s1.err"; then
        fail "stage1 rejects $name for another reason:"
        sed 's/^/      /' "$work/$name.s1.err" | head -6
    fi
done
[[ "$count" -gt 0 ]] || fail "no fixtures under $FIXTURES"

cp "$OK_FIXTURE" "$work/ok.elisa"
if ! "$stage0" -emit obj -o "$work/ok.s0.o" "$work/ok.elisa" >"$work/ok.s0.err" 2>&1; then
    fail "stage0 rejects the positive fixture:"
    sed 's/^/      /' "$work/ok.s0.err" | head -6
fi
if "${stage1[@]}" -emit exe -o "$work/ok" "$work/ok.elisa" >"$work/ok.s1.err" 2>&1; then
    "$work/ok" </dev/null >/dev/null 2>&1
    rc=$?
    [[ "$rc" -eq 0 ]] || fail "stage1's positive fixture exits $rc: check $rc in accepted.elisa saw the wrong Counter"
else
    fail "stage1 rejects or declines the positive fixture:"
    sed 's/^/      /' "$work/ok.s1.err" | head -6
fi

# 3. The backend SYNTHESIZES `&target` for `lock target as g:` (`mutex_lock(&target)`). When the
#    target is itself a reference parameter that must be the reference, not its slot: stage0
#    passes the loaded pointer; stage1 used to lock the slot, and now hands the reference over
#    as-is (codegen_stmt_blocks_exprs.elisa).
cat >"$work/lock.elisa" <<EOF
include "$ROOT/elisacore_std/elisacore_runtime.elisa"

def bump(mu: mutable Mutex&, total: mutable i64&) -> void:
    can Sync.Lock, Sync.Unlock, Abort.Panic:
        lock mu as g:
            total <- total + 1

def main() -> i64:
    can Memory.Allocate, Memory.Release, Sync.Lock, Sync.Unlock, Abort.Panic:
        mu: mutable Mutex = mutex()
        total: mutable i64 = 0
        bump(&mu, &total)
        bump(&mu, &total)
        mutex_dispose(&mu)
        return 0 if total == 2
        return 1
EOF
if ! "$stage0" -emit obj -o "$work/lock.s0.o" "$work/lock.elisa" >"$work/lock.s0.err" 2>&1; then
    fail "stage0 rejects \`lock\` on a reference parameter:"
    sed 's/^/      /' "$work/lock.s0.err" | head -6
fi
if "${stage1[@]}" -emit exe -o "$work/lock" "$work/lock.elisa" >"$work/lock.s1.err" 2>&1; then
    "$work/lock" </dev/null >/dev/null 2>&1
    rc=$?
    [[ "$rc" -eq 0 ]] || fail "\`lock\` on a reference parameter exits $rc under stage1 (locked the slot?)"
else
    fail "stage1 rejects or declines \`lock\` on a reference parameter:"
    sed 's/^/      /' "$work/lock.s1.err" | head -6
fi

# `submit[p] f(x)` synthesizes `pool_submit(&p, ...)` the same way.
cat >"$work/submit.elisa" <<EOF
include "$ROOT/elisacore_std/elisacore_runtime.elisa"

def sq(n: i64) -> i64:
    n * n

def run(p: mutable ThreadPool&) -> i64:
    can Pool.Submit, Pool.Await, Memory.Allocate, Memory.Release, Abort.Panic, Atomics.Load, Atomics.CompareExchange, Thread.Spawn, Thread.Join:
        task: Task[i64, Pending] = submit[p] sq(7)
        return pool_await(move task)

def main() -> i64:
    can Pool.Create, Pool.Submit, Pool.Await, Pool.Shutdown, Thread.Spawn, Thread.Join, Memory.Allocate, Memory.Release, Atomics.Load, Atomics.CompareExchange, Abort.Panic:
        pool: mutable ThreadPool = pool_new(2)
        got: i64 = run(&pool)
        pool_shutdown(&pool)
        return 0 if got == 49
        return 1
EOF
if ! "$stage0" -emit obj -o "$work/submit.s0.o" "$work/submit.elisa" >"$work/submit.s0.err" 2>&1; then
    fail "stage0 rejects \`submit[p]\` on a reference parameter:"
    sed 's/^/      /' "$work/submit.s0.err" | head -6
fi
if "${stage1[@]}" -emit exe -o "$work/submit" "$work/submit.elisa" >"$work/submit.s1.err" 2>&1; then
    "$work/submit" </dev/null >/dev/null 2>&1
    rc=$?
    [[ "$rc" -eq 0 ]] || fail "\`submit[p]\` on a reference parameter exits $rc under stage1 (submitted through the slot?)"
else
    fail "stage1 rejects or declines \`submit[p]\` on a reference parameter:"
    sed 's/^/      /' "$work/submit.s1.err" | head -6
fi

if [[ "$failed" -gt 0 ]]; then
    echo "reference-reborrow FAILED: $failed failures"
    exit 1
fi
echo "reference-reborrow OK: $count contexts rejected by both compilers on the expected lines; bare forwarding, real T&&, reborrow casts, and lock/submit on a reference run correctly"
