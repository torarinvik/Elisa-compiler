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

# 1. int == string LITERAL must NOT be flagged. This assertion used to REQUIRE a
# diagnostic here, enshrining a false positive: stage0 ACCEPTS `n == "s"` all the way
# through `-emit obj` (the bare literal adapts to a byte comparison). It is not a general
# string/number exemption — rows 1b and 1c below pin the two shapes stage0 does reject.
out=$(printf 'def f(n: i64) -> bool:\n    return n == "s"\n' | "$RPT")
echo "$out" | grep -q "cannot compare" && fail "false positive on int==string literal: $out"

# 1b. a cstr VARIABLE against a number IS rejected by stage0 ("cannot compare i64 and cstr").
out=$(printf 'def f(n: i64, s: cstr) -> bool:\n    return n == s\n' | "$RPT")
echo "$out" | grep -q "cannot compare i64 and cstr" || fail "int==cstr var not flagged: $out"

# 1c. a string literal against a BOOL is rejected too — the adaptation is numeric-only.
out=$(printf 'def f(b: bool) -> bool:\n    return b == "s"\n' | "$RPT")
echo "$out" | grep -q "cannot compare bool and static u8" || fail "bool==string literal not flagged: $out"

# 2. bool == int MUST be flagged. "i64", not "int": stage0 names a TYPED operand by its
# declared spelling and only a bare literal by its family.
out=$(printf 'def f(b: bool, n: i64) -> bool:\n    return b == n\n' | "$RPT")
echo "$out" | grep -q "cannot compare bool and i64" || fail "bool==int not flagged: $out"

# 2b. the LITERAL form still reports the family, matching stage0.
out=$(printf 'def f(b: bool) -> bool:\n    return b == 1\n' | "$RPT")
echo "$out" | grep -q "cannot compare bool and int" || fail "bool==int literal not flagged: $out"

# 3. int == int must NOT be flagged.
out=$(printf 'def f(n: i64, m: i64) -> bool:\n    return n == m\n' | "$RPT")
echo "$out" | grep -q "cannot compare" && fail "false positive on int==int: $out"

# 4. int == float (both numeric) must NOT be flagged.
out=$(printf 'def f(n: i64, x: f64) -> bool:\n    return n == x\n' | "$RPT")
echo "$out" | grep -q "cannot compare" && fail "false positive on int==float: $out"

# 5. char == int (numeric-adjacent) must NOT be flagged.
out=$(printf 'def f(c: char, n: i64) -> bool:\n    return c == n\n' | "$RPT")
echo "$out" | grep -q "cannot compare" && fail "false positive on char==int: $out"

# 6. A string slice compares as text, so slice == int MUST be flagged.
out=$(printf 'def f(text: cstr[row]) -> bool:\n    return text[0:1] == 1\n' | "$RPT")
echo "$out" | grep -q "cannot compare sview and int" || fail "sview==int not flagged with surface type: $out"

# 7. String views and strings remain mutually comparable.
out=$(printf 'def f(view: sview, text: cstr[row]) -> bool:\n    return view == text\n' | "$RPT")
echo "$out" | grep -q "cannot compare" && fail "false positive on sview==cstr: $out"

# 8. A variant test requires an enum-typed value and retains a slice's surface type.
out=$(printf 'enum Flag:\n    On\n\ndef f(text: cstr[row]) -> bool:\n    return text[0:1] is Flag.On\n' | "$RPT")
echo "$out" | grep -q "is requires an enum value for variant tests, got sview" || fail "sview variant-test operand not flagged: $out"
out=$(printf 'enum Flag:\n    On\n\ndef f(flag: Flag) -> bool:\n    return flag is Flag.On\n' | "$RPT")
echo "$out" | grep -q "is requires an enum value" && fail "false positive on enum variant test: $out"

# 9. 0 FP across frontend + stdlib.
t=0
while IFS= read -r f; do
  c=$("$RPT" < "$f" 2>/dev/null | grep -cE "cannot compare|is requires an enum value for variant tests" || true)
  t=$((t + c))
done < <(find "$REPO_ROOT/src" "$REPO_ROOT/elisacore_std" -name '*.elisa' | grep -v _unused)
[ "$t" -eq 0 ] || fail "$t comparison false positives across frontend+stdlib"

echo "comparison-type smoke OK: flags cross-group ==/!=, silent on numeric mixes/enum/unknown, 0 FP across frontend+stdlib"
