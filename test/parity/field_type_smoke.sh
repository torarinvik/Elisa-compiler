#!/usr/bin/env bash
# Behavioral smoke for field-access typing — the type-inference engine's batch-3 unlock.
# `obj.field` now infers the field's declared type (via the struct-field registry), so the
# existing condition / operator-operand checks fire through a struct field. A struct int
# field used as an if-condition or a logical operand is flagged; a bool field is silent;
# 0 FP across the frontend + stdlib.
set -uo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/structpy-tree}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
fail() { echo "field-type smoke FAIL: $1" >&2; exit 1; }

# 1. a struct int field used as an if-condition MUST flag NonBoolCondition.
out=$(printf 'struct Point:\n    x: i64\n    y: i64\n\ndef f(p: Point) -> i64:\n    if p.x:\n        return 1\n    return 0\n' | "$RPT")
echo "$out" | grep -q "if condition must be bool, got i64" || fail "int field-as-condition not flagged: $out"

# 2. a struct int field as a logical operand MUST flag NonBoolOperand.
out=$(printf 'struct Point:\n    x: i64\n\ndef f(p: Point) -> bool:\n    return p.x and p.x\n' | "$RPT")
echo "$out" | grep -q "logical operator requires bool operands" || fail "int field-as-operand not flagged: $out"

# 3. a bool field used as a condition must NOT be flagged.
out=$(printf 'struct Flags:\n    on: bool\n\ndef f(fl: Flags) -> i64:\n    if fl.on:\n        return 1\n    return 0\n' | "$RPT")
echo "$out" | grep -q "condition must be bool" && fail "false positive on bool field condition: $out"

# 4. 0 FP across frontend + stdlib.
t=0
while IFS= read -r f; do
  c=$("$RPT" < "$f" 2>/dev/null | grep -cE "must be bool|requires bool operands|requires numeric operands" || true)
  t=$((t + c))
done < <(find "$REPO_ROOT/src" "$REPO_ROOT/elisacore_std" -name '*.elisa' | grep -v _unused)
[ "$t" -eq 0 ] || fail "$t type-check false positives across frontend+stdlib"

echo "field-type smoke OK: obj.field typed, feeds condition/operand checks, silent on bool field, 0 FP across frontend+stdlib"
