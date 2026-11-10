#!/usr/bin/env bash
# Compile and execute each real stdlib case through both compiler drivers.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/real_std_runtime_cases.sh"
real_std_collections_setup

deque_case() {
    real_std_runtime_case "collections.elisa" "$@" "${link_inputs[@]}"
}

# push_back two items, then read them back via arena_deque_at (ref-field index): 40 + 2.
deque_case push_at 'def main() -> i64:
    can Abort.Panic, Atomics{Exchange,Load,Store}, Global{Read,Write}, Memory.Allocate, Unsafe{Alias,PointerCast,RawExtern}:
        arena: mutable Arena = zeroed
        d: mutable Deque[i64] = arena_deque_with_capacity[i64](&arena, 4.usize())
        _ = arena_deque_push_back(&arena, &d, 40)
        _ = arena_deque_push_back(&arena, &d, 2)
        a: i64& = arena_deque_at(&d, 0.usize())
        b: i64& = arena_deque_at(&d, 1.usize())
        return a + b' 42
# count reflects the pushes.
deque_case count 'def main() -> i64:
    can Abort.Panic, Atomics{Exchange,Load,Store}, Global{Read,Write}, Memory.Allocate, Unsafe{Alias,PointerCast,RawExtern}:
        arena: mutable Arena = zeroed
        d: mutable Deque[i64] = arena_deque_with_capacity[i64](&arena, 8.usize())
        _ = arena_deque_push_back(&arena, &d, 1)
        _ = arena_deque_push_back(&arena, &d, 2)
        _ = arena_deque_push_back(&arena, &d, 3)
        return d.count.i64() + 39' 42

real_std_runtime_summary "deque_real_smoke"
