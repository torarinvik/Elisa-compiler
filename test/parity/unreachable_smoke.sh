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
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"   # sets ELISACORE_BIN to a fresh build
command -v clang >/dev/null 2>&1 || { echo "error: missing clang" >&2; exit 2; }

RPT="$REPO_ROOT/build/parse_report"
mkdir -p "$REPO_ROOT/build"
"$ELISACORE_BIN" -emit obj -O2 -permissive -o "$REPO_ROOT/build/parse_report.o" "$REPO_ROOT/test/breadth/parse_report.elisa" >/dev/null 2>&1
clang -O2 "$REPO_ROOT/build/parse_report.o" -o "$RPT" 2>/dev/null

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

# 5. the whole self+stdlib frontend must produce ZERO unreachable findings (no false positives).
uc=0
while IFS= read -r f; do
  n=$("$RPT" < "$f" 2>/dev/null | grep -c "unreachable code" || true)
  uc=$((uc + n))
done < <(find "$REPO_ROOT/src" -name '*.elisa' | grep -v _unused)
[ "$uc" -eq 0 ] || fail "$uc unreachable-code false positives across the frontend"

echo "unreachable smoke OK: flags dead code after return/break, silent on reachable code, 0 false positives across the frontend"
