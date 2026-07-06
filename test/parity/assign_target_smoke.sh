#!/usr/bin/env bash
# `<-` on a bare undeclared name reports the specific "undefined assignment
# target" (parity with stage0), distinct from a plain undefined reference. A
# `<-` on a declared-mutable local is fine. 0 findings across frontend+stdlib
# (whose globals all resolve within that self-contained set).
set -uo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
fail() { echo "assign-target smoke FAIL: $1" >&2; exit 1; }

# 1. `<-` on an undeclared name is flagged specifically.
out=$(printf 'def f() -> i64:\n    x <- 5\n    return x\n' | "$RPT")
echo "$out" | grep -q "undefined assignment target 'x' (use = to introduce a new local; <- requires an existing mutable target)" || fail "not flagged: $out"

# 2. `<-` on a declared-mutable local is fine.
out=$(printf 'def f() -> i64:\n    x: mutable i64 = 0\n    x <- 5\n    return x\n' | "$RPT")
echo "$out" | grep -q "undefined assignment target" && fail "false positive on declared mutable: $out"

# 2b. `<-` to an immutable const is rejected; to a `global mutable` is fine.
out=$(printf 'const K: i64 = 5\ndef f() -> i64:\n    K <- 10\n    return K\n' | "$RPT")
echo "$out" | grep -q "cannot assign to immutable 'K'" || fail "const write not flagged: $out"
out=$(printf 'global mutable G: i64 = 0\ndef f() -> i64:\n    G <- 10\n    return G\n' | "$RPT")
echo "$out" | grep -q "cannot assign to immutable" && fail "false positive on global mutable write: $out"

# 2c. assigning to a call result is an invalid assignment target.
out=$(printf 'def g() -> i64:\n    return 1\ndef f() -> i64:\n    g() <- 5\n    return 1\n' | "$RPT")
echo "$out" | grep -q "invalid assignment target" || fail "call-target assign not flagged: $out"

# 2d. a compound assign to an undeclared name is an undefined assignment target.
out=$(printf 'def f() -> i64:\n    y += 1\n    return 1\n' | "$RPT")
echo "$out" | grep -q "undefined assignment target 'y'" || fail "compound-assign undeclared not flagged: $out"

# 3. 0 findings across frontend + stdlib (self-contained resolution set).
t=0
while IFS= read -r f; do
  c=$("$RPT" < "$f" 2>/dev/null | grep -cE "undefined assignment target|invalid assignment target" || true)
  t=$((t + c))
done < <(find "$REPO_ROOT/src" "$REPO_ROOT/elisacore_std" -name '*.elisa' | grep -v _unused)
[ "$t" -eq 0 ] || fail "$t assignment-target findings across frontend+stdlib"

echo "assign-target smoke OK: flags undeclared <-/compound, call-target, const write; silent on declared-mutable + global mutable; 0 across frontend+stdlib"
