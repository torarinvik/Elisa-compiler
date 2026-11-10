#!/usr/bin/env bash
# Compile and execute each real stdlib case through both compiler drivers.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/real_std_runtime_cases.sh"
real_std_collections_setup

reserve_case() {
    real_std_runtime_case "collections.elisa" "$@" "${link_inputs[@]}"
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

real_std_runtime_summary "reserve_real_smoke"
