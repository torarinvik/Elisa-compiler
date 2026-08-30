#!/usr/bin/env bash
# Packed-enum `as` tests/destructures use qualified pattern targets, infer Store
# parameters, and remain distinct from the removed general `value as Type` cast.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/structpy-tree}"
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

clean $'packed enum Expr:\n    common:\n        @storage(side_table)\n        span: int\n    Int(value: int)\n    End\n\ndef build(store: Expr.Store[Local]) -> Expr:\n    return Expr.Int(value: 2)\n'

clean $'packed enum Expr:\n    Int(value: int)\n    Add(left: Expr, right: Expr)\n\ndef left(node: Expr, store: Expr.Store[Frozen]) -> Expr:\n    move node in store as Expr.Add(lhs, rhs)\n    _ = rhs\n    return lhs\n'

wrong_store="$(printf '%s' $'packed enum Expr:\n    Int(value: int)\n\npacked enum Token:\n    Ident\n\ndef bad(node: Expr, store: Token.Store[Local]) -> int:\n    move node in store as Expr.Int(value)\n    return value\n' | "$RPT")"
echo "$wrong_store" | grep -q '^D 1$' || fail "wrong packed Store owner was not rejected exactly once: $wrong_store"
echo "$wrong_store" | grep -q "requires store type \"Expr.Store\", got Token.Store" || fail "wrong packed Store diagnostic missing: $wrong_store"

store_assign=$(printf 'packed enum Expr:\n    Int(value: int)\n\ndef bad(store: Expr.Store[Frozen], node: Expr) -> void:\n    store[0] <- node\n' | "$RPT")
echo "$store_assign" | grep -Fq 'cannot assign to packed store index result' || fail "packed store index assignment not flagged: $store_assign"

bare_ctor=$(printf 'packed enum Expr:\n    Int(value: int)\n\ndef bad() -> Expr:\n    return Expr.Int(value: 1)\n' | "$RPT")
echo "$bare_ctor" | grep -Fq 'packed enum constructor "Expr.Int" requires an active in Expr.Store' || fail "bare packed constructor not flagged: $bare_ctor"
clean $'packed enum Expr:\n    Int(value: int)\n\ndef build(owner: Arena) -> Expr:\n    store: Expr.Store[Local] = Expr.Store(owner)\n    return Expr.Int(value: 1)\n'

missing_match_store=$(printf 'packed enum Expr:\n    Int(value: int)\n\ndef bad(node: Expr) -> int:\n    match node:\n        Expr.Int(value: value):\n            return value\n' | "$RPT")
echo "$missing_match_store" | grep -Fq 'packed enum match over "Expr" requires an in Expr.Store clause' || fail "packed match without store not flagged: $missing_match_store"
ordinary_store=$(printf 'enum Expr:\n    Int(value: int)\npacked enum PackedExpr:\n    Int(value: int)\ndef bad(node: Expr, store: PackedExpr.Store[Local]) -> int:\n    match node in store:\n        Expr.Int(value: value):\n            return value\n' | "$RPT")
echo "$ordinary_store" | grep -Fq 'ordinary enum match over "Expr" does not take an in-store clause' || fail "ordinary match store clause not flagged: $ordinary_store"

missing_if_binder=$(printf 'packed enum Expr:\n    Int(value: int)\ndef bad(node: Expr, store: Expr.Store[Local]) -> int:\n    if node in store:\n        return 1\n    return 0\n' | "$RPT")
echo "$missing_if_binder" | grep -Fq 'if pattern binder requires `as Enum.Variant(...)` after store expression' || fail "packed if-store binder omission not flagged: $missing_if_binder"
clean $'def contains(value: int, values: darray[int]&) -> bool:\n    if value in values:\n        return true\n    return false\n'

ordinary_variant_type=$(printf 'enum Expr:\n    Int(value: int)\ndef bad(node: Expr.Int) -> int:\n    return 0\n' | "$RPT")
echo "$ordinary_variant_type" | grep -Fq 'bare variant type "Expr.Int" requires a packed enum or tree category' || fail "ordinary bare variant type not flagged: $ordinary_variant_type"
clean $'packed enum Expr:\n    Int(value: int)\ndef ok(node: Expr.Int) -> int:\n    return 0\n'

clean $'enum Expr:\n    Int(value: int)\n\ndef check(node: Expr) -> int:\n    can Abort.Panic:\n        expect node as Expr.Int(value):\n            return value\n    return 0\n'

removed="$(printf '%s' $'struct Box:\n    value: int\n\ndef bad(value: int) -> Box:\n    return value as Box\n' | "$RPT")"
echo "$removed" | grep -q '^P 1$' || fail "removed value cast was accepted: $removed"
echo "$removed" | grep -q "unexpected token \"as\"" || fail "removed value cast lacks directed error: $removed"

removed_abi=$(printf '@packed_abi(dense_fixed)\npacked enum Expr:\n    Lit(value: int)\n' | "$RPT")
echo "$removed_abi" | grep -Fq '@packed_abi on enum "Expr" has been removed' || fail "removed packed ABI annotation not flagged: $removed_abi"
removed_prefix=$(printf '@packed_prefix(common_only)\npacked enum Expr:\n    common:\n        span: int\n    Lit(value: int)\n' | "$RPT")
echo "$removed_prefix" | grep -Fq '@packed_prefix on enum "Expr" has been removed' || fail "removed packed prefix annotation not flagged: $removed_prefix"

removed_store_as="$(printf '%s' $'packed enum Expr:\n    Lit(value: int)\n\ndef bad(node: Expr, store: Expr.Store[Local]) -> int:\n    if node in store as Expr.Lit(value):\n        return value\n    return 0\n' | "$RPT")"
echo "$removed_store_as" | grep -Eq '^P [1-9][0-9]*$' || fail "removed in-store as binder was accepted: $removed_store_as"

move_arity="$(printf '%s' $'struct Pair:\n    left: mutable i64\n    right: mutable i64\n\ndef bad(pair: Pair) -> void:\n    move pair as Pair(left)\n' | "$RPT")"
echo "$move_arity" | grep -q '^D 1$' || fail "move struct arity mismatch was not rejected exactly once: $move_arity"
echo "$move_arity" | grep -q "move-as pattern \"Pair\" expects 2 bindings, got 1" || fail "move struct arity diagnostic missing: $move_arity"

clean $'struct Pair:\n    left: mutable i64\n    right: mutable i64\n\ndef take(pair: Pair) -> i64:\n    move pair as Pair(left, right)\n    return left + right\n'

echo "packed-pattern smoke OK: if/move/expect patterns parse and bind with arity checks; removed value casts stay rejected"
