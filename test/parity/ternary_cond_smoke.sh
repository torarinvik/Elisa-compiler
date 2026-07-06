#!/usr/bin/env bash
# Behavioral smoke for the ternary-condition check (parity with stage0's
# `ternary condition must be bool, got T`). Fires on a non-bool ternary condition,
# stays silent on a bool one and on chained ternaries with bool conditions, and
# produces 0 false positives across the frontend + stdlib.
set -uo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
fail() { echo "ternary-cond smoke FAIL: $1" >&2; exit 1; }

# 1. non-bool (int) ternary condition MUST be flagged.
out=$(printf 'def f(n: i64) -> i64:\n    x: i64 = 1 if n else 2\n    return x\n' | "$RPT")
echo "$out" | grep -q "ternary condition must be bool, got int" || fail "non-bool ternary cond not flagged: $out"

# 2. a bool condition must NOT be flagged.
out=$(printf 'def f(n: i64) -> i64:\n    x: i64 = 1 if n > 0 else 2\n    return x\n' | "$RPT")
echo "$out" | grep -q "ternary condition" && fail "false positive on bool ternary cond: $out"

# 3. chained ternary — inner bool conditions must NOT be flagged.
out=$(printf 'def f(n: i64) -> i64:\n    x: i64 = 1 if n > 0 else (2 if n < 0 else 3)\n    return x\n' | "$RPT")
echo "$out" | grep -q "ternary condition" && fail "false positive on chained bool ternary: $out"

# 4. 0 FP across frontend + stdlib.
t=0
while IFS= read -r f; do
  c=$("$RPT" < "$f" 2>/dev/null | grep -c "ternary condition" || true)
  t=$((t + c))
done < <(find "$REPO_ROOT/src" "$REPO_ROOT/elisacore_std" -name '*.elisa' | grep -v _unused)
[ "$t" -eq 0 ] || fail "$t ternary-condition false positives across frontend+stdlib"

echo "ternary-cond smoke OK: flags non-bool cond, silent on bool/chained, 0 FP across frontend+stdlib"
