#!/usr/bin/env bash
# Regression smoke: the type argument of a type-application field op (`x.cast[T]`,
# `.ref[T]`, `.specialize[T]`) is a TYPE, not a value — the resolver must not report it
# as an undefined name. Guards resolve_expr's index_receiver_is_type_application skip,
# while confirming ordinary subscript index expressions (`xs[idx]`) still resolve.
set -uo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
fail() { echo "cast-typearg smoke FAIL: $1" >&2; exit 1; }

# 1. `.cast[T]` to a primitive: the type arg must NOT be an undefined name.
out=$(printf 'def f(x: i32) -> i64:\n    return x.cast[i64]\n' | "$RPT")
echo "$out" | grep -q "undefined name 'i64'" && fail "cast type-arg flagged undefined: $out"

# 2. Same for a local receiver.
out=$(printf 'def f() -> i64:\n    a: i32 = 5\n    return a.cast[i64]\n' | "$RPT")
echo "$out" | grep -q "undefined name" && fail "local cast type-arg flagged undefined: $out"

# 3. A genuinely-undefined VALUE reference is still caught (guard is scoped, not blanket).
out=$(printf 'def f(x: i32) -> i64:\n    return bogusvalue\n' | "$RPT")
echo "$out" | grep -q "undefined name 'bogusvalue'" || fail "real undefined name no longer caught: $out"

# 4. An ordinary subscript index expression is still resolved as a value.
out=$(printf 'def f(xs: darray[i64]) -> i64:\n    return xs[missingidx]\n' | "$RPT")
echo "$out" | grep -q "undefined name 'missingidx'" || fail "ordinary index expr no longer resolved: $out"

echo "cast-typearg smoke OK: .cast/.ref/.specialize type args skipped, real undefined names + ordinary indexing still resolved"
