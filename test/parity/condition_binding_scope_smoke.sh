#!/usr/bin/env bash
# `is` bindings in the condition of an `if`/`elif`/`while` STATEMENT, and of a postfix
# guard `STMT if COND` (which desugars to an if), scope like stage0's analyzeCondExpr and
# bindConditionPatternLocals:
#   - a LATER `and` conjunct sees an earlier conjunct's bindings;
#   - an earlier conjunct, an `or` alternative and a `not` operand see none;
#   - an `or` binds only a name that EVERY alternative binds;
#   - the then-body or loop body sees what the condition binds when TRUE, the else-body
#     nothing, and nothing survives past the statement.
# stage1 used to gather every binding in the condition up front, which made all of them
# visible to the whole condition and body. `if p is q or q…` and `if not (p is q) or q…`
# then compiled silently and read `q` when `p` was null, and `if q… and p is q` got as
# far as the backend before failing. The same up-front gather missed the `is … as NAME`
# alias of a `while` condition entirely, so `while node is Expr.Pair as pair:` reported
# `pair` undefined where stage0 accepts it.
#
# Each verdict is checked against stage0 as well, so a case that drifts from the oracle
# fails here instead of pinning a guess. stage0's wording differs (`identifier "q" is
# not available here because …` for an `or`), so only the NAME is matched on its side.
# `and_under_or` passes stage0's analysis but fails its LLVM lowering, which is why this
# runs `-emit semantic` and not `-emit obj`. ternary_cond_smoke.sh section 5 pins the
# same rule for the value-position `A if COND else B`.
set -uo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
fail() { echo "condition-binding scope smoke FAIL: $1" >&2; exit 1; }

WORK_ROOT="$REPO_ROOT/build/condition-binding-scope-smoke"
mkdir -p "$WORK_ROOT"
WORK="$(mktemp -d "$WORK_ROOT/case.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

# check NAME WANT IDENT: compile $WORK/NAME.elisa with both compilers and require both to
# agree with WANT on whether IDENT resolves.
check() {
  local name="$1" want="$2" ident="$3" s0_out s1_out s0 s1
  # Capture before grepping: stage0 exits 1 exactly when it rejects, and under pipefail a
  # `stage0 | grep -q` pipeline would then read as "no match".
  s0_out=$("$ELISACORE_BIN" -emit semantic "$WORK/$name.elisa" 2>&1)
  s1_out=$("$RPT" < "$WORK/$name.elisa" 2>&1)
  s0="bound"
  grep -q "identifier \"$ident\"" <<< "$s0_out" && s0="unbound"
  s1="bound"
  grep -q "undefined identifier \"$ident\"" <<< "$s1_out" && s1="unbound"
  [ "$s0" = "$want" ] || fail "$name: stage0 (the ORACLE) says $ident is $s0, expected $want — the case itself is wrong"
  [ "$s1" = "$s0" ] || fail "$name: stage1 says $ident is $s1, stage0 says $s0"
}

# 1. An optional reference `p is q`. The body is the function's first statement; `\n`
#    starts a new line at the function's own indent, so a nested line spells out its
#    extra four spaces.
optional=0
while IFS='|' read -r name want body; do
  printf 'def f(p: u8&?, flag: bool) -> i64:\n    %b\n    return 0\n\ndef main() -> i64:\n    return f(null, false)\n' "$body" > "$WORK/$name.elisa"
  check "$name" "$want" q
  optional=$((optional + 1))
done <<'EOF'
if_and_conjunct|bound|if p is q and q.cast[i64] != 0:\n        return 2
if_paren_conjunct|bound|if (p is q and q.cast[i64] != 0):\n        return 2
if_and_under_or|bound|if flag or p is q and q.cast[i64] != 0:\n        return 2
if_body|bound|if p is q:\n        return q.cast[i64]
if_body_after_and|bound|if flag and p is q:\n        return q.cast[i64]
elif_and_conjunct|bound|if flag:\n        return 1\n    elif p is q and q.cast[i64] != 0:\n        return 2
elif_body|bound|if flag:\n        return 1\n    elif p is q:\n        return q.cast[i64]
while_and_conjunct|bound|while p is q and q.cast[i64] != 0:\n        return 2
while_body|bound|while p is q:\n        return q.cast[i64]
postfix_and_conjunct|bound|return 2 if p is q and q.cast[i64] != 0
postfix_statement|bound|return q.cast[i64] if p is q
if_or_alternative|unbound|if p is q or q.cast[i64] != 0:\n        return 2
if_not_operand|unbound|if not (p is q) or q.cast[i64] != 0:\n        return 2
if_earlier_conjunct|unbound|if q.cast[i64] != 0 and p is q:\n        return 2
if_or_then_and|unbound|if (p is q or flag) and q.cast[i64] != 0:\n        return 2
if_body_after_or|unbound|if p is q or flag:\n        return q.cast[i64]
if_body_under_not|unbound|if not (p is q):\n        return q.cast[i64]
if_body_under_double_not|unbound|if not not (p is q):\n        return q.cast[i64]
else_body|unbound|if p is q:\n        return 1\n    else:\n        return q.cast[i64]
elif_after_binding|unbound|if p is q:\n        return 1\n    elif flag:\n        return q.cast[i64]
after_if|unbound|if p is q:\n        pass\n    return q.cast[i64]
while_or_alternative|unbound|while p is q or q.cast[i64] != 0:\n        return 2
while_earlier_conjunct|unbound|while q.cast[i64] != 0 and p is q:\n        return 2
while_body_after_or|unbound|while p is q or flag:\n        return q.cast[i64]
postfix_or_alternative|unbound|return 2 if p is q or q.cast[i64] != 0
postfix_earlier_conjunct|unbound|return 2 if q.cast[i64] != 0 and p is q
postfix_statement_after_or|unbound|return q.cast[i64] if p is q or flag
EOF
[ "$optional" -eq 27 ] || fail "ran $optional of 27 optional-reference cases"

# 2. Enum payloads and the variant alias `node is Expr.Pair as pair`. An `or` binds a
#    payload name only when both alternatives bind it; the alias follows the same rule.
enum_cases=0
while IFS='|' read -r name want ident body; do
  printf 'enum Expr:\n    Pair(left: i64, right: i64)\n    Int(value: i64)\n    Wrap(value: i64)\n\ndef f(node: Expr, flag: bool) -> i64:\n    %b\n    return 7\n\ndef main() -> i64:\n    return f(Expr.Pair(3, 4), true)\n' "$body" > "$WORK/$name.elisa"
  check "$name" "$want" "$ident"
  enum_cases=$((enum_cases + 1))
done <<'EOF'
or_both_alternatives|bound|value|if node is Expr.Int(value) or node is Expr.Wrap(value):\n        return value
or_both_then_and|bound|value|if (node is Expr.Int(value) or node is Expr.Wrap(value)) and value > 2:\n        return value
or_one_alternative|unbound|left|if node is Expr.Pair(left, right) or node is Expr.Int(right):\n        return left
alias_if|bound|pair|if node is Expr.Pair as pair:\n        return pair.left
alias_after_and|bound|pair|if flag and node is Expr.Pair as pair:\n        return pair.left
alias_and_conjunct|bound|pair|if node is Expr.Pair as pair and pair.left == 3:\n        return pair.right
alias_while|bound|pair|while node is Expr.Pair as pair:\n        return pair.left
alias_or|unbound|pair|if node is Expr.Pair as pair or flag:\n        return pair.left
alias_else|unbound|pair|if node is Expr.Pair as pair:\n        return 1\n    else:\n        return pair.left
EOF
[ "$enum_cases" -eq 9 ] || fail "ran $enum_cases of 9 enum-payload cases"

echo "condition-binding scope smoke OK: $optional optional-reference and $enum_cases enum-payload statement conditions match stage0"
