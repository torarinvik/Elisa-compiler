#!/usr/bin/env bash
# `<-` on a bare undeclared name reports the specific "undefined assignment
# target" (parity with stage0), distinct from a plain undefined reference. A
# `<-` on a declared-mutable local is fine. 0 findings across frontend+stdlib
# (whose globals all resolve within that self-contained set).
set -uo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
command -v clang >/dev/null 2>&1 || { echo "error: missing clang" >&2; exit 2; }
RPT="$REPO_ROOT/build/parse_report"
mkdir -p "$REPO_ROOT/build"
"$ELISACORE_BIN" -emit obj -O2 -permissive -o "$REPO_ROOT/build/parse_report.o" "$REPO_ROOT/test/breadth/parse_report.elisa" >/dev/null 2>&1
clang -O2 "$REPO_ROOT/build/parse_report.o" -o "$RPT" 2>/dev/null
fail() { echo "assign-target smoke FAIL: $1" >&2; exit 1; }

# 1. `<-` on an undeclared name is flagged specifically.
out=$(printf 'def f() -> i64:\n    x <- 5\n    return x\n' | "$RPT")
echo "$out" | grep -q "undefined assignment target 'x' (use = to introduce a new local; <- requires an existing mutable target)" || fail "not flagged: $out"

# 2. `<-` on a declared-mutable local is fine.
out=$(printf 'def f() -> i64:\n    x: mutable i64 = 0\n    x <- 5\n    return x\n' | "$RPT")
echo "$out" | grep -q "undefined assignment target" && fail "false positive on declared mutable: $out"

# 3. 0 findings across frontend + stdlib (self-contained resolution set).
t=0
while IFS= read -r f; do
  c=$("$RPT" < "$f" 2>/dev/null | grep -c "undefined assignment target" || true)
  t=$((t + c))
done < <(find "$REPO_ROOT/src" "$REPO_ROOT/elisacore_std" -name '*.elisa' | grep -v _unused)
[ "$t" -eq 0 ] || fail "$t undefined-assignment-target findings across frontend+stdlib"

echo "assign-target smoke OK: flags undeclared <- target, silent on declared-mutable, 0 across frontend+stdlib"
