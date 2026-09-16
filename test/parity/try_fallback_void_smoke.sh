#!/usr/bin/env bash
# `try VOID_CALL else <value>` — the guarded call succeeds with no value, so a value
# fallback has nothing to inhabit. stage0 rejects it as "try fallback expects void, got int".
#
# REGRESSION: stage1 had no void check on the try-fallback path. It emitted the fallback at
# the void payload type, which reached LLVMBuildAlloca with a void type and trapped inside
# LLVM's getPrefTypeAlign -- SIGTRAP (rc=133), no diagnostic, no span, no location. A crash
# with no span is easy to mis-generalise: it was first reported as "`try ... else` in statement
# position is rejected", which is false (every statement form below is accepted by both).
#
# Checks: the diagnostic fires with stage0's exact wording; the three NEIGHBOURING shapes that
# must keep working are not flagged; the compiler no longer traps; and there are no false
# positives across the whole frontend + stdlib.
set -uo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
source "$REPO_ROOT/test/parity/build_parse_report.sh"
fail() { echo "try-fallback-void smoke FAIL: $1" >&2; exit 1; }

VOID_FN='error E:\n    Bad(sview)\n\ndef may(x: i64) -> void error[E]:\n    raise E.Bad("neg") if x < 0\n\ndef noop() -> void:\n    return\n\n'
VALUE_FN='error E:\n    Bad(sview)\n\ndef may_value(x: i64) -> i64 error[E]:\n    raise E.Bad("neg") if x < 0\n    return x\n\n'

# 1. A VALUE fallback over a void payload MUST flag, with stage0's wording.
out=$(printf "${VOID_FN}def f(x: i64) -> i64:\n    try may(x) else 0\n    return 0\n" | "$RPT")
grep -q "try fallback expects void, got int" <<< "$out" || fail "void payload + int fallback not flagged: $out"

# 2. A VOID-typed call fallback is legal and must NOT flag.
out=$(printf "${VOID_FN}def f(x: i64) -> i64:\n    try may(x) else noop()\n    return 0\n" | "$RPT")
grep -q "try fallback expects void" <<< "$out" && fail "false positive on void call fallback: $out"

# 3. A CONTROL-FLOW recovery is legal and must NOT flag (the parser routes `else return`
#    to Expr.GetElse, not Expr.Refinement, so it never reaches the void branch at all).
out=$(printf "${VOID_FN}def f(x: i64) -> i64:\n    try may(x) else return 1\n    return 0\n" | "$RPT")
grep -q "try fallback expects void" <<< "$out" && fail "false positive on control-flow recovery: $out"

# 4. A value fallback over a VALUE payload is the ordinary form and must NOT flag.
out=$(printf "${VALUE_FN}def f(x: i64) -> i64:\n    v: i64 = try may_value(x) else 0\n    return v\n" | "$RPT")
grep -q "try fallback expects void" <<< "$out" && fail "false positive on value payload: $out"

# 5. The compiler must not TRAP on the offending shape, and must agree with stage0.
#    (rc=133 is 128+SIGTRAP, the original crash. Checking the rc, not the wording, is the
#    point here: a crash produced no wording at all.)
S1="${ELISA_STAGE1_BIN:-$REPO_ROOT/bin/elisac-stage1}"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
printf "${VOID_FN}def f(x: i64) -> i64:\n    try may(x) else 0\n    return 0\n\ndef main() -> i64:\n    return 0\n" > "$work/void_else.elisa"
( cd "$work" && "$S1" -emit llvm -o /dev/null void_else.elisa >/dev/null 2>&1 )
s1_rc=$?
( cd "$work" && "$ELISACORE_BIN" -emit llvm -o /dev/null void_else.elisa >/dev/null 2>&1 )
s0_rc=$?
[ "$s1_rc" != 133 ] || fail "stage1 still TRAPS (rc=133) on try-void-else-value"
[ "$s1_rc" = "$s0_rc" ] || fail "stage1 rc=$s1_rc disagrees with stage0 rc=$s0_rc"
[ "$s1_rc" != 0 ] || fail "try-void-else-value was accepted; stage0 rejects it"

# 6. 0 findings across frontend + stdlib — the check must be sound on real code.
t=0
while IFS= read -r f; do
  c=$("$RPT" < "$f" 2>/dev/null | grep -c "try fallback expects void" || true)
  t=$((t + c))
done < <(find "$REPO_ROOT/src" "$REPO_ROOT/elisacore_std" -name '*.elisa' | grep -v _unused)
[ "$t" -eq 0 ] || fail "$t try-fallback-void false positives across frontend+stdlib"

echo "try-fallback-void smoke OK: fires with stage0's wording, no trap, rc matches stage0, 0 FP across frontend+stdlib"
