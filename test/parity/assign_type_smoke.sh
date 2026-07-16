#!/usr/bin/env bash
# Type compatibility checks on variable declarations and assignments.
# Tests that:
# 1. `x: T = v` where v's type is incompatible with T is flagged as TypeMismatch
# 2. `x <- v` where v's type is incompatible with binding's type is flagged
# 3. `return v` where v's type is incompatible with declared return type is flagged
# 4. `s.f <- v` where v's type is incompatible with field's type is flagged
# All checks are conservative: only when BOTH types are firm/known. No false positives.
set -uo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
fail() { echo "assign-type smoke FAIL: $1" >&2; exit 1; }

# 1. VarDecl with bool expecting literal int MUST flag TypeMismatch.
out=$(printf 'def f() -> void:\n    x: bool = 5\n' | "$RPT")
echo "$out" | grep -q "expects bool, got int" || fail "VarDecl literal mismatch not flagged: $out"

# 2. VarDecl with i64 expecting literal bool MUST flag TypeMismatch.
out=$(printf 'def f() -> void:\n    y: i64 = true\n' | "$RPT")
echo "$out" | grep -q "expects i64, got bool" || fail "VarDecl bool->int not flagged: $out"

# 3. VarDecl with matching types must NOT flag.
out=$(printf 'def f() -> void:\n    z: i64 = 5\n' | "$RPT")
echo "$out" | grep -q "expects i64" && fail "false positive on matching VarDecl: $out"

# 4. Assignment rebind with <- and type mismatch MUST flag.
out=$(printf 'def f() -> void:\n    a: mutable bool = false\n    a <- 10\n' | "$RPT")
echo "$out" | grep -q "expects bool, got int" || fail "Assign <- mismatch not flagged: $out"

# 5. Assignment rebind with matching type must NOT flag.
out=$(printf 'def f() -> void:\n    b: mutable i64 = 0\n    b <- 10\n' | "$RPT")
echo "$out" | grep -q "expects i64" && fail "false positive on matching Assign <-: $out"

# A void call cannot satisfy a value-returning function's return type.
out=$(printf 'def helper() -> void:\n    return\ndef f() -> i64:\n    return helper()\n' | "$RPT")
echo "$out" | grep -q "return type expects i64, got void" || fail "void call return mismatch not flagged: $out"

# An unannotated empty array binding has no element-type context.
out=$(printf 'def f() -> void:\n    values = []\n' | "$RPT")
echo "$out" | grep -q "empty list literal requires an expected array or darray type" || fail "context-free empty array not flagged: $out"
out=$(printf 'def f() -> void:\n    values: darray[i64] = []\n' | "$RPT")
echo "$out" | grep -q "empty list literal requires" && fail "typed empty array false positive: $out"

# 6. Return value type mismatch MUST flag.
out=$(printf 'def f() -> i64:\n    return true\n' | "$RPT")
echo "$out" | grep -q "return type expects i64, got bool" || fail "Return mismatch not flagged: $out"

# 7. Return bool->bool must NOT flag.
out=$(printf 'def f() -> bool:\n    return true\n' | "$RPT")
echo "$out" | grep -q "return type expects bool" && fail "false positive on matching Return: $out"

# 8. Field assignment type mismatch MUST flag.
out=$(printf 'struct S:\n    x: bool\ndef f() -> void:\n    s: S = S{}\n    s.x <- 5\n' | "$RPT")
echo "$out" | grep -q "expects bool, got int" || fail "Field assign mismatch not flagged: $out"

# 9. Structural generic-container mismatch MUST flag (darray <- dict).
out=$(printf 'def f() -> void:\n    a: mutable darray[i64] = []\n    b: dict[cstr, i64] = {}\n    a <- b\n' | "$RPT")
echo "$out" | grep -q "expects darray, got dict" || fail "generic container mismatch not flagged: $out"

# 10. 0 findings across frontend + stdlib (self-contained resolution set).
t=0
while IFS= read -r f; do
  c=$("$RPT" < "$f" 2>/dev/null | grep -cE " expects .*, got " || true)
  t=$((t + c))
done < <(find "$REPO_ROOT/src" "$REPO_ROOT/elisacore_std" -name '*.elisa' | grep -v _unused)
[ "$t" -eq 0 ] || fail "$t type-mismatch false positives across frontend+stdlib"

echo "assign-type smoke OK: VarDecl/Assign/<-/return/field all type-checked, conservative (firm types only), 0 FP across frontend+stdlib"
