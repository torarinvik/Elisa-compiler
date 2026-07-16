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
clean $'def id[T, @r](value: T& @r) -> T& @r:\n    return value\n'

out="$(printf '%s' $'def f() -> void:\n    destroy missing\n' | "$RPT")"
echo "$out" | grep -q "undefined name 'missing'" || fail "destroy of unknown region was not resolved: $out"

echo "region-scope smoke OK: declarations/strategies/@regions bind; destroy consumes a resolved region"
