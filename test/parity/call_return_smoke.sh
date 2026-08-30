#!/usr/bin/env bash
# Behavioral smoke for call-return typing — the type-inference engine's batch-4 unlock.
# A direct call `f(...)` to a uniquely-named function infers that function's return type,
# so the existing condition / operator checks fire through a call. An int-returning call
# used as a condition/operand is flagged; a bool-returning call is silent; an OVERLOADED
# name is ambiguous and stays silent (sound). 0 FP across the frontend + stdlib.
set -uo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/structpy-tree}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
fail() { echo "call-return smoke FAIL: $1" >&2; exit 1; }

# 1. an int-returning call used as an if-condition MUST flag NonBoolCondition.
out=$(printf 'def g(n: i64) -> i64:\n    return n\n\ndef f() -> i64:\n    if g(1):\n        return 1\n    return 0\n' | "$RPT")
echo "$out" | grep -q "if condition must be bool, got i64" || fail "int-returning call-as-condition not flagged: $out"

# 2. an int-returning call as a logical operand MUST flag NonBoolOperand.
out=$(printf 'def g() -> i64:\n    return 1\n\ndef f() -> bool:\n    return g() and g()\n' | "$RPT")
echo "$out" | grep -q "logical operator requires bool operands" || fail "int-returning call-as-operand not flagged: $out"

# 3. a bool-returning call as a condition must NOT be flagged.
out=$(printf 'def ok() -> bool:\n    return true\n\ndef f() -> i64:\n    if ok():\n        return 1\n    return 0\n' | "$RPT")
echo "$out" | grep -q "condition must be bool" && fail "false positive on bool-returning call: $out"

# 4. an OVERLOADED name (ambiguous return type) must NOT be flagged.
out=$(printf 'def g(n: i64) -> i64:\n    return n\n\ndef g(s: sview) -> bool:\n    return true\n\ndef f() -> i64:\n    if g(1):\n        return 1\n    return 0\n' | "$RPT")
echo "$out" | grep -q "condition must be bool" && fail "false positive on overloaded call: $out"

# 5. reduce_sum requires a numeric callback return, but accepts numeric callbacks.
out=$(printf 'def positive(value: i64) -> bool:\n    return value > 0\ndef bad(values: darray[i64]) -> i64:\n    return reduce_sum(readonly(values), positive)\n' | "$RPT")
echo "$out" | grep -Fq 'reduce_sum callback must return a numeric accumulator' || fail "bool reduce_sum callback accepted: $out"
out=$(printf 'def identity(value: i64) -> i64:\n    return value\ndef ok(values: darray[i64]) -> i64:\n    return reduce_sum(readonly(values), identity)\n' | "$RPT")
echo "$out" | grep -Fq 'reduce_sum callback must return a numeric accumulator' && fail "numeric reduce_sum callback rejected: $out"

# 6. 0 FP across frontend + stdlib.
t=0
while IFS= read -r f; do
  c=$("$RPT" < "$f" 2>/dev/null | grep -cE "must be bool|requires bool operands|requires numeric operands" || true)
  t=$((t + c))
done < <(find "$REPO_ROOT/src" "$REPO_ROOT/elisacore_std" -name '*.elisa' | grep -v _unused)
[ "$t" -eq 0 ] || fail "$t type-check false positives across frontend+stdlib"

echo "call-return smoke OK: direct call typed by return type, feeds condition/operand checks, overload-ambiguous silent, 0 FP across frontend+stdlib"
