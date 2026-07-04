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
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
command -v clang >/dev/null 2>&1 || { echo "error: missing clang" >&2; exit 2; }

RPT="$REPO_ROOT/build/parse_report"
mkdir -p "$REPO_ROOT/build"
"$ELISACORE_BIN" -emit obj -O2 -permissive -o "$REPO_ROOT/build/parse_report.o" "$REPO_ROOT/test/breadth/parse_report.elisa" >/dev/null 2>&1
clang -O2 "$REPO_ROOT/build/parse_report.o" -o "$RPT" 2>/dev/null

fail() { echo "match-exhaustive smoke FAIL: $1" >&2; exit 1; }

E3='enum E:\n    A\n    B\n    C\n\n'

# 1. a match omitting a variant with no catch-all MUST be flagged.
out=$(printf "${E3}def f(e: E) -> i64:\n    match e:\n        E.A:\n            return 1\n        E.B:\n            return 2\n" | "$RPT")
echo "$out" | grep -q "non-exhaustive match over 'E'; missing variant 'C'" || fail "missing variant not flagged: $out"

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

# 6. the whole frontend + stdlib must produce ZERO findings (all compile on stage0 → exhaustive).
n=0
while IFS= read -r f; do
  c=$("$RPT" < "$f" 2>/dev/null | grep -c "non-exhaustive match" || true)
  n=$((n + c))
done < <(find "$REPO_ROOT/src" "$REPO_ROOT/elisacore_std" -name '*.elisa' | grep -v _unused)
[ "$n" -eq 0 ] || fail "$n non-exhaustive false positives across frontend+stdlib"

echo "match-exhaustive smoke OK: flags a missing variant, silent on exhaustive/wildcard/or-pattern/non-enum, 0 false positives across frontend+stdlib"
