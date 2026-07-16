#!/usr/bin/env bash
# Packed-enum `as` tests/destructures use qualified pattern targets, infer Store
# parameters, and remain distinct from the removed general `value as Type` cast.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

fail() { echo "packed-pattern smoke FAIL: $1" >&2; exit 1; }
clean() {
    local out
    out="$(printf '%s' "$1" | "$RPT")"
    echo "$out" | grep -q '^P 0$' || fail "parse error: $out"
    echo "$out" | grep -q '^D 0$' || fail "semantic diagnostic: $out"
}

clean $'packed enum Expr:\n    Int(value: int)\n    Add(left: Expr, right: Expr)\n\ndef left_value(node: Expr, store: Expr.Store[Frozen]) -> int:\n    if node as Expr.Add(Expr.Int(value), rhs):\n        _ = rhs\n        return value\n    return 0\n'

clean $'packed enum Expr:\n    Int(value: int)\n    Add(left: Expr, right: Expr)\n\ndef left(node: Expr, store: Expr.Store[Frozen]) -> Expr:\n    move node in store as Expr.Add(lhs, rhs)\n    _ = rhs\n    return lhs\n'

clean $'enum Expr:\n    Int(value: int)\n\ndef check(node: Expr) -> int:\n    can Abort.Panic:\n        expect node as Expr.Int(value):\n            return value\n    return 0\n'

removed="$(printf '%s' $'struct Box:\n    value: int\n\ndef bad(value: int) -> Box:\n    return value as Box\n' | "$RPT")"
echo "$removed" | grep -q '^P 1$' || fail "removed value cast was accepted: $removed"
echo "$removed" | grep -q "unexpected token 'as'" || fail "removed value cast lacks directed error: $removed"

removed_store_as="$(printf '%s' $'packed enum Expr:\n    Lit(value: int)\n\ndef bad(node: Expr, store: Expr.Store[Local]) -> int:\n    if node in store as Expr.Lit(value):\n        return value\n    return 0\n' | "$RPT")"
echo "$removed_store_as" | grep -Eq '^P [1-9][0-9]*$' || fail "removed in-store as binder was accepted: $removed_store_as"

echo "packed-pattern smoke OK: if/move/expect patterns parse and bind; removed value casts stay rejected"
