#!/usr/bin/env bash
# Behavioral smoke for the operator-operand checks — the type-inference engine's first
# real unlock. A logical `and`/`or` with a firm non-bool operand (parity with stage0's
# "logical operator requires bool operands"), and an arithmetic `+ - * / %` with a firm
# non-numeric operand (parity with stage0's "operator requires numeric operands"), are
# flagged. Sound subset: char arithmetic and unknown operands never fire; 0 FP across
# the frontend + stdlib.
set -uo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
command -v clang >/dev/null 2>&1 || { echo "error: missing clang" >&2; exit 2; }
RPT="$REPO_ROOT/build/parse_report"
mkdir -p "$REPO_ROOT/build"
"$ELISACORE_BIN" -emit obj -O2 -permissive -o "$REPO_ROOT/build/parse_report.o" "$REPO_ROOT/test/breadth/parse_report.elisa" >/dev/null 2>&1
clang -O2 "$REPO_ROOT/build/parse_report.o" -o "$RPT" 2>/dev/null
fail() { echo "operator-operands smoke FAIL: $1" >&2; exit 1; }

# 1. int operand to a logical `and` MUST be flagged.
out=$(printf 'def f(n: i64, m: i64) -> bool:\n    return n and m\n' | "$RPT")
echo "$out" | grep -q "logical 'and' requires bool operands, got int" || fail "int-to-and not flagged: $out"

# 2. string operand to `+` MUST be flagged as non-numeric.
out=$(printf 'def f(s: sview, n: i64) -> i64:\n    x: i64 = s + n\n    return x\n' | "$RPT")
echo "$out" | grep -q "operator '+' requires numeric operands, got string" || fail "string-to-plus not flagged: $out"

# 3. bool operands to `and` must NOT be flagged.
out=$(printf 'def f(a: bool, b: bool) -> bool:\n    return a and b\n' | "$RPT")
echo "$out" | grep -q "requires bool operands" && fail "false positive on bool-and: $out"

# 4. char arithmetic must NOT be flagged (char is numeric-adjacent).
out=$(printf 'def f(c: char) -> i64:\n    x: i64 = c - c\n    return x\n' | "$RPT")
echo "$out" | grep -q "requires numeric operands" && fail "false positive on char arithmetic: $out"

# 5. int arithmetic must NOT be flagged.
out=$(printf 'def f(n: i64) -> i64:\n    return n + n\n' | "$RPT")
echo "$out" | grep -q "requires numeric operands" && fail "false positive on int arithmetic: $out"

# 6. 0 FP across frontend + stdlib.
t=0
while IFS= read -r f; do
  c=$("$RPT" < "$f" 2>/dev/null | grep -cE "requires bool operands|requires numeric operands" || true)
  t=$((t + c))
done < <(find "$REPO_ROOT/src" "$REPO_ROOT/elisacore_std" -name '*.elisa' | grep -v _unused)
[ "$t" -eq 0 ] || fail "$t operator-operand false positives across frontend+stdlib"

echo "operator-operands smoke OK: flags non-bool logical + non-numeric arithmetic operands, silent on bool/char/int, 0 FP across frontend+stdlib"
