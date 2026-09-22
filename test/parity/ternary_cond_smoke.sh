#!/usr/bin/env bash
# Behavioral smoke for the ternary-condition check (parity with stage0's
# `ternary condition must be bool, got T`). Fires on a non-bool ternary condition,
# stays silent on a bool one and on chained ternaries with bool conditions, and
# produces 0 false positives across the frontend + stdlib.
set -uo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
fail() { echo "ternary-cond smoke FAIL: $1" >&2; exit 1; }

# 1. non-bool (int) ternary condition MUST be flagged.
# "got i64", not "got int": stage0 names a TYPED operand by its declared spelling and only
# a bare LITERAL by its family. This assertion used to pin the family name, which stage1
# printed and stage0 never did — the smoke was holding the divergence in place.
out=$(printf 'def f(n: i64) -> i64:\n    x: i64 = 1 if n else 2\n    return x\n' | "$RPT")
grep -q "ternary condition must be bool, got i64" <<< "$out" || fail "non-bool ternary cond not flagged: $out"
# The literal form still reports the FAMILY, matching stage0.
out=$(printf 'def f() -> i64:\n    x: i64 = 1 if 3 else 2\n    return x\n' | "$RPT")
grep -q "ternary condition must be bool, got int" <<< "$out" || fail "literal ternary cond not flagged: $out"

# 2. a bool condition must NOT be flagged.
out=$(printf 'def f(n: i64) -> i64:\n    x: i64 = 1 if n > 0 else 2\n    return x\n' | "$RPT")
grep -q "ternary condition" <<< "$out" && fail "false positive on bool ternary cond: $out"

# 3. chained ternary — inner bool conditions must NOT be flagged.
out=$(printf 'def f(n: i64) -> i64:\n    x: i64 = 1 if n > 0 else (2 if n < 0 else 3)\n    return x\n' | "$RPT")
grep -q "ternary condition" <<< "$out" && fail "false positive on chained bool ternary: $out"

# 4. 0 FP across frontend + stdlib.
t=0
while IFS= read -r f; do
  c=$("$RPT" < "$f" 2>/dev/null | grep -c "ternary condition" || true)
  t=$((t + c))
done < <(find "$REPO_ROOT/src" "$REPO_ROOT/elisacore_std" -name '*.elisa' | grep -v _unused)
[ "$t" -eq 0 ] || fail "$t ternary-condition false positives across frontend+stdlib"

# 5. `is` bindings in a ternary condition scope like stage0's analyzeCondExpr. A LATER
#    `and` conjunct and the true value see them. An earlier conjunct, an `or` alternative,
#    the operand of `not`, and the else value do not. stage1 once walked the condition as
#    one plain expression, which broke both halves:
#    - `2 if p is q and q… else 0` reported `q` undefined. That is the shape of
#      codegen_target_machine.elisa's PIC switch, so stage1 rejected its own compiler.
#    - the true value saw every binding, so `q if p is q or flag else 0` compiled silently.
#    Each verdict is checked against stage0 as well, so a case that drifts from the
#    oracle fails here instead of pinning a guess. stage0's wording differs
#    (`identifier "q" is not available here because …` for an `or`), so only the NAME is
#    matched on its side. `and_under_or` passes stage0's analysis but fails its LLVM
#    lowering, which is why this runs `-emit semantic` and not `-emit obj`.
WORK_ROOT="$REPO_ROOT/build/ternary-cond-smoke"
mkdir -p "$WORK_ROOT"
WORK="$(mktemp -d "$WORK_ROOT/case.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP
bindings=0
while IFS='|' read -r name want body; do
  printf 'def f(p: u8&?, flag: bool) -> i64:\n    return %s\n\ndef main() -> i64:\n    return f(null, false)\n' "$body" > "$WORK/$name.elisa"
  # Capture before grepping: stage0 exits 1 exactly when it rejects, and under pipefail a
  # `stage0 | grep -q` pipeline would then read as "no match".
  s0_out=$("$ELISACORE_BIN" -emit semantic "$WORK/$name.elisa" 2>&1)
  s1_out=$("$RPT" < "$WORK/$name.elisa" 2>&1)
  s0="bound"
  grep -q 'identifier "q"' <<< "$s0_out" && s0="unbound"
  s1="bound"
  grep -q 'undefined identifier "q"' <<< "$s1_out" && s1="unbound"
  [ "$s0" = "$want" ] || fail "$name: stage0 (the ORACLE) says q is $s0, expected $want — the case itself is wrong"
  [ "$s1" = "$s0" ] || fail "$name: stage1 says q is $s1 in \`$body\`, stage0 says $s0"
  bindings=$((bindings + 1))
done <<'EOF'
and_conjunct|bound|2 if p is q and q.cast[i64] != 0 else 0
paren_conjunct|bound|2 if (p is q and q.cast[i64] != 0) else 0
third_conjunct|bound|2 if p is q and q.cast[i64] != 0 and q.cast[i64] != 1 else 0
nested_condition|bound|2 if (3 if p is q and q.cast[i64] != 0 else 4) == 3 else 0
and_under_or|bound|2 if flag or p is q and q.cast[i64] != 0 else 0
true_value|bound|q.cast[i64] if p is q else 0
true_value_after_and|bound|q.cast[i64] if flag and p is q else 0
earlier_conjunct|unbound|2 if q.cast[i64] != 0 and p is q else 0
or_alternative|unbound|2 if p is q or q.cast[i64] != 0 else 0
not_operand|unbound|2 if not (p is q) or q.cast[i64] != 0 else 0
double_not|unbound|2 if not not (p is q) and q.cast[i64] != 0 else 0
or_then_and|unbound|2 if (p is q or flag) and q.cast[i64] != 0 else 0
else_value|unbound|2 if p is q else q.cast[i64]
true_value_after_or|unbound|q.cast[i64] if p is q or flag else 0
true_value_under_not|unbound|q.cast[i64] if not (p is q) else 0
EOF
[ "$bindings" -eq 15 ] || fail "ran $bindings of 15 condition-binding cases"

echo "ternary-cond smoke OK: flags non-bool cond, silent on bool/chained, 0 FP across frontend+stdlib, $bindings condition-binding scopes match stage0"
