#!/usr/bin/env bash
# Names bound inside a lambda body, an expression `catch` arm or an expression `match` arm
# scope like stage0's:
#   - the body resolves in ORDER, like a function body: an `is` binding follows the
#     statement-condition and ternary rules (condition_binding_scope_smoke.sh,
#     ternary_cond_smoke.sh), and a local is visible only after its declaration and only
#     inside the block that declares it;
#   - nothing a lambda or an arm binds (its params, its pattern, the catch arm's `value`,
#     an `is` binding or a local) is visible after the expression, or in a sibling arm.
# stage1 used to resolve these bodies with a flattened walker after hoisting every name
# they introduce, and to hoist the same names into the ENCLOSING scope as well. So
# `fn(r: u8&?) -> i64 => 2 if r is q or q.cast[i64] != 0 else 0` compiled silently and read
# `q` when `r` was null, and so did a use of `r` or `q` after the lambda.
#
# Each verdict is checked against stage0, so a case that drifts from the oracle fails here
# instead of pinning a guess. A `bound` case must also compile cleanly under stage0: a
# stage0 parse error prints no `identifier` message and would otherwise read as `bound`.
# stage0 parses a block lambda only where nothing follows it in the enclosing block, so
# those cases return the lambda or declare it last.
set -uo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
fail() { echo "lambda-catch binding scope smoke FAIL: $1" >&2; exit 1; }

WORK_ROOT="$REPO_ROOT/build/lambda-catch-binding-scope-smoke"
mkdir -p "$WORK_ROOT"
WORK="$(mktemp -d "$WORK_ROOT/case.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM HUP

# check NAME WANT IDENT: compile $WORK/NAME.elisa with both compilers and require both to
# agree with WANT on whether IDENT resolves.
check() {
  local name="$1" want="$2" ident="$3" s0_out s0_rc s1_out s0 s1
  # Capture before grepping: stage0 exits 1 exactly when it rejects, and under pipefail a
  # `stage0 | grep -q` pipeline would then read as "no match".
  s0_out=$("$ELISACORE_BIN" -emit semantic "$WORK/$name.elisa" 2>&1)
  s0_rc=$?
  s1_out=$("$RPT" < "$WORK/$name.elisa" 2>&1)
  s0="bound"
  grep -q "identifier \"$ident\"" <<< "$s0_out" && s0="unbound"
  s1="bound"
  grep -q "undefined identifier \"$ident\"" <<< "$s1_out" && s1="unbound"
  [ "$want" = "unbound" ] || [ "$s0_rc" -eq 0 ] || fail "$name: stage0 (the ORACLE) rejects a case meant to compile — the case itself is wrong"
  [ "$s0" = "$want" ] || fail "$name: stage0 (the ORACLE) says $ident is $s0, expected $want — the case itself is wrong"
  [ "$s1" = "$s0" ] || fail "$name: stage1 says $ident is $s1, stage0 says $s0"
}

# Each case is the whole function under test. `\n` starts a new line, so every line spells
# out its own indent.
cases=0
while IFS='|' read -r name want ident body; do
  printf 'error Problem:\n    First\n    Second\n\nenum Node:\n    Int(value: i64)\n    Pair(left: i64, right: i64)\n\ndef fallible(flag: i32) -> i64 error[Problem]:\n    raise Problem.First if flag == 1\n    return 42\n\n%b\n\ndef main() -> i64:\n    return 0\n' "$body" > "$WORK/$name.elisa"
  check "$name" "$want" "$ident"
  cases=$((cases + 1))
done <<'EOF'
lambda_arrow_and|bound|q|def f() -> i64:\n    h: fn(u8&?) -> i64 = fn(r: u8&?) -> i64 => 2 if r is q and q.cast[i64] != 0 else 0\n    return h(null)
lambda_arrow_or|unbound|q|def f() -> i64:\n    h: fn(u8&?) -> i64 = fn(r: u8&?) -> i64 => 2 if r is q or q.cast[i64] != 0 else 0\n    return h(null)
lambda_arrow_outer_local|bound|base|def f() -> i64:\n    base: i64 = 3\n    h: fn(i64) -> i64 = fn(x: i64) -> i64 => x + base\n    return h(1)
lambda_block_if_body|bound|q|def make() -> fn(u8&?) -> i64:\n    return fn(r: u8&?) -> i64:\n        if r is q:\n            return q.cast[i64]\n        return 0
lambda_block_after_if|unbound|q|def make() -> fn(u8&?) -> i64:\n    return fn(r: u8&?) -> i64:\n        if r is q:\n            pass\n        return q.cast[i64]
lambda_declared_block_after_if|unbound|q|def make() -> i64:\n    h: fn(u8&?) -> i64 = fn(r: u8&?) -> i64:\n        if r is q:\n            pass\n        return q.cast[i64]
lambda_block_local_before_declaration|unbound|z|def make() -> fn(i64) -> i64:\n    return fn(r: i64) -> i64:\n        y: i64 = z + 1\n        z: i64 = r\n        return y
lambda_block_loop_local_after_loop|unbound|t|def make() -> fn(i64) -> i64:\n    return fn(r: i64) -> i64:\n        for i in 0..<r:\n            t: i64 = i\n        return t
lambda_param_after_lambda|unbound|r|def f() -> i64:\n    h: fn(i64) -> i64 = fn(r: i64) -> i64 => r + 1\n    return r
lambda_is_after_lambda|unbound|q|def f(p: u8&?) -> i64:\n    h: fn(u8&?) -> i64 = fn(r: u8&?) -> i64 => 1 if r is q else 0\n    return q.cast[i64]
catch_value_arm_binding|bound|value|def f(flag: i32) -> i64:\n    result: i64 = catch fallible(flag):\n        value: value + 1\n        error failure: 1\n    return result
catch_value_and|bound|q|def f(p: u8&?, flag: i32) -> i64:\n    result: i64 = catch fallible(flag):\n        value: 2 if p is q and q.cast[i64] != 0 else 0\n        error failure: 1\n    return result
catch_value_or|unbound|q|def f(p: u8&?, flag: i32) -> i64:\n    result: i64 = catch fallible(flag):\n        value: 2 if p is q or q.cast[i64] != 0 else 0\n        error failure: 1\n    return result
catch_block_if_body|bound|q|def f(p: u8&?, flag: i32) -> i64:\n    result: i64 = catch fallible(flag):\n        value:\n            if p is q:\n                return q.cast[i64]\n            return value\n        error failure:\n            return 1\n    return result
catch_block_after_if|unbound|q|def f(p: u8&?, flag: i32) -> i64:\n    result: i64 = catch fallible(flag):\n        value:\n            if p is q:\n                pass\n            return q.cast[i64]\n        error failure:\n            return 1\n    return result
catch_returned_block_after_if|unbound|q|def f(p: u8&?, flag: i32) -> i64:\n    return catch fallible(flag):\n        value:\n            if p is q:\n                pass\n            return q.cast[i64]\n        error failure:\n            return 1
catch_statement_block_after_if|unbound|q|def f(p: u8&?, flag: i32) -> i64:\n    catch fallible(flag):\n        value:\n            if p is q:\n                pass\n            return q.cast[i64]\n        error failure:\n            return 1\n    return 0
catch_sibling_arm|unbound|q|def f(p: u8&?, flag: i32) -> i64:\n    result: i64 = catch fallible(flag):\n        value:\n            if p is q:\n                return 3\n            return value\n        error failure:\n            return q.cast[i64]\n    return result
catch_is_after_catch|unbound|q|def f(p: u8&?, flag: i32) -> i64:\n    result: i64 = catch fallible(flag):\n        value: 2 if p is q else 0\n        error failure: 1\n    return q.cast[i64]
catch_value_after_catch|unbound|value|def f(flag: i32) -> i64:\n    result: i64 = catch fallible(flag):\n        value: value\n        error failure: 1\n    return value
match_payload_arm|bound|v|def f(node: Node) -> i64:\n    result: i64 = match node:\n        Node.Int(v): v\n        Node.Pair(l, r): l\n    return result
match_payload_after_match|unbound|v|def f(node: Node) -> i64:\n    result: i64 = match node:\n        Node.Int(v): v\n        Node.Pair(l, r): l\n    return v
match_is_after_match|unbound|q|def f(p: u8&?, n: i64) -> i64:\n    result: i64 = match n:\n        1: 2 if p is q else 0\n        _: 0\n    return q.cast[i64]
EOF
[ "$cases" -eq 23 ] || fail "ran $cases of 23 cases"

echo "lambda-catch binding scope smoke OK: $cases lambda, catch-arm and match-arm scopes match stage0"
