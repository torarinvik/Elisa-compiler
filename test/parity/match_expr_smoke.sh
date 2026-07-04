#!/usr/bin/env bash
# Behavioral smoke: `match` as an EXPRESSION (return/assign position) parses (stage0
# accepts it; stage1 previously rejected it with "unexpected token 'match'"), and
# resolution descends into its arms. Statement-form match is unaffected.
set -uo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
command -v clang >/dev/null 2>&1 || { echo "error: missing clang" >&2; exit 2; }
RPT="$REPO_ROOT/build/parse_report"
mkdir -p "$REPO_ROOT/build"
"$ELISACORE_BIN" -emit obj -O2 -permissive -o "$REPO_ROOT/build/parse_report.o" "$REPO_ROOT/test/breadth/parse_report.elisa" >/dev/null 2>&1
clang -O2 "$REPO_ROOT/build/parse_report.o" -o "$RPT" 2>/dev/null
fail() { echo "match-expr smoke FAIL: $1" >&2; exit 1; }
E='enum E:\n    A\n    B\n'

# 1. `return match` parses with zero parse errors.
p=$(printf "${E}def f(e: E) -> i64:\n    return match e:\n        E.A: 1\n        E.B: 2\n" | "$RPT" | head -1 | awk '{print $2}')
[ "$p" = "0" ] || fail "return-match still has parse errors: P=$p"

# 2. `x = match` (assignment position) parses.
p=$(printf "${E}def f(e: E) -> i64:\n    x: i64 = match e:\n        E.A: 1\n        E.B: 2\n    return x\n" | "$RPT" | head -1 | awk '{print $2}')
[ "$p" = "0" ] || fail "assign-match still has parse errors: P=$p"

# 3. resolution descends into arms: an undefined name in an arm body is flagged.
out=$(printf "${E}def f(e: E, k: i64) -> i64:\n    return match e:\n        E.A: k\n        E.B: nope\n" | "$RPT")
echo "$out" | grep -q "undefined name 'nope'" || fail "arm body not resolved: $out"

echo "match-expr smoke OK: return/assign match-expressions parse, arms resolve"
