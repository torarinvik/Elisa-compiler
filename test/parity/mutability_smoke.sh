#!/usr/bin/env bash
# Behavioral smoke for mutability checking — assignment/compound-assignment to non-mutable
# locals/params (AssignImmutable), and mutating method calls on non-mutable containers.
set -uo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
command -v clang >/dev/null 2>&1 || { echo "error: missing clang" >&2; exit 2; }
RPT="$REPO_ROOT/build/parse_report"
mkdir -p "$REPO_ROOT/build"
"$ELISACORE_BIN" -emit obj -O2 -permissive -o "$REPO_ROOT/build/parse_report.o" "$REPO_ROOT/test/breadth/parse_report.elisa" >/dev/null 2>&1
clang -O2 "$REPO_ROOT/build/parse_report.o" -o "$RPT" 2>/dev/null
fail() { echo "mutability smoke FAIL: $1" >&2; exit 1; }

# 1. Compound-assign to immutable local MUST be flagged.
out=$(printf 'def f() -> void:\n    x: i64 = 5\n    x <- 10\n' | "$RPT")
echo "$out" | grep -q "cannot assign to immutable" || fail "compound-assign to immutable local not flagged: $out"

# 2. Regular assignment to immutable local MUST NOT be flagged (it defines a new binding).
out=$(printf 'def f() -> void:\n    x: i64 = 5\n    x = 10\n' | "$RPT")
echo "$out" | grep -q "cannot assign" && fail "false positive on defining assignment: $out"

# 3. Compound-assign to a mutable local must NOT be flagged.
out=$(printf 'def f() -> void:\n    x: mutable i64 = 5\n    x <- 10\n' | "$RPT")
echo "$out" | grep -q "cannot assign" && fail "false positive on mutable local compound-assign: $out"

# 4. push() on immutable container MUST be flagged.
out=$(printf 'def f() -> void:\n    xs: darray[i64] = []\n    xs.push(5)\n' | "$RPT")
echo "$out" | grep -q "cannot assign to immutable" || fail "push on immutable container not flagged: $out"

# 5. push() on mutable container must NOT be flagged.
out=$(printf 'def f() -> void:\n    xs: mutable darray[i64] = []\n    xs.push(5)\n' | "$RPT")
echo "$out" | grep -q "cannot assign to immutable" && fail "false positive on mutable container push: $out"

# 6. pop() on immutable container MUST be flagged.
out=$(printf 'def f() -> void:\n    xs: darray[i64] = [1, 2]\n    xs.pop()\n' | "$RPT")
echo "$out" | grep -q "cannot assign to immutable" || fail "pop on immutable container not flagged: $out"

# 7. clear() on immutable dict MUST be flagged.
out=$(printf 'def f() -> void:\n    d: dict[i64, sview] = {}\n    d.clear()\n' | "$RPT")
echo "$out" | grep -q "cannot assign to immutable" || fail "clear on immutable dict not flagged: $out"

# 8. Non-mutating method (count) on immutable container must NOT be flagged.
out=$(printf 'def f() -> void:\n    xs: darray[i64] = [1, 2]\n    n: i64 = xs.count\n' | "$RPT")
echo "$out" | grep -q "cannot assign to immutable" && fail "false positive on non-mutating count: $out"

echo "mutability smoke OK: compound-assign and mutating methods checked against mutable bindings, 0 FP"
