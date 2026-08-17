#!/usr/bin/env bash
# Regression smoke: the type argument of a type-application field op (`x.cast[T]`,
# `.ref[T]`, `.specialize[T]`) is a TYPE, not a value — the resolver must not report it
# as an undefined identifier. Guards resolve_expr's index_receiver_is_type_application skip,
# while confirming ordinary subscript index expressions (`xs[idx]`) still resolve.
set -uo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
fail() { echo "cast-typearg smoke FAIL: $1" >&2; exit 1; }

# 1. `.cast[T]` to a primitive: the type arg must NOT be an undefined identifier.
out=$(printf 'def f(x: i32) -> i64:\n    return x.cast[i64]\n' | "$RPT")
echo "$out" | grep -q "undefined identifier \"i64\"" && fail "cast type-arg flagged undefined: $out"

# 2. Same for a local receiver.
out=$(printf 'def f() -> i64:\n    a: i32 = 5\n    return a.cast[i64]\n' | "$RPT")
echo "$out" | grep -q "undefined identifier" && fail "local cast type-arg flagged undefined: $out"

# 3. A genuinely-undefined VALUE reference is still caught (guard is scoped, not blanket).
out=$(printf 'def f(x: i32) -> i64:\n    return bogusvalue\n' | "$RPT")
echo "$out" | grep -q "undefined identifier \"bogusvalue\"" || fail "real undefined identifier no longer caught: $out"

# 4. An ordinary subscript index expression is still resolved as a value.
out=$(printf 'def f(xs: darray[i64]) -> i64:\n    return xs[missingidx]\n' | "$RPT")
echo "$out" | grep -q "undefined identifier \"missingidx\"" || fail "ordinary index expr no longer resolved: $out"

# 5. Direct specialization is valid only for a function with generic params.
out=$(printf 'def id(value: int) -> int:\n    return value\ndef run() -> int:\n    return id[int](7)\n' | "$RPT")
echo "$out" | grep -Fq 'function "id" is not generic' || fail "non-generic specialization accepted: $out"
out=$(printf 'def id[T](value: T) -> T:\n    return value\ndef run() -> int:\n    return id[int](7)\n' | "$RPT")
echo "$out" | grep -Fq 'is not generic' && fail "generic specialization rejected: $out"

# 6. A local binding shadows a same-named function and remains ordinary indexing.
out=$(printf 'def item(value: int) -> int:\n    return value\ndef run(item: darray[int]&) -> int:\n    return item[0]\n' | "$RPT")
echo "$out" | grep -Fq 'is not generic' && fail "shadowed local index treated as specialization: $out"

# 7. Explicit generic type arguments must satisfy retained interface bounds.
bounded_prefix='struct BuilderTag:\n    tag: int\n\nprotocol Builder:\n    type State\n    def state() -> State\n\nimpl Builder for BuilderTag:\n    type State = int\n\n    def state() -> int:\n        return 1\n\ndef build[B: Builder]() -> B.State:\n    return B.state()\n'
out=$(printf "${bounded_prefix}\ndef bad() -> int:\n    return build[sview]()\n" | "$RPT")
echo "$out" | grep -Fq 'type "sview" does not satisfy required interface fact "Builder" for type argument' || fail "unsatisfied interface bound accepted: $out"
out=$(printf "${bounded_prefix}\ndef ok() -> int:\n    return build[BuilderTag]()\n" | "$RPT")
echo "$out" | grep -Fq 'does not satisfy required interface fact' && fail "recorded interface implementation rejected: $out"

echo "cast-typearg smoke OK: .cast/.ref/.specialize type args skipped, real undefined identifiers + ordinary indexing still resolved"
