#!/usr/bin/env bash
# Behavioral smoke for the stage1 NonExhaustiveMatch diagnostic (parity with stage0's
# `non-exhaustive match over "E"; missing variants: E.C`). Asserts it FIRES on a match that
# omits a variant with no catch-all, and STAYS SILENT on exhaustive matches, wildcards,
# or-patterns, non-enum scrutinees, and across the whole frontend + stdlib (every corpus
# file compiles on stage0, so ANY finding there would be a false positive).
#
# Usage: test/parity/match_exhaustive_smoke.sh
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/structpy-tree}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"

fail() { echo "match-exhaustive smoke FAIL: $1" >&2; exit 1; }

E3='enum E:\n    A\n    B\n    C\n\n'

# 1. a match omitting a variant with no catch-all MUST be flagged.
out=$(printf "${E3}def f(e: E) -> i64:\n    match e:\n        E.A:\n            return 1\n        E.B:\n            return 2\n" | "$RPT")
echo "$out" | grep -q "non-exhaustive match over \"E\"; missing variant \"C\"" || fail "missing variant not flagged: $out"

# 2. an exhaustive match must NOT be flagged.
out=$(printf "${E3}def g(e: E) -> i64:\n    match e:\n        E.A:\n            return 1\n        E.B:\n            return 2\n        E.C:\n            return 3\n" | "$RPT")
echo "$out" | grep -q "non-exhaustive" && fail "false positive on exhaustive match: $out"

# 3. a wildcard makes it exhaustive.
out=$(printf "${E3}def h(e: E) -> i64:\n    match e:\n        E.A:\n            return 1\n        _:\n            return 0\n" | "$RPT")
echo "$out" | grep -q "non-exhaustive" && fail "false positive on wildcard match: $out"

# 4. an or-pattern covering the rest is exhaustive.
out=$(printf "${E3}def k(e: E) -> i64:\n    match e:\n        E.A:\n            return 1\n        E.B | E.C:\n            return 2\n" | "$RPT")
echo "$out" | grep -q "non-exhaustive" && fail "false positive on or-pattern cover: $out"

# 5. an integer (non-enum) match must never be flagged.
out=$(printf 'def m(n: i64) -> i64:\n    match n:\n        0:\n            return 1\n        1:\n            return 2\n' | "$RPT")
echo "$out" | grep -q "non-exhaustive" && fail "false positive on integer match: $out"

# 5b. EXPRESSION-position match/when must be checked too (docs/125 R2 parity with stage0):
#     `x = match e:` / `return when e:` omitting a variant with no `_` MUST be flagged.
out=$(printf "${E3}def p(e: E) -> i64:\n    r: i64 = match e:\n        E.A: 1\n        E.B: 2\n    return r\n" | "$RPT")
echo "$out" | grep -q "non-exhaustive match over \"E\"; missing variant \"C\"" || fail "expr-form match not checked: $out"
out=$(printf "${E3}def q(e: E) -> i64:\n    r: i64 = when e:\n        E.A: 1\n        E.B: 2\n    return r\n" | "$RPT")
echo "$out" | grep -q "non-exhaustive match over \"E\"; missing variant \"C\"" || fail "expr-form when not checked: $out"
out=$(printf "${E3}def r(e: E) -> i64:\n    return when e:\n        E.A: 1\n        E.B: 2\n" | "$RPT")
echo "$out" | grep -q "non-exhaustive match over \"E\"; missing variant \"C\"" || fail "return-position when not checked: $out"
# 5c. an exhaustive expr-form match/when must STAY SILENT.
out=$(printf "${E3}def s(e: E) -> i64:\n    r: i64 = when e:\n        E.A: 1\n        E.B: 2\n        E.C: 3\n    return r\n" | "$RPT")
echo "$out" | grep -q "non-exhaustive" && fail "false positive on exhaustive expr-form when: $out"

# 5d. OPEN-SCALAR totality (docs/125 R2): a value-producing match/when over an int/char/
#     string/float domain with no `_` cannot yield a value for every input — MUST be flagged
#     (applied to match AND when, stricter-but-sound vs stage0's match-only expr rule).
#     The message is stage0's verbatim ("non-exhaustive integer match expression; add a final
#     _ arm"). It used to be stage1's own phrasing, which THIS FILE pinned — a hand-written
#     assertion holding a wording divergence in place, since no diagnostics fixture could
#     carry the rule while the text disagreed with the oracle. There are fixtures now
#     (when_scalar_total / when_tuple_total), so the text is oracle-checked.
out=$(printf 'def f(n: i64) -> i64:\n    r: i64 = match n:\n        0: 1\n        1: 2\n    return r\n' | "$RPT")
echo "$out" | grep -q "add a final _ arm" || fail "open-scalar match without _ not flagged: $out"
out=$(printf 'def f(n: i64) -> i64:\n    r: i64 = when n:\n        0: 1\n        1: 2\n    return r\n' | "$RPT")
echo "$out" | grep -q "add a final _ arm" || fail "open-scalar when without _ not flagged: $out"
# 5e. a `_` arm makes it total; a bool (closed) domain needs no `_`.
out=$(printf 'def f(n: i64) -> i64:\n    r: i64 = when n:\n        0: 1\n        _: 9\n    return r\n' | "$RPT")
echo "$out" | grep -q "add a final _ arm" && fail "false positive on open-scalar with _: $out"
out=$(printf 'def f(b: bool) -> i64:\n    r: i64 = when b:\n        true: 1\n        false: 2\n    return r\n' | "$RPT")
echo "$out" | grep -q "add a final _ arm" && fail "false positive on closed bool domain: $out"

# 6. the whole frontend + stdlib must produce ZERO findings (all compile on stage0 → exhaustive).
n=0
while IFS= read -r f; do
  c=$("$RPT" < "$f" 2>/dev/null | grep -cE "non-exhaustive match|add a final _ arm" || true)
  n=$((n + c))
done < <(find "$REPO_ROOT/src" "$REPO_ROOT/elisacore_std" -name '*.elisa' | grep -v _unused)
[ "$n" -eq 0 ] || fail "$n non-exhaustive false positives across frontend+stdlib"

echo "match-exhaustive smoke OK: enum + open-scalar totality flagged (stmt/expr, match/when), silent on exhaustive/wildcard/or/non-enum/bool, 0 false positives across frontend+stdlib"
