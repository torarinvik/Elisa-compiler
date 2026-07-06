#!/usr/bin/env bash
# Behavioral smoke for the InvalidCast check: a `.cast[T]` between two DIFFERENT numeric
# primitive types is a value conversion, not a reinterpret (stage0 requires a constructor
# T(x)). Asserts the check FIRES on a real violation AND stays silent on same-type casts,
# ref casts, struct casts, and across the whole frontend+stdlib.
set -uo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ELISA_CORE="${ELISA_CORE:-$REPO_ROOT/../../Go projects/Elisa-core}"
source "$REPO_ROOT/test/parity/resolve_elisac.sh"
command -v clang >/dev/null 2>&1 || { echo "error: missing clang" >&2; exit 2; }
RPT="$REPO_ROOT/build/parse_report"
mkdir -p "$REPO_ROOT/build"
"$ELISACORE_BIN" -emit obj -O2 -permissive -o "$REPO_ROOT/build/parse_report.o" "$REPO_ROOT/test/breadth/parse_report.elisa" >/dev/null 2>&1
clang -O2 "$REPO_ROOT/build/parse_report.o" -o "$RPT" 2>/dev/null
fail() { echo "cast-validity smoke FAIL: $1" >&2; exit 1; }
MSG="is a value conversion, not a reinterpret"

# 1. POSITIVE: different numeric primitives must be flagged.
out=$(printf 'def f(x: i32) -> u32:\n    return x.cast[u32]\n' | "$RPT")
echo "$out" | grep -q "$MSG" || fail "numeric->numeric cast not flagged: $out"

# 2. Same-type `.cast` (identity reinterpret) must stay silent.
out=$(printf 'def f(x: i32) -> i32:\n    return x.cast[i32]\n' | "$RPT")
echo "$out" | grep -q "$MSG" && fail "false positive on same-type cast: $out"

# 3. Reference reinterpret must stay silent.
out=$(printf 'def f(p: i32&) -> i64&:\n    return p.cast[i64&]\n' | "$RPT")
echo "$out" | grep -q "$MSG" && fail "false positive on ref cast: $out"

# 4. Cast to a struct (reinterpret) must stay silent.
out=$(printf 'struct S:\n    a: i64\ndef f(x: i64) -> S:\n    return x.cast[S]\n' | "$RPT")
echo "$out" | grep -q "$MSG" && fail "false positive on struct cast: $out"

# 5. Zero false positives across the whole frontend + stdlib.
t=0
while IFS= read -r f; do
    c=$("$RPT" < "$f" 2>/dev/null | grep -cE "$MSG" || true)
    t=$((t + c))
done < <(find "$REPO_ROOT/src" "$REPO_ROOT/elisacore_std" -name '*.elisa' | grep -v _unused)
[ "$t" -eq 0 ] || fail "$t cast false positives across frontend+stdlib"

echo "cast-validity smoke OK: flags different-numeric .cast, silent on same-type/ref/struct, 0 FP across frontend+stdlib"
