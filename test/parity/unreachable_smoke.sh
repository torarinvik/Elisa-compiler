#!/usr/bin/env bash
# Behavioral smoke for the stage1 UnreachableCode diagnostic (a statement following an
# unconditional `return`/`break`/`continue` in the same list is dead code — a Warning).
#
# Builds the breadth `parse_report` reporter (lex -> parse -> semantic check, emitting
# `P <n>` parse-error and `D <n>` diagnostic lines with per-finding text) and asserts the
# check FIRES on genuinely-dead code and STAYS SILENT on reachable code (no false positive
# on the common guard-then-fallthrough shape). A green run proves the check codegens and is
# behaviorally correct.
#
# Usage: test/parity/unreachable_smoke.sh   [ELISACORE_BIN=/path/to/elisac to pin]
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/structpy-tree}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"   # sets ELISACORE_BIN to a fresh build
source "$REPO_ROOT/test/parity/build_parse_report.sh"

fail() { echo "unreachable smoke FAIL: $1" >&2; exit 1; }

# 1. dead code after `return` MUST be flagged.
out=$(printf 'def f() -> i64:\n    return 1\n    x: i64 = 2\n    return x\n' | "$RPT")
echo "$out" | grep -q "unreachable code" || fail "dead code after return not flagged: $out"

# 2. dead code after `break` inside a loop MUST be flagged.
out=$(printf 'def h() -> void:\n    while true:\n        break\n        y: i64 = 1\n' | "$RPT")
echo "$out" | grep -q "unreachable code" || fail "dead code after break not flagged: $out"

# 3. guard-then-fallthrough (if returns, then a real return) must NOT be flagged.
out=$(printf 'def g(n: i64) -> i64:\n    if n > 0:\n        return n\n    return 0\n' | "$RPT")
echo "$out" | grep -q "unreachable code" && fail "false positive on guard-then-fallthrough: $out"

# 4. a `return` as the LAST statement must NOT be flagged.
out=$(printf 'def k() -> i64:\n    x: i64 = 1\n    return x\n' | "$RPT")
echo "$out" | grep -q "unreachable code" && fail "false positive on trailing return: $out"

# 5. the whole self+stdlib frontend must produce ZERO unreachable-CODE findings (no false positives).
uc=0
while IFS= read -r f; do
  n=$("$RPT" < "$f" 2>/dev/null | grep -c "unreachable code" || true)
  uc=$((uc + n))
done < <(find "$REPO_ROOT/src" -name '*.elisa' | grep -v _unused)
[ "$uc" -eq 0 ] || fail "$uc unreachable-code false positives across the frontend"

# --- UnreachableMatchArm (a duplicate/dominated match arm) ---

# 6. an exact-duplicate variant arm MUST be flagged.
out=$(printf 'enum E:\n    A\n    B\n\ndef f(e: E) -> i64:\n    match e:\n        E.A:\n            return 1\n        E.A:\n            return 2\n' | "$RPT")
echo "$out" | grep -q "unreachable because an earlier arm" || fail "duplicate variant arm not flagged: $out"

# 7. an arm after a `_` wildcard MUST be flagged.
out=$(printf 'def g(n: i64) -> i64:\n    match n:\n        _:\n            return 0\n        5:\n            return 1\n' | "$RPT")
echo "$out" | grep -q "unreachable because an earlier arm" || fail "arm after wildcard not flagged: $out"

# 8. SOUNDNESS: variant arms with DIFFERENT refutable payloads (E.A(1) vs E.A(2)) must NOT be flagged.
out=$(printf 'enum E:\n    A(x: i64)\n\ndef h(e: E) -> i64:\n    match e:\n        E.A(1):\n            return 1\n        E.A(2):\n            return 2\n' | "$RPT")
echo "$out" | grep -q "unreachable because an earlier arm" && fail "false positive on distinct payload subpatterns: $out"

# 9. SOUNDNESS: a `catch` block (success binding + error-handler arms, same Stmt.Match) must NOT be flagged.
out=$(printf 'def load(m: mutable i64&) -> void:\n    catch do_load(m):\n        n:\n            return\n        SomeError.Bad:\n            return\n        error e:\n            return\n' | "$RPT")
echo "$out" | grep -q "unreachable because an earlier arm" && fail "false positive on catch handler arms: $out"

# 10. the whole self+stdlib frontend must produce ZERO unreachable-MATCH-ARM findings.
uma=0
while IFS= read -r f; do
  n=$("$RPT" < "$f" 2>/dev/null | grep -c "unreachable because an earlier arm" || true)
  uma=$((uma + n))
done < <(find "$REPO_ROOT/src" "$REPO_ROOT/elisacore_std" -name '*.elisa' | grep -v _unused)
[ "$uma" -eq 0 ] || fail "$uma unreachable-match-arm false positives across frontend+stdlib"

echo "unreachable smoke OK: flags dead code + duplicate/dominated match arms, silent on reachable code / catch / distinct payloads, 0 false positives across frontend+stdlib"
