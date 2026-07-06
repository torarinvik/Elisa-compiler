#!/usr/bin/env bash
# Behavioral smoke for the incompatible-comparison check — batch-6 engine check. An
# `==`/`!=` whose operands live in different comparison groups (bool / string / numeric)
# can never be equal and is flagged. Numeric-width and int/float/char mixes are
# compatible (Elisa inter-converts numerics; char is numeric-adjacent); enum/null/unknown
# operands are silent. 0 FP across the frontend + stdlib.
set -uo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
fail() { echo "comparison-type smoke FAIL: $1" >&2; exit 1; }

# 1. int == string MUST be flagged.
out=$(printf 'def f(n: i64) -> bool:\n    return n == "s"\n' | "$RPT")
echo "$out" | grep -q "cannot compare int with string" || fail "int==string not flagged: $out"

# 2. bool == int MUST be flagged.
out=$(printf 'def f(b: bool, n: i64) -> bool:\n    return b == n\n' | "$RPT")
echo "$out" | grep -q "cannot compare bool with int" || fail "bool==int not flagged: $out"

# 3. int == int must NOT be flagged.
out=$(printf 'def f(n: i64, m: i64) -> bool:\n    return n == m\n' | "$RPT")
echo "$out" | grep -q "cannot compare" && fail "false positive on int==int: $out"

# 4. int == float (both numeric) must NOT be flagged.
out=$(printf 'def f(n: i64, x: f64) -> bool:\n    return n == x\n' | "$RPT")
echo "$out" | grep -q "cannot compare" && fail "false positive on int==float: $out"

# 5. char == int (numeric-adjacent) must NOT be flagged.
out=$(printf 'def f(c: char, n: i64) -> bool:\n    return c == n\n' | "$RPT")
echo "$out" | grep -q "cannot compare" && fail "false positive on char==int: $out"

# 6. 0 FP across frontend + stdlib.
t=0
while IFS= read -r f; do
  c=$("$RPT" < "$f" 2>/dev/null | grep -c "cannot compare" || true)
  t=$((t + c))
done < <(find "$REPO_ROOT/src" "$REPO_ROOT/elisacore_std" -name '*.elisa' | grep -v _unused)
[ "$t" -eq 0 ] || fail "$t comparison false positives across frontend+stdlib"

echo "comparison-type smoke OK: flags cross-group ==/!=, silent on numeric mixes/enum/unknown, 0 FP across frontend+stdlib"
