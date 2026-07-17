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
source "$REPO_ROOT/test/parity/build_parse_report.sh"
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

# 4. Defaulted trailing parameters may be omitted.
out=$(printf 'def add(x: i64, y: i64 = 7) -> i64:\n    return x + y\n\ndef g() -> i64:\n    return add(5)\n' | "$RPT")
echo "$out" | grep -q "expects.*arguments, got" && fail "false positive on defaulted trailing parameter: $out"

# 5. Required parameters before defaults are still required.
out=$(printf 'def add(x: i64, y: i64 = 7) -> i64:\n    return x + y\n\ndef g() -> i64:\n    return add()\n' | "$RPT")
echo "$out" | grep -q "expects 1-2 arguments, got 0\|wrong number of arguments" || fail "missing required arg before default not flagged: $out"

# 6. Required parameters after defaulted parameters are rejected.
out=$(printf 'def bad(x: i64 = 1, y: i64) -> i64:\n    return x + y\n' | "$RPT")
echo "$out" | grep -q "must declare a default because it follows a defaulted parameter" || fail "non-trailing default parameter not flagged: $out"

# 7. Named arguments may reorder parameters and omit defaulted parameters.
out=$(printf 'def sum3(x: i64, y: i64 = 1, z: i64 = 2) -> i64:\n    return x + y + z\n\ndef g() -> i64:\n    return sum3(z: 9, x: 5)\n' | "$RPT")
echo "$out" | grep -q "missing argument\|has no parameter\|specified more than once\|positional arguments after named" && fail "false positive on valid named/default call: $out"

# 8. Named calls must still provide every required parameter.
out=$(printf 'def sum3(x: i64, y: i64 = 1, z: i64 = 2) -> i64:\n    return x + y + z\n\ndef g() -> i64:\n    return sum3(z: 9)\n' | "$RPT")
echo "$out" | grep -q "missing argument for parameter 'x'" || fail "missing required named arg not flagged: $out"

# 9. Unknown named parameters are rejected.
out=$(printf 'def f(x: i64) -> i64:\n    return x\n\ndef g() -> i64:\n    return f(y: 1)\n' | "$RPT")
echo "$out" | grep -q "has no parameter 'y'" || fail "unknown named arg not flagged: $out"

# 10. A parameter may not be specified twice.
out=$(printf 'def f(x: i64, y: i64) -> i64:\n    return x + y\n\ndef g() -> i64:\n    return f(1, x: 2)\n' | "$RPT")
echo "$out" | grep -q "parameter 'x' is specified more than once" || fail "duplicate named arg not flagged: $out"

# 11. Positional arguments may not follow named arguments.
out=$(printf 'def f(x: i64, y: i64) -> i64:\n    return x + y\n\ndef g() -> i64:\n    return f(x: 1, 2)\n' | "$RPT")
echo "$out" | grep -q "cannot use positional arguments after named arguments" || fail "positional after named not flagged: $out"

# 12. Overloaded function names with different arities are ambiguous (no error expected).
out=$(printf 'def f(n: i64) -> i64:\n    return n\n\ndef f(s: sview) -> i64:\n    return 0\n\ndef g() -> i64:\n    return f()\n' | "$RPT")
echo "$out" | grep -q "expects.*arguments, got" && fail "false positive on overload ambiguity: $out"

# 13. Extern function signatures retain arity too (stage0 semantic parity).
out=$(printf 'extern alloc(size: usize) -> int\n\ndef g() -> int:\n    return alloc()\n' | "$RPT")
echo "$out" | grep -q "function 'alloc' expects 1 arguments, got 0\|wrong number of arguments" || fail "extern missing-required-arg not flagged: $out"

# 14. REGRESSION: a function named `get` must be CALLABLE. `get` is contextual (`get EXPR
# else …`), and the expression head used to route on the name alone, with no lookahead —
# so `get(1, 2, 3)` consumed the `get` and parsed `(1, 2, 3)` as the guarded expression.
# The call node VANISHED, which is why this is an arity test: the residue is a well-formed
# expression, so nothing errored — stage1 silently reported "variable expects i64, got
# tuple" where stage0 reports an arity mismatch. The gate mirrors stage0
# (parser_expr_parsepostfix…go: `Text == "get" && tokens[pos+1].Kind == TOKEN_IDENT`).
out=$(printf 'def get(n: i64) -> i64:\n    return n\n\ndef g() -> i64:\n    return get(1, 2, 3)\n' | "$RPT")
echo "$out" | grep -q "function 'get' expects 1 arguments, got 3" || fail "call to a function named 'get' was not parsed as a call: $out"

# 15. …and the `get EXPR else …` form it is contextual for must still parse.
out=$(printf 'def find(k: i64) -> i64?:\n    return 42 if k > 0 else null\n\ndef g() -> i64:\n    v: i64 = get find(1) else return 0\n    return v\n' | "$RPT")
echo "$out" | grep -q "expects.*arguments, got" && fail "false positive on the get-else form: $out"

# 16. 0 FP across frontend + stdlib.
t=0
while IFS= read -r f; do
  c=$("$RPT" < "$f" 2>/dev/null | grep -cE "expects.*arguments, got" || true)
  t=$((t + c))
done < <(find "$REPO_ROOT/src" "$REPO_ROOT/elisacore_std" -name '*.elisa' | grep -v _unused)
[ "$t" -eq 0 ] || fail "$t call-arity false positives across frontend+stdlib"

echo "call-arity smoke OK: flags mismatched argument counts, honors defaulted/named arity, rejects non-trailing defaults, silent on correct/overloaded calls, 0 FP across frontend+stdlib"
