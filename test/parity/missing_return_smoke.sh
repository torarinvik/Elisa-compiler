#!/usr/bin/env bash
# Behavioral smoke for the stage1 MissingReturnValue diagnostic (a non-void function
# whose body does not guarantee a return on all control paths). Exercises the STAGE1
# resolver (via the parse_report harness), mirroring the other parity smokes: the
# check must FIRE on fall-through paths and STAY SILENT on guaranteed-return bodies,
# abort tails (panic/raise), and non-breaking `while true:` loops.
set -uo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
command -v clang >/dev/null 2>&1 || { echo "error: missing clang" >&2; exit 2; }
RPT="$REPO_ROOT/build/parse_report"
mkdir -p "$REPO_ROOT/build"
"$ELISACORE_BIN" -emit obj -O2 -permissive -o "$REPO_ROOT/build/parse_report.o" "$REPO_ROOT/test/breadth/parse_report.elisa" >/dev/null 2>&1
clang -O2 "$REPO_ROOT/build/parse_report.o" -o "$RPT" 2>/dev/null
fail() { echo "missing-return smoke FAIL: $1" >&2; exit 1; }

# 1. Fall-through after a guard MUST be flagged.
out=$(printf 'def f(n: i64) -> i64:\n    if n > 0:\n        return 1\n' | "$RPT")
echo "$out" | grep -q "must return a value" || fail "guard fall-through not flagged: $out"

# 2. Both-branch return must NOT be flagged.
out=$(printf 'def g(n: i64) -> i64:\n    if n > 0:\n        return 1\n    else:\n        return 0\n' | "$RPT")
echo "$out" | grep -q "must return" && fail "false positive on both-branch return: $out"

# 3. Void function must NOT be flagged.
out=$(printf 'def v(n: i64) -> void:\n    if n > 0:\n        return\n' | "$RPT")
echo "$out" | grep -q "must return" && fail "false positive on void fn: $out"

# 4. Abort tail (`panic(...)`) must NOT be flagged.
out=$(printf 'def f(n: i64) -> i64:\n    if n > 0:\n        return 1\n    panic("bad")\n' | "$RPT")
echo "$out" | grep -q "must return" && fail "false positive on panic tail: $out"

# 5. Non-breaking `while true:` must NOT be flagged.
out=$(printf 'def h(n: mutable i64) -> i64:\n    while true:\n        n <- n + 1\n' | "$RPT")
echo "$out" | grep -q "must return" && fail "false positive on while-true: $out"

# 6. `while true:` WITH a break MUST be flagged (the break path falls through).
out=$(printf 'def h(n: mutable i64) -> i64:\n    while true:\n        break\n' | "$RPT")
echo "$out" | grep -q "must return a value" || fail "breaking while-true not flagged: $out"

# 7. Guaranteed final return must NOT be flagged.
out=$(printf 'def k(n: i64) -> i64:\n    return n\n' | "$RPT")
echo "$out" | grep -q "must return" && fail "false positive on direct return: $out"

echo "missing-return smoke OK: fall-through/breaking-loop flagged, both-branch/void/panic/while-true silent, 0 FP"
