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
source "$REPO_ROOT/test/parity/build_parse_report.sh"
fail() { echo "operator-operands smoke FAIL: $1" >&2; exit 1; }

# 1. int operand to a logical `and` MUST be flagged.
out=$(printf 'def f(n: i64, m: i64) -> bool:\n    return n and m\n' | "$RPT")
echo "$out" | grep -q "logical 'and' requires bool operands, got int" || fail "int-to-and not flagged: $out"

# 2. string operand to `+` MUST be flagged as non-numeric.
out=$(printf 'def f(s: sview, n: i64) -> i64:\n    x: i64 = s + n\n    return x\n' | "$RPT")
echo "$out" | grep -q "operator requires numeric operands" || fail "string-to-plus not flagged: $out"

# 3. bool operands to `and` must NOT be flagged.
out=$(printf 'def f(a: bool, b: bool) -> bool:\n    return a and b\n' | "$RPT")
echo "$out" | grep -q "requires bool operands" && fail "false positive on bool-and: $out"

# 4. char arithmetic must NOT be flagged (char is numeric-adjacent).
out=$(printf 'def f(c: char) -> i64:\n    x: i64 = c - c\n    return x\n' | "$RPT")
echo "$out" | grep -q "requires numeric operands" && fail "false positive on char arithmetic: $out"

# 5. int arithmetic must NOT be flagged.
out=$(printf 'def f(n: i64) -> i64:\n    return n + n\n' | "$RPT")
echo "$out" | grep -q "requires numeric operands" && fail "false positive on int arithmetic: $out"

# 6. modulo is integral-only.
out=$(printf 'def f(value: f64) -> f64:\n    return value %% 2.0\n' | "$RPT")
echo "$out" | grep -q "operator requires integral operands" || fail "float modulo not flagged: $out"
out=$(printf 'def f(value: i64) -> i64:\n    return value %% 2\n' | "$RPT")
echo "$out" | grep -q "operator requires integral operands" && fail "false positive on integer modulo: $out"

# 7. fixed arrays require integral indexes.
out=$(printf 'def f(values: i32[4], idx: f64) -> i32:\n    return values[idx]\n' | "$RPT")
echo "$out" | grep -q "index must be integral, got float" || fail "float array index not flagged: $out"
out=$(printf 'def f(values: i32[4], idx: i64) -> i32:\n    return values[idx]\n' | "$RPT")
echo "$out" | grep -q "index must be integral" && fail "false positive on integer array index: $out"

# 8. literal-zero for-range strides are rejected, nonzero strides are valid.
out=$(printf 'def f() -> void:\n    for i in 0..<10..0:\n        pass\n' | "$RPT")
echo "$out" | grep -q "for loop range step cannot be zero" || fail "zero range step not flagged: $out"
out=$(printf 'def f() -> void:\n    for i in 0..<10..2:\n        pass\n' | "$RPT")
echo "$out" | grep -q "for loop range step cannot be zero" && fail "false positive on nonzero range step: $out"

# 9. 0 FP across frontend + stdlib.
t=0
while IFS= read -r f; do
  c=$("$RPT" < "$f" 2>/dev/null | grep -cE "requires bool operands|requires numeric operands|operator requires integral operands|index must be integral|range step cannot be zero" || true)
  t=$((t + c))
done < <(find "$REPO_ROOT/src" "$REPO_ROOT/elisacore_std" -name '*.elisa' | grep -v _unused)
[ "$t" -eq 0 ] || fail "$t operator-operand false positives across frontend+stdlib"

echo "operator-operands smoke OK: flags logical/arithmetic/integral violations, silent on valid operands, 0 FP across frontend+stdlib"
