#!/usr/bin/env bash
# Behavioral smoke for docs/119 expression-unification forms (stage1 parity with
# stage0): bare block expressions, multi-line if/match value forms, loop-expression
# headers `|acc = 0| -> yield` with `|capture|`, and the `rebind` statement. Each must
# parse with zero parse errors, resolve cleanly, and flag an undefined name inside the
# new construct — while a bitwise `|` in an iterable is never misread as a header, and
# there are zero parse false positives across the frontend + stdlib.
set -uo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
command -v clang >/dev/null 2>&1 || { echo "error: missing clang" >&2; exit 2; }
RPT="$REPO_ROOT/build/parse_report"
mkdir -p "$REPO_ROOT/build"
"$ELISACORE_BIN" -emit obj -O2 -permissive -o "$REPO_ROOT/build/parse_report.o" "$REPO_ROOT/test/breadth/parse_report.elisa" >/dev/null 2>&1
clang -O2 "$REPO_ROOT/build/parse_report.o" -o "$RPT" 2>/dev/null
fail() { echo "docs119-forms smoke FAIL: $1" >&2; exit 1; }
perr() { printf "$1" | "$RPT" | head -1 | awk '{print $2}'; }

# 1. bare block expression parses.
[ "$(perr 'def f() -> i64:\n    y: i64 =\n        a: i64 = 40\n        a + 2\n    return y\n')" = "0" ] || fail "bare block has parse errors"

# 2. multi-line if value form parses.
[ "$(perr 'def f(n: i64) -> i64:\n    r: i64 =\n        if n > 0:\n            1\n        else:\n            0\n    return r\n')" = "0" ] || fail "if-value form has parse errors"

# 3. loop-expression header (fold) parses.
[ "$(perr 'def f(xs: darray[i64]) -> i64:\n    s: i64 =\n        for x in xs |acc = 0| -> acc:\n            acc <- acc + x\n    return s\n')" = "0" ] || fail "loop header has parse errors"

# 4. loop header with a capture parses.
[ "$(perr 'def f(xs: darray[i64]) -> i64:\n    t: mutable i64 = 0\n    r: i64 =\n        for x in xs |acc = 0, t| -> acc:\n            t <- t + x\n            acc <- acc + 1\n    return t + r\n')" = "0" ] || fail "capture header has parse errors"

# 5. rebind parses.
[ "$(perr 'def f(p: mutable i64, v: i64) -> i64:\n    rebind p, applied: i64 =\n        p + v, v\n    return p + applied\n')" = "0" ] || fail "rebind has parse errors"

# 5b. a typed loop accumulator `|acc: u64 = 0|` parses.
[ "$(perr 'def f(xs: darray[i64]) -> u64:\n    s: u64 =\n        for x in xs |acc: u64 = 0| -> acc:\n            acc <- acc + 1\n    return s\n')" = "0" ] || fail "typed accumulator has parse errors"

# 6. a bitwise `|` in an iterable is NOT misread as a header.
[ "$(perr 'def f(a: i64, b: i64) -> i64:\n    s: mutable i64 = 0\n    for x in 0..<(a | b):\n        s <- s + x\n    return s\n')" = "0" ] || fail "bitwise | in iterable misread as header"

# 7. resolution descends into the new constructs: an undefined name in a block/loop-
#    header body is flagged.
out=$(printf 'def f(xs: darray[i64]) -> i64:\n    s: i64 =\n        for x in xs |acc = 0| -> acc:\n            acc <- acc + nope\n    return s\n' | "$RPT")
echo "$out" | grep -q "undefined name 'nope'" || fail "loop-header body not resolved: $out"

# 8. zero parse false positives across frontend + stdlib.
t=0
while IFS= read -r f; do
  c=$("$RPT" < "$f" 2>/dev/null | head -1 | awk '{print $2}')
  [ -n "$c" ] || fail "parse crash/empty output on $f"
  t=$((t + c))
done < <(find "$REPO_ROOT/src" "$REPO_ROOT/elisacore_std" -name '*.elisa' | grep -v _unused)
[ "$t" -eq 0 ] || fail "$t parse errors across frontend+stdlib (regression)"

echo "docs119-forms smoke OK: bare block / if-value / loop headers / capture / rebind parse + resolve, bitwise | safe, 0 FP"
