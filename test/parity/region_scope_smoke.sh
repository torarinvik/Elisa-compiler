#!/usr/bin/env bash
# Manual region declarations bind a region for following statements; backing
# strategies and explicit @region annotations parse without fabricating blocks.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

fail() { echo "region-scope smoke FAIL: $1" >&2; exit 1; }
clean() {
    local out
    out="$(printf '%s' "$1" | "$RPT")"
    echo "$out" | grep -q '^P 0$' || fail "parse error: $out"
    echo "$out" | grep -q '^D 0$' || fail "semantic diagnostic: $out"
}

clean $'def f(seed: i32) -> i32:\n    region scratch(1024)\n    value: i32& @scratch = new[scratch] seed + 1\n    result: i32 = value[0]\n    destroy scratch\n    return result\n'
clean $'def f() -> void:\n    region a(1024) using reserve_commit\n    region b(1024) using fixed\n    region c(1024) using chained\n    region d(1024) using scratch\n    destroy a\n    destroy b\n    destroy c\n    destroy d\n'
out=$(printf 'def f() -> void:\n    region a(1024) using bogus\n    destroy a\n' | "$RPT")
echo "$out" | grep -q 'unknown region backing "bogus"' || fail "unknown backing strategy was not flagged: $out"
out=$(printf 'def f() -> i64:\n    region r(64)\n    xs: array[i64, 4] @r = zeroed\n    destroy r\n    return xs[0]\n' | "$RPT")
echo "$out" | grep -q "cannot carry a region" || fail "fixed-array region annotation was not flagged: $out"
clean $'def id[T, @r](value: T& @r) -> T& @r:\n    return value\n'

out=$(printf 'def f() -> void:\n    value: i32&? @missing = null\n' | "$RPT")
echo "$out" | grep -q 'unknown region qualifier "missing"' || fail "unknown local region qualifier was not flagged: $out"

out=$(printf 'def f() -> void:\n    region left(64)\n    region right(64)\n    value: i32& @left = new[left] 1\n    other: i32& @right = value\n' | "$RPT")
echo "$out" | grep -q 'variable "other" expects i32& @right, got i32& @left' || fail "mismatched local regions were not flagged: $out"
clean $'def f() -> void:\n    region same(64)\n    value: i32& @same = new[same] 1\n    alias: i32& @same = value\n'

out=$(printf 'def bad() -> i32&:\n    region scratch(64)\n    value: i32& = new[scratch] 1\n    return value\n' | "$RPT")
echo "$out" | grep -q 'cannot return reference: region dependency facts include local region "scratch"' || fail "local-region return escape was not flagged: $out"
out=$(printf 'def bad() -> i32&:\n    region scratch(64)\n    value: i32& = new[scratch] 1\n    return value.cast[i32&]\n' | "$RPT")
echo "$out" | grep -q 'cannot return reference: region dependency facts include local region "scratch"' || fail "cast local-region return escape was not flagged: $out"
clean $'def id[T, @r](value: T& @r) -> T& @r:\n    alias: T& @r = value\n    return alias\n'

out="$(printf '%s' $'def f() -> void:\n    destroy missing\n' | "$RPT")"
echo "$out" | grep -q "undefined identifier 'missing'" || fail "destroy of unknown region was not resolved: $out"

echo "region-scope smoke OK: declarations/strategies/@regions bind; destroy consumes a resolved region"
