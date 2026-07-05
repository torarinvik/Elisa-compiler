#!/usr/bin/env bash
# Behavioral smoke for call argument count checks — ArityMismatch diagnostic.
# A direct call `f(...)` to a uniquely-named function must match that function's
# declared arity (parameter count range). Too few or too many arguments are flagged;
# overloaded names with different arities remain silent (ambiguous). 0 FP across the
# frontend + stdlib.
set -uo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
command -v clang >/dev/null 2>&1 || { echo "error: missing clang" >&2; exit 2; }
RPT="$REPO_ROOT/build/parse_report"
mkdir -p "$REPO_ROOT/build"
"$ELISACORE_BIN" -emit obj -O2 -permissive -o "$REPO_ROOT/build/parse_report.o" "$REPO_ROOT/test/breadth/parse_report.elisa" >/dev/null 2>&1
clang -O2 "$REPO_ROOT/build/parse_report.o" -o "$RPT" 2>/dev/null
fail() { echo "call-arity smoke FAIL: $1" >&2; exit 1; }

# 1. Too few arguments (no defaults): `f()` with `def f(n: i64)` MUST be flagged.
out=$(printf 'def f(n: i64) -> i64:\n    return n\n\ndef g() -> i64:\n    return f()\n' | "$RPT")
echo "$out" | grep -q "expects 1 arguments, got 0\|wrong number of arguments" || fail "missing-required-arg not flagged: $out"

# 2. Too many arguments: `f(1, 2)` with `def f(n: i64)` MUST be flagged.
out=$(printf 'def f(n: i64) -> i64:\n    return n\n\ndef g() -> i64:\n    return f(1, 2)\n' | "$RPT")
echo "$out" | grep -q "expects 1 arguments, got 2\|wrong number of arguments" || fail "extra-arg not flagged: $out"

# 3. Correct argument count must NOT be flagged.
out=$(printf 'def f(n: i64) -> i64:\n    return n\n\ndef g() -> i64:\n    return f(1)\n' | "$RPT")
echo "$out" | grep -q "expects.*arguments, got" && fail "false positive on correct arity: $out"

# 4. Overloaded function names with different arities are ambiguous (no error expected).
out=$(printf 'def f(n: i64) -> i64:\n    return n\n\ndef f(s: sview) -> i64:\n    return 0\n\ndef g() -> i64:\n    return f()\n' | "$RPT")
echo "$out" | grep -q "expects.*arguments, got" && fail "false positive on overload ambiguity: $out"

# 5. 0 FP across frontend + stdlib.
t=0
while IFS= read -r f; do
  c=$("$RPT" < "$f" 2>/dev/null | grep -cE "expects.*arguments, got" || true)
  t=$((t + c))
done < <(find "$REPO_ROOT/src" "$REPO_ROOT/elisacore_std" -name '*.elisa' | grep -v _unused)
[ "$t" -eq 0 ] || fail "$t call-arity false positives across frontend+stdlib"

echo "call-arity smoke OK: flags mismatched argument counts, silent on correct/overloaded calls, 0 FP across frontend+stdlib"
