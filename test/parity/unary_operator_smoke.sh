#!/usr/bin/env bash
# Behavioral smoke for unary operator checks — `not` on non-bool and `-`/`~` on non-numeric.
# A `not` operator with a firm non-bool operand, or a unary `-`/`~` with a firm non-numeric
# operand, is flagged. Sound subset: unknown operands never fire; 0 FP across the frontend
# + stdlib.
set -uo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
command -v clang >/dev/null 2>&1 || { echo "error: missing clang" >&2; exit 2; }
RPT="$REPO_ROOT/build/parse_report"
mkdir -p "$REPO_ROOT/build"
"$ELISACORE_BIN" -emit obj -O2 -permissive -o "$REPO_ROOT/build/parse_report.o" "$REPO_ROOT/test/breadth/parse_report.elisa" >/dev/null 2>&1
clang -O2 "$REPO_ROOT/build/parse_report.o" -o "$RPT" 2>/dev/null
fail() { echo "unary-operator smoke FAIL: $1" >&2; exit 1; }

# 1. `not` on an int operand MUST be flagged.
out=$(printf 'def f(n: i64) -> bool:\n    return not n\n' | "$RPT")
echo "$out" | grep -q "logical 'not' requires bool operand" || fail "not-on-int not flagged: $out"

# 2. unary `-` on a bool operand MUST be flagged.
out=$(printf 'def f(b: bool) -> i64:\n    x: i64 = -b\n    return x\n' | "$RPT")
echo "$out" | grep -q "operator '-' requires numeric operand" || fail "minus-on-bool not flagged: $out"

# 3. unary `~` on a string operand MUST be flagged.
out=$(printf 'def f(s: sview) -> i64:\n    x: i64 = ~s\n    return x\n' | "$RPT")
echo "$out" | grep -q "operator '~' requires numeric operand" || fail "tilde-on-string not flagged: $out"

# 4. `not` on bool operand must NOT be flagged.
out=$(printf 'def f(b: bool) -> bool:\n    return not b\n' | "$RPT")
echo "$out" | grep -q "requires bool operand" && fail "false positive on not-bool: $out"

# 5. unary `-` on int must NOT be flagged.
out=$(printf 'def f(n: i64) -> i64:\n    return -n\n' | "$RPT")
echo "$out" | grep -q "requires numeric operand" && fail "false positive on minus-int: $out"

# 6. unary `~` on int must NOT be flagged.
out=$(printf 'def f(n: i64) -> i64:\n    return ~n\n' | "$RPT")
echo "$out" | grep -q "requires numeric operand" && fail "false positive on tilde-int: $out"

# 7. 0 FP across frontend + stdlib.
t=0
while IFS= read -r f; do
  c=$("$RPT" < "$f" 2>/dev/null | grep -cE "requires bool operand|requires numeric operand" || true)
  t=$((t + c))
done < <(find "$REPO_ROOT/src" "$REPO_ROOT/elisacore_std" -name '*.elisa' | grep -v _unused)
[ "$t" -eq 0 ] || fail "$t unary-operator false positives across frontend+stdlib"

echo "unary-operator smoke OK: flags not on non-bool and unary -/~ on non-numeric, silent on bool/numeric, 0 FP across frontend+stdlib"
