#!/usr/bin/env bash
# Behavioral smoke for stage1 pattern-specific semantic checks:
# - Unknown variant name in match pattern or .Variant shorthand
# - Duplicate variant pattern across arms
# - Pattern payload arity mismatch
# - Match exhaustiveness (single-enum scrutinee)
#
# Parity with stage0's enum + match checking:
#   - UnknownVariant: enum.has_variant(path)
#   - VariantArity: pattern subcount != declared arity
#   - DuplicateVariant / UnreachableMatchArm: duplicate patterns
#   - NonExhaustiveMatch: missing variant with no catch-all
#
# Usage: test/parity/match_pattern_smoke.sh
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
command -v clang >/dev/null 2>&1 || { echo "error: missing clang" >&2; exit 2; }

RPT="$REPO_ROOT/build/parse_report"
mkdir -p "$REPO_ROOT/build"

# Build the test harness. The stage1 frontend builds cleanly (the historical
# docs/119 E4-mutation parser break is resolved), so a build or link failure is
# a real regression and must FAIL the gate — never a silent SKIP.
if ! "$ELISACORE_BIN" -emit obj -O2 -o "$REPO_ROOT/build/parse_report.o" \
    "$REPO_ROOT/test/breadth/parse_report.elisa" >"$REPO_ROOT/build/parse_report.build.log" 2>&1; then
  echo "match-pattern smoke FAIL: stage1 parse_report build broke" >&2
  grep -i "error:" "$REPO_ROOT/build/parse_report.build.log" | head -20 >&2
  exit 1
fi

clang -O2 "$REPO_ROOT/build/parse_report.o" -o "$RPT" 2>"$REPO_ROOT/build/parse_report.link.log" || {
  echo "match-pattern smoke FAIL: clang link failed" >&2
  cat "$REPO_ROOT/build/parse_report.link.log" >&2
  exit 1
}

fail() { echo "match-pattern smoke FAIL: $1" >&2; exit 1; }

E2='enum E:\n    A\n    B\n\n'

# 1. Unknown variant name: E.C when C is not declared in E.
out=$(printf "${E2}def f(e: E) -> i64:\n    match e:\n        E.C:\n            return 0\n" | "$RPT")
echo "$out" | grep -q "has no variant" || fail "unknown variant not flagged: $out"

# 2. Duplicate variant pattern: the second E.A is unreachable.
out=$(printf "${E2}def f(e: E) -> i64:\n    match e:\n        E.A:\n            return 1\n        E.A:\n            return 2\n        E.B:\n            return 3\n" | "$RPT")
echo "$out" | grep -q "unreachable" && echo "found unreachable (expected)" || fail "duplicate pattern not flagged: $out"

# 3. Arity mismatch on an enum with no payload — attempting to destructure it.
out=$(printf "enum E:\n    A\n    B\n\ndef f(e: E) -> i64:\n    match e:\n        E.A(x):\n            return 1\n        E.B:\n            return 2\n" | "$RPT")
echo "$out" | grep -q "variant\|expects.*arguments" && echo "found variant error (arity or name check)" || fail "arity mismatch not flagged: $out"

# 4. Arity mismatch: a variant declared with 2 fields matched with 1 pattern.
out=$(printf "enum E:\n    A(i64, i64)\n    B\n\ndef f(e: E) -> i64:\n    match e:\n        E.A(x):\n            return 1\n        E.B:\n            return 2\n" | "$RPT")
echo "$out" | grep -q "variant\|expects.*arguments" && echo "found variant error (arity check)" || fail "arity mismatch not detected: $out"

# 5. Exhaustiveness: missing variant B.
out=$(printf "${E2}def f(e: E) -> i64:\n    match e:\n        E.A:\n            return 1\n" | "$RPT")
echo "$out" | grep -q "non-exhaustive\|missing" || fail "non-exhaustive match not flagged: $out"

# 6. Exhaustiveness: fully covered, no flag.
out=$(printf "${E2}def f(e: E) -> i64:\n    match e:\n        E.A:\n            return 1\n        E.B:\n            return 2\n" | "$RPT")
echo "$out" | grep -q "non-exhaustive" && fail "false positive on exhaustive match: $out"

# 7. Exhaustiveness: catch-all makes it exhaustive.
out=$(printf "${E2}def f(e: E) -> i64:\n    match e:\n        E.A:\n            return 1\n        _:\n            return 0\n" | "$RPT")
echo "$out" | grep -q "non-exhaustive" && fail "false positive on wildcard catch-all: $out"

# 8. Exhaustiveness: or-pattern makes it exhaustive.
out=$(printf "${E2}def f(e: E) -> i64:\n    match e:\n        E.A | E.B:\n            return 1\n" | "$RPT")
echo "$out" | grep -q "non-exhaustive" && fail "false positive on or-pattern cover: $out"

# 9. Sequence matches require a list pattern or wildcard, never an enum variant.
out=$(printf 'def f(values: view[i32]) -> i64:\n    match values:\n        Token.Region:\n            return 0\n    return 0\n' | "$RPT")
echo "$out" | grep -q 'unsupported top-level sequence match pattern \*ast.MatchVariantPattern' || fail "sequence variant pattern not flagged: $out"
out=$(printf 'def f(values: view[i32]) -> i64:\n    match values:\n        [head, ...tail]:\n            return head\n        _:\n            return 0\n' | "$RPT")
echo "$out" | grep -q 'unsupported top-level sequence match pattern' && fail "false positive on sequence list pattern: $out"

echo "match-pattern smoke OK: all checks fire on violations and silent on correct code"
